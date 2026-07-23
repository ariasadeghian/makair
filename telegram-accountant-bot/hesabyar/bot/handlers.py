"""هندلرهای بات تلگرام.

برای سادگی و پایداری، جریان‌های چندمرحله‌ای (ثبت طلب/بدهی و صدور فاکتور و
نام کسب‌وکار) با یک ماشین حالت ساده در ``context.user_data['flow']`` مدیریت
می‌شوند تا با هندلر متن آزادِ ثبت تراکنش تداخل نکنند.
"""
from __future__ import annotations

import os
import re
import tempfile
from contextlib import contextmanager

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ..core import jalali, money, nlp
from ..db.models import Direction, Kind
from ..pdf.invoice_pdf import render_invoice_pdf
from ..services import invoices as invoice_service
from ..services import ledger as ledger_service
from ..services import ocr as ocr_service
from ..services import reports as report_service
from ..services import transactions as tx_service
from . import keyboards, texts

_ITEM_SPLIT = re.compile(r"[×✕xX*]")


# --- کمک‌تابع‌ها ---------------------------------------------------------------


@contextmanager
def _session(context: ContextTypes.DEFAULT_TYPE):
    factory = context.application.bot_data["session_factory"]
    s = factory()
    try:
        yield s
    finally:
        s.close()


def _kind_label(kind: str) -> str:
    return "درآمد" if kind == Kind.INCOME else "هزینه"


def _kind_icon(kind: str) -> str:
    return texts.TX_INCOME_ICON if kind == Kind.INCOME else texts.TX_EXPENSE_ICON


def _clear_flow(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("flow", None)
    context.user_data.pop("ledger", None)
    context.user_data.pop("invoice", None)


# --- دستورها -----------------------------------------------------------------


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_flow(context)
    uid = update.effective_user.id
    with _session(context) as session:
        user = tx_service.get_or_create_user(session, uid)
        session.commit()
        has_name = bool(user.business_name)
    if has_name:
        await update.message.reply_text(texts.WELCOME_BACK, reply_markup=keyboards.main_menu())
    else:
        context.user_data["flow"] = "onboarding"
        await update.message.reply_text(texts.WELCOME)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        texts.HELP, parse_mode="HTML", reply_markup=keyboards.main_menu()
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_flow(context)
    await update.message.reply_text(texts.CANCELLED, reply_markup=keyboards.main_menu())


# --- متن آزاد ----------------------------------------------------------------


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    flow = context.user_data.get("flow")

    # جریان‌های چندمرحله‌ای
    if flow == "onboarding":
        return await _handle_onboarding(update, context, text)
    if flow in ("ledger_party", "ledger_amount", "ledger_due"):
        return await _handle_ledger_flow(update, context, text, flow)
    if flow in ("invoice_customer", "invoice_items"):
        return await _handle_invoice_flow(update, context, text, flow)

    # دکمه‌های منوی اصلی
    if text == texts.BTN_HELP:
        return await help_cmd(update, context)
    if text == texts.BTN_REPORT:
        return await update.message.reply_text(
            texts.REPORT_CHOOSE_PERIOD, reply_markup=keyboards.report_periods()
        )
    if text == texts.BTN_LEDGER:
        return await update.message.reply_text(
            texts.LEDGER_MENU, reply_markup=keyboards.ledger_menu()
        )
    if text == texts.BTN_INVOICE:
        context.user_data["flow"] = "invoice_customer"
        context.user_data["invoice"] = {"items": []}
        return await update.message.reply_text(texts.INVOICE_ASK_CUSTOMER)
    if text == texts.BTN_CANCEL:
        return await cancel(update, context)

    # در غیر این صورت: ثبت تراکنش از روی متن
    await _log_transaction(update, context, text)


async def _handle_onboarding(update, context, text: str) -> None:
    name = text.strip()
    if not name:
        return await update.message.reply_text(texts.WELCOME)
    uid = update.effective_user.id
    with _session(context) as session:
        user = tx_service.get_or_create_user(session, uid)
        user.business_name = name[:200]
        session.commit()
    _clear_flow(context)
    await update.message.reply_text(
        texts.ONBOARD_DONE.format(name=name), reply_markup=keyboards.main_menu()
    )


async def _log_transaction(update, context, text: str) -> None:
    parsed = nlp.parse_transaction(text, base=jalali.now())
    if parsed is None:
        return await update.message.reply_text(texts.UNKNOWN_INPUT)
    uid = update.effective_user.id
    with _session(context) as session:
        tx_service.get_or_create_user(session, uid)
        tx_service.add_transaction(
            session,
            uid,
            kind=parsed.kind,
            amount=parsed.amount,
            category=parsed.category,
            description=parsed.description,
            occurred_at=parsed.occurred_at,
        )
        session.commit()
    msg = (
        f"{_kind_icon(parsed.kind)} {_kind_label(parsed.kind)} ثبت شد\n"
        f"مبلغ: {money.format_amount(parsed.amount)}\n"
        f"دسته: {parsed.category}\n"
        f"تاریخ: {jalali.format_date(parsed.occurred_at)}"
    )
    await update.message.reply_text(msg, reply_markup=keyboards.main_menu())


# --- گزارش (callback) ---------------------------------------------------------


async def on_report_period(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    period = query.data.split(":", 1)[1]
    uid = update.effective_user.id
    with _session(context) as session:
        tx_service.get_or_create_user(session, uid)
        session.commit()
        report = report_service.build_report(session, uid, jalali.now(), period)
    await query.edit_message_text(report)


# --- دفتر طلب و بدهی ----------------------------------------------------------


async def on_ledger_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")  # ledger:add:receivable / ledger:list
    action = parts[1]
    uid = update.effective_user.id

    if action == "list":
        with _session(context) as session:
            tx_service.get_or_create_user(session, uid)
            session.commit()
            report = ledger_service.build_ledger_report(session, uid)
        return await query.edit_message_text(report)

    if action == "add":
        direction = parts[2]
        context.user_data["flow"] = "ledger_party"
        context.user_data["ledger"] = {"direction": direction}
        prompt = (
            texts.LEDGER_ASK_PARTY_RECEIVABLE
            if direction == Direction.RECEIVABLE
            else texts.LEDGER_ASK_PARTY_PAYABLE
        )
        await query.edit_message_text(prompt)


async def _handle_ledger_flow(update, context, text: str, flow: str) -> None:
    data = context.user_data.setdefault("ledger", {})

    if flow == "ledger_party":
        data["party_name"] = text[:200]
        context.user_data["flow"] = "ledger_amount"
        return await update.message.reply_text(texts.LEDGER_ASK_AMOUNT)

    if flow == "ledger_amount":
        amount = money.parse_amount(text)
        if amount is None:
            return await update.message.reply_text(texts.LEDGER_ASK_AMOUNT)
        data["amount"] = amount
        context.user_data["flow"] = "ledger_due"
        return await update.message.reply_text(texts.LEDGER_ASK_DUE)

    if flow == "ledger_due":
        due_date = None
        if "بدون" not in text:
            due_date = jalali.parse_relative_date(text, jalali.now())
        uid = update.effective_user.id
        with _session(context) as session:
            tx_service.get_or_create_user(session, uid)
            ledger_service.add_entry(
                session,
                uid,
                direction=data["direction"],
                party_name=data.get("party_name", "—"),
                amount=data.get("amount", 0),
                due_date=due_date,
                description="",
            )
            session.commit()
            report = ledger_service.build_ledger_report(session, uid)
        _clear_flow(context)
        await update.message.reply_text(
            f"{texts.LEDGER_SAVED}\n\n{report}", reply_markup=keyboards.main_menu()
        )


# --- فاکتور -------------------------------------------------------------------


async def _handle_invoice_flow(update, context, text: str, flow: str) -> None:
    data = context.user_data.setdefault("invoice", {"items": []})

    if flow == "invoice_customer":
        data["customer_name"] = text[:200]
        context.user_data["flow"] = "invoice_items"
        return await update.message.reply_text(texts.INVOICE_ASK_ITEM)

    if flow == "invoice_items":
        if text in ("تمام", "تموم", "پایان", "اتمام"):
            return await _finalize_invoice(update, context, data)
        item = _parse_invoice_item(text)
        if item is None:
            return await update.message.reply_text(texts.INVOICE_BAD_ITEM)
        data.setdefault("items", []).append(item)
        return await update.message.reply_text(texts.INVOICE_ITEM_ADDED)


def _parse_invoice_item(text: str) -> dict | None:
    parts = [p.strip() for p in _ITEM_SPLIT.split(text) if p.strip()]
    if len(parts) < 3:
        return None
    title = parts[0]
    quantity = money.parse_int(parts[1])
    unit_price = money.parse_amount(parts[2])
    if not title or quantity is None or quantity <= 0 or unit_price is None:
        return None
    return {"title": title[:200], "quantity": quantity, "unit_price": unit_price}


async def _finalize_invoice(update, context, data: dict) -> None:
    items = data.get("items", [])
    if not items:
        _clear_flow(context)
        return await update.message.reply_text(
            texts.INVOICE_NO_ITEMS, reply_markup=keyboards.main_menu()
        )
    await update.message.reply_text(texts.INVOICE_GENERATING)
    uid = update.effective_user.id
    out_path = None
    try:
        with _session(context) as session:
            user = tx_service.get_or_create_user(session, uid)
            invoice = invoice_service.create_invoice(
                session,
                uid,
                customer_name=data.get("customer_name", "مشتری"),
                items=items,
                issue_date=jalali.now().date(),
            )
            session.commit()
            number = invoice.number
            out_path = os.path.join(
                tempfile.gettempdir(), f"invoice_{invoice.id}.pdf"
            )
            render_invoice_pdf(invoice, user, out_path)
        with open(out_path, "rb") as fh:
            await update.message.reply_document(
                document=fh,
                filename=f"factor-{number}.pdf",
                caption=texts.INVOICE_DONE.format(number=number),
                reply_markup=keyboards.main_menu(),
            )
    finally:
        _clear_flow(context)
        if out_path and os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass


# --- عکس رسید (OCR) -----------------------------------------------------------


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    provider = context.application.bot_data.get("ocr")
    photo = update.message.photo[-1]
    tg_file = await photo.get_file()
    image_bytes = bytes(await tg_file.download_as_bytearray())
    try:
        extracted = await provider.extract_text(image_bytes)
    except ocr_service.OcrUnavailable:
        return await update.message.reply_text(texts.OCR_DISABLED)
    except Exception:
        return await update.message.reply_text(texts.OCR_FAILED)

    parsed = ocr_service.parse_receipt_text(extracted, base=jalali.now())
    if parsed is None:
        return await update.message.reply_text(texts.OCR_FAILED)
    uid = update.effective_user.id
    with _session(context) as session:
        tx_service.get_or_create_user(session, uid)
        tx_service.add_transaction(
            session,
            uid,
            kind=parsed.kind,
            amount=parsed.amount,
            category=parsed.category,
            description=parsed.description,
            occurred_at=parsed.occurred_at,
        )
        session.commit()
    msg = (
        f"📸 از روی عکس ثبت شد:\n"
        f"{_kind_icon(parsed.kind)} {_kind_label(parsed.kind)} — "
        f"{money.format_amount(parsed.amount)}\n"
        f"دسته: {parsed.category}"
    )
    await update.message.reply_text(msg, reply_markup=keyboards.main_menu())


# --- ثبت هندلرها --------------------------------------------------------------


def register(application: Application) -> None:
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CallbackQueryHandler(on_report_period, pattern=r"^report:"))
    application.add_handler(CallbackQueryHandler(on_ledger_action, pattern=r"^ledger:"))
    application.add_handler(MessageHandler(filters.PHOTO, on_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
