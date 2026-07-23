"""هندلرهای بات تلگرام.

برای سادگی و پایداری، جریان‌های چندمرحله‌ای (ثبت طلب/بدهی و صدور فاکتور و
نام کسب‌وکار) با یک ماشین حالت ساده در ``context.user_data['flow']`` مدیریت
می‌شوند تا با هندلر متن آزادِ ثبت تراکنش تداخل نکنند.
"""
from __future__ import annotations

import html
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
from ..db.models import Direction, Kind, PaymentStatus
from ..pdf.invoice_pdf import render_invoice_pdf
from ..services import backup as backup_service
from ..services import dashboard as dashboard_service
from ..services import export as export_service
from ..services import gateway as gateway_service
from ..services import invoices as invoice_service
from ..services import ledger as ledger_service
from ..services import moadian as moadian_service
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


def _tx_summary(tx) -> str:
    return f"{_kind_label(tx.kind)} {money.format_amount(tx.amount)} ({tx.category})"


async def undo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور /undo — حذف آخرین تراکنش ثبت‌شده."""
    uid = update.effective_user.id
    with _session(context) as session:
        tx = tx_service.delete_last(session, uid)
        summary = _tx_summary(tx) if tx else None
    if summary:
        await update.message.reply_text(
            texts.UNDO_DONE.format(summary=summary), reply_markup=keyboards.main_menu()
        )
    else:
        await update.message.reply_text(
            texts.UNDO_NONE, reply_markup=keyboards.main_menu()
        )


async def on_undo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه‌ی «لغو این ثبت» زیر پیام تأیید تراکنش."""
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    try:
        tx_id = int(query.data.split(":")[2])
    except (IndexError, ValueError):
        return
    with _session(context) as session:
        tx = tx_service.delete_transaction(session, uid, tx_id)
        summary = _tx_summary(tx) if tx else None
    text = texts.UNDO_DONE.format(summary=summary) if summary else texts.UNDO_NONE
    await _safe_edit(query, text)


async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور /export — خروجی اکسل تراکنش‌های ماه جاری."""
    uid = update.effective_user.id
    start, end = jalali.month_bounds(jalali.now())
    out_path = os.path.join(tempfile.gettempdir(), f"hesabyar_export_{uid}.xlsx")
    made = False
    with _session(context) as session:
        user = tx_service.get_or_create_user(session, uid)
        if tx_service.list_transactions(session, uid, start, end):
            export_service.export_transactions_xlsx(
                session, uid, start, end, out_path, business=user
            )
            made = True
    if not made:
        return await update.message.reply_text(
            texts.EXPORT_EMPTY, reply_markup=keyboards.main_menu()
        )
    try:
        with open(out_path, "rb") as fh:
            await update.message.reply_document(
                document=fh,
                filename="hesabyar-transactions.xlsx",
                caption=texts.EXPORT_CAPTION,
                reply_markup=keyboards.main_menu(),
            )
    finally:
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass


async def _send_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    out_path = os.path.join(tempfile.gettempdir(), f"hesabyar_dash_{uid}.png")
    try:
        with _session(context) as session:
            user = tx_service.get_or_create_user(session, uid)
            dashboard_service.render_dashboard_png(session, uid, out_path, business=user)
        with open(out_path, "rb") as fh:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=fh,
                caption=texts.DASHBOARD_CAPTION,
                reply_markup=keyboards.main_menu(),
            )
    finally:
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass


async def dashboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور /dashboard — داشبورد مالی تصویری."""
    await update.message.reply_text(texts.DASHBOARD_GENERATING)
    await _send_dashboard(update, context)


async def on_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه‌ی «داشبورد تصویری» زیر انتخاب دوره‌ی گزارش."""
    query = update.callback_query
    await query.answer(texts.DASHBOARD_GENERATING)
    await _send_dashboard(update, context)


async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور /backup — پشتیبان کامل داده‌های کاربر به‌صورت اکسل چندشیتی."""
    uid = update.effective_user.id
    await update.message.reply_text(texts.BACKUP_GENERATING)
    out_path = os.path.join(tempfile.gettempdir(), f"hesabyar_backup_{uid}.xlsx")
    try:
        with _session(context) as session:
            user = tx_service.get_or_create_user(session, uid)
            backup_service.export_full_user_xlsx(session, uid, out_path, business=user)
        with open(out_path, "rb") as fh:
            await update.message.reply_document(
                document=fh,
                filename="hesabyar-backup.xlsx",
                caption=texts.BACKUP_CAPTION,
                reply_markup=keyboards.main_menu(),
            )
    finally:
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass


async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور /search <کلمه> — جست‌وجو در تراکنش‌ها."""
    query_text = " ".join(context.args).strip() if context.args else ""
    if not query_text:
        return await update.message.reply_text(texts.SEARCH_USAGE, parse_mode="HTML")
    uid = update.effective_user.id
    lines = [texts.SEARCH_HEADER]
    with _session(context) as session:
        tx_service.get_or_create_user(session, uid)
        results = tx_service.search_transactions(session, uid, query_text)
        for t in results:
            lines.append(
                f"{_kind_icon(t.kind)} {money.format_amount(t.amount)} — "
                f"{html.escape(t.category)} — {jalali.format_date(t.occurred_at)}\n"
                f"<i>{html.escape(t.description or '')}</i>"
            )
    if not results:
        return await update.message.reply_text(
            texts.SEARCH_EMPTY, reply_markup=keyboards.main_menu()
        )
    await update.message.reply_text(
        "\n".join(lines), parse_mode="HTML", reply_markup=keyboards.main_menu()
    )


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
        tx = tx_service.add_transaction(
            session,
            uid,
            kind=parsed.kind,
            amount=parsed.amount,
            category=parsed.category,
            description=parsed.description,
            occurred_at=parsed.occurred_at,
        )
        session.commit()
        tx_id = tx.id
    msg = (
        f"{_kind_icon(parsed.kind)} {_kind_label(parsed.kind)} ثبت شد\n"
        f"مبلغ: {money.format_amount(parsed.amount)}\n"
        f"دسته: {parsed.category}\n"
        f"تاریخ: {jalali.format_date(parsed.occurred_at)}"
    )
    await update.message.reply_text(msg, reply_markup=keyboards.undo_transaction(tx_id))


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
            invoice_id = invoice.id
            out_path = os.path.join(
                tempfile.gettempdir(), f"invoice_{invoice.id}.pdf"
            )
            render_invoice_pdf(invoice, user, out_path)
        with open(out_path, "rb") as fh:
            await update.message.reply_document(
                document=fh,
                filename=f"factor-{number}.pdf",
                caption=texts.INVOICE_DONE.format(number=number),
                reply_markup=keyboards.moadian_send(invoice_id),
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

    # روش پرداخت: درگاه آنلاین یا کارت‌به‌کارت
    if settings.payment_method == "zarinpal":
        return await _start_zarinpal_payment(update, context, plan_key, plan)

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


async def _safe_edit(query, text: str, reply_markup=None) -> None:
    """ویرایش متن یا کپشن پیام (پیام می‌تواند عکس یا متن باشد)."""
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except Exception:
        try:
            await query.edit_message_caption(caption=text, reply_markup=reply_markup)
        except Exception:
            pass


# --- پرداخت آنلاین (زرین‌پال) -------------------------------------------------


async def _start_zarinpal_payment(update, context, plan_key: str, plan: dict) -> None:
    query = update.callback_query
    uid = update.effective_user.id
    settings = context.application.bot_data["settings"]
    gateway = gateway_service.get_gateway(settings)
    callback_url = settings.payment_callback_url or "https://t.me"
    try:
        res = await gateway.request_payment(
            plan["price"],
            description=f"اشتراک {plan['label']} حسابیار",
            callback_url=callback_url,
        )
    except gateway_service.GatewayError:
        return await _safe_edit(query, texts.GATEWAY_ERROR)

    with _session(context) as session:
        tx_service.get_or_create_user(session, uid)
        payment = sub_service.create_payment(
            session, uid, plan_key, plan["price"], reference=res["authority"]
        )
        session.commit()
        pid = payment.id
    _clear_flow(context)
    await _safe_edit(
        query,
        texts.PAYMENT_ZARINPAL_LINK.format(
            plan=plan["label"], amount=money.format_amount(plan["price"])
        ),
        reply_markup=keyboards.zarinpal_pay(res["pay_url"], pid),
    )


async def on_zarinpal_verify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه‌ی «بررسی پرداخت» — راستی‌آزمایی تراکنش زرین‌پال."""
    query = update.callback_query
    await query.answer(texts.PAYMENT_VERIFYING)
    try:
        pid = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        return
    uid = update.effective_user.id
    settings = context.application.bot_data["settings"]
    gateway = gateway_service.get_gateway(settings)

    with _session(context) as session:
        payment = sub_service.get_payment(session, pid)
        if payment is None or payment.user_id != uid:
            return await _safe_edit(query, texts.GENERIC_ERROR)
        if payment.status == PaymentStatus.APPROVED:
            status_text = sub_service.status_text(session, uid)
            return await _safe_edit(
                query,
                texts.PAYMENT_VERIFY_OK.format(
                    ref=payment.reference or "—", status=status_text
                ),
            )
        authority = payment.reference
        amount = payment.amount

    try:
        result = await gateway.verify(authority, amount)
    except gateway_service.GatewayError:
        return await _safe_edit(query, texts.PAYMENT_VERIFY_FAIL)
    if not result.get("ok"):
        return await _safe_edit(query, texts.PAYMENT_VERIFY_FAIL)

    ref_id = str(result.get("ref_id") or "—")
    with _session(context) as session:
        approved = sub_service.approve_payment(session, pid, admin_id=0)
        if approved is not None:
            approved.reference = ref_id
        status_text = sub_service.status_text(session, uid)
        session.commit()
    await _safe_edit(
        query, texts.PAYMENT_VERIFY_OK.format(ref=ref_id, status=status_text)
    )


# --- مودیان -------------------------------------------------------------------


async def on_moadian(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ارسال فاکتور به سامانه‌ی مودیان (حالت واقعی یا آزمایشی)."""
    query = update.callback_query
    await query.answer(texts.MOADIAN_SENDING)
    try:
        invoice_id = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        return
    uid = update.effective_user.id
    settings = context.application.bot_data["settings"]

    with _session(context) as session:
        user = tx_service.get_or_create_user(session, uid)
        invoice = invoice_service.get_invoice(session, invoice_id, uid)
        if invoice is None:
            return await _safe_edit(query, texts.MOADIAN_FAILED)
        payload = moadian_service.build_invoice_payload(
            invoice,
            user,
            economic_code=settings.economic_code,
            seller_tin=settings.seller_tin,
            vat_rate=settings.vat_rate,
        )

    client = moadian_service.get_moadian_client(settings)
    try:
        result = await client.submit(payload)
    except moadian_service.MoadianUnavailable:
        return await _safe_edit(query, texts.MOADIAN_FAILED)

    ref = result.get("reference") or result.get("ref") or "—"
    if result.get("status") == "dry-run":
        await _safe_edit(query, texts.MOADIAN_DRYRUN.format(ref=ref))
    else:
        await _safe_edit(query, texts.MOADIAN_OK.format(ref=ref))


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
        sub_service.get_or_create_subscription(session, uid)
        if not sub_service.is_active(session, uid):
            session.commit()
            return await update.message.reply_text(
                texts.SUB_REQUIRED, reply_markup=keyboards.subscription_plans()
            )
        tx = tx_service.add_transaction(
            session,
            uid,
            kind=parsed.kind,
            amount=parsed.amount,
            category=parsed.category,
            description=parsed.description,
            occurred_at=parsed.occurred_at,
        )
        session.commit()
        tx_id = tx.id
    msg = (
        f"📸 از روی عکس ثبت شد:\n"
        f"{_kind_icon(parsed.kind)} {_kind_label(parsed.kind)} — "
        f"{money.format_amount(parsed.amount)}\n"
        f"دسته: {parsed.category}"
    )
    await update.message.reply_text(msg, reply_markup=keyboards.undo_transaction(tx_id))


# --- ثبت هندلرها --------------------------------------------------------------


def register(application: Application) -> None:
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("undo", undo_cmd))
    application.add_handler(CommandHandler("export", export_cmd))
    application.add_handler(CommandHandler("search", search_cmd))
    application.add_handler(CommandHandler("backup", backup_cmd))
    application.add_handler(CommandHandler("dashboard", dashboard_cmd))
    application.add_handler(CallbackQueryHandler(on_report_period, pattern=r"^report:"))
    application.add_handler(CallbackQueryHandler(on_dashboard, pattern=r"^dash:"))
    application.add_handler(CallbackQueryHandler(on_ledger_action, pattern=r"^ledger:"))
    application.add_handler(CallbackQueryHandler(on_subscription, pattern=r"^sub:"))
    application.add_handler(CallbackQueryHandler(on_payment_review, pattern=r"^pay:"))
    application.add_handler(CallbackQueryHandler(on_zarinpal_verify, pattern=r"^zpv:"))
    application.add_handler(CallbackQueryHandler(on_undo, pattern=r"^tx:undo:"))
    application.add_handler(CallbackQueryHandler(on_moadian, pattern=r"^moadian:"))
    application.add_handler(MessageHandler(filters.PHOTO, on_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
