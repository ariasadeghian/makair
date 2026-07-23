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

from .. import plans
from ..core import jalali, money, nlp
from ..db.models import Direction, Kind
from ..pdf.invoice_pdf import render_invoice_pdf
from ..services import invoices as invoice_service
from ..services import ledger as ledger_service
from ..services import ocr as ocr_service
from ..services import reports as report_service
from ..services import subscription as sub_service
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
        # شروع دوره‌ی آزمایشی رایگان برای کاربر جدید
        sub_service.get_or_create_subscription(session, uid)
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
    if flow == "payment_reference":
        return await _handle_payment_flow(update, context, reference=text)

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
    if text == texts.BTN_SUBSCRIPTION:
        return await _show_subscription(update, context)
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
        sub_service.get_or_create_subscription(session, uid)
        if not sub_service.is_active(session, uid):
            session.commit()
            return await update.message.reply_text(
                texts.SUB_REQUIRED, reply_markup=keyboards.subscription_plans()
            )
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
    uid = update.effective_user.id
    with _session(context) as session:
        tx_service.get_or_create_user(session, uid)
        sub_service.get_or_create_subscription(session, uid)
        active = sub_service.is_active(session, uid)
        session.commit()
    if not active:
        _clear_flow(context)
        return await update.message.reply_text(
            texts.SUB_REQUIRED, reply_markup=keyboards.subscription_plans()
        )
    await update.message.reply_text(texts.INVOICE_GENERATING)
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


# --- اشتراک و پرداخت ----------------------------------------------------------


async def _show_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    with _session(context) as session:
        tx_service.get_or_create_user(session, uid)
        sub_service.get_or_create_subscription(session, uid)
        status = sub_service.status_text(session, uid)
        session.commit()
    await update.message.reply_text(
        f"{status}\n\n{texts.SUB_CHOOSE_PLAN}",
        parse_mode="HTML",
        reply_markup=keyboards.subscription_plans(),
    )


async def on_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """انتخاب پلن → نمایش دستور پرداخت کارت‌به‌کارت."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")  # sub:buy:<plan>
    if len(parts) < 3 or parts[1] != "buy":
        return
    plan_key = parts[2]
    plan = plans.get_plan(plan_key)
    if plan is None:
        return await query.edit_message_text(texts.GENERIC_ERROR)
    settings = context.application.bot_data["settings"]
    if not settings.card_number:
        return await query.edit_message_text(texts.PAYMENT_NO_CARD)
    context.user_data["flow"] = "payment_reference"
    context.user_data["payment"] = {"plan": plan_key}
    await query.edit_message_text(
        texts.PAYMENT_INSTRUCTIONS.format(
            plan=plan["label"],
            amount=money.format_amount(plan["price"]),
            card=settings.card_number,
            holder=settings.card_holder or "—",
        ),
        parse_mode="HTML",
    )


async def _handle_payment_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    reference: str = "",
    receipt_file_id: str | None = None,
) -> None:
    data = context.user_data.get("payment") or {}
    plan_key = data.get("plan")
    plan = plans.get_plan(plan_key) if plan_key else None
    if plan is None:
        _clear_flow(context)
        return await update.message.reply_text(
            texts.GENERIC_ERROR, reply_markup=keyboards.main_menu()
        )
    uid = update.effective_user.id
    with _session(context) as session:
        tx_service.get_or_create_user(session, uid)
        payment = sub_service.create_payment(
            session,
            uid,
            plan_key,
            plan["price"],
            reference=reference or "",
            receipt_file_id=receipt_file_id,
        )
        session.commit()
        pid = payment.id
    _clear_flow(context)
    await update.message.reply_text(
        texts.PAYMENT_SUBMITTED, reply_markup=keyboards.main_menu()
    )
    await _notify_admins_payment(context, uid, plan, pid, reference, receipt_file_id)


async def _notify_admins_payment(
    context: ContextTypes.DEFAULT_TYPE,
    uid: int,
    plan: dict,
    pid: int,
    reference: str,
    receipt_file_id: str | None,
) -> None:
    settings = context.application.bot_data["settings"]
    caption = texts.ADMIN_NEW_PAYMENT.format(
        user_id=uid,
        plan=plan["label"],
        amount=money.format_amount(plan["price"]),
        reference=reference or "—",
    )
    markup = keyboards.payment_review(pid)
    for admin_id in settings.admin_ids:
        try:
            if receipt_file_id:
                await context.bot.send_photo(
                    chat_id=admin_id, photo=receipt_file_id, caption=caption,
                    parse_mode="HTML", reply_markup=markup,
                )
            else:
                await context.bot.send_message(
                    chat_id=admin_id, text=caption, parse_mode="HTML",
                    reply_markup=markup,
                )
        except Exception:
            continue


async def on_payment_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تأیید/رد پرداخت توسط مدیر."""
    query = update.callback_query
    parts = query.data.split(":")  # pay:approve|reject:<id>
    action = parts[1] if len(parts) > 1 else ""
    try:
        pid = int(parts[2])
    except (IndexError, ValueError):
        return await query.answer()
    admin_id = update.effective_user.id
    settings = context.application.bot_data["settings"]
    if admin_id not in settings.admin_ids:
        return await query.answer(texts.ADMIN_NOT_ALLOWED, show_alert=True)
    await query.answer()

    payment = None
    approved = False
    target_uid = None
    status_text = ""
    with _session(context) as session:
        if action == "approve":
            payment = sub_service.approve_payment(session, pid, admin_id)
            if payment is not None:
                approved = True
                target_uid = payment.user_id
                status_text = sub_service.status_text(session, payment.user_id)
        else:
            payment = sub_service.reject_payment(session, pid, admin_id)
            if payment is not None:
                target_uid = payment.user_id
        session.commit()

    if payment is None:  # قبلاً بررسی شده
        return await _safe_edit(query, texts.ADMIN_PAYMENT_GONE)

    result = "تأیید شد ✅" if approved else "رد شد ❌"
    await _safe_edit(query, texts.ADMIN_PAYMENT_DONE.format(pid=pid, result=result))

    if target_uid is not None:
        try:
            if approved:
                await context.bot.send_message(
                    chat_id=target_uid,
                    text=texts.PAYMENT_APPROVED_USER.format(status=status_text),
                    parse_mode="HTML",
                    reply_markup=keyboards.main_menu(),
                )
            else:
                await context.bot.send_message(
                    chat_id=target_uid, text=texts.PAYMENT_REJECTED_USER
                )
        except Exception:
            pass


async def _safe_edit(query, text: str) -> None:
    """ویرایش متن یا کپشن پیام مدیر (پیام می‌تواند عکس یا متن باشد)."""
    try:
        await query.edit_message_text(text)
    except Exception:
        try:
            await query.edit_message_caption(caption=text)
        except Exception:
            pass


# --- عکس رسید (OCR) -----------------------------------------------------------


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # اگر کاربر در جریان پرداخت است، عکس را به‌عنوان رسید در نظر بگیر
    if context.user_data.get("flow") == "payment_reference":
        file_id = update.message.photo[-1].file_id
        return await _handle_payment_flow(
            update, context, reference="(عکس رسید)", receipt_file_id=file_id
        )
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
    application.add_handler(CallbackQueryHandler(on_subscription, pattern=r"^sub:"))
    application.add_handler(CallbackQueryHandler(on_payment_review, pattern=r"^pay:"))
    application.add_handler(MessageHandler(filters.PHOTO, on_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
