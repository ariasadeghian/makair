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

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .. import plans
from ..core import categories, group_nlp, industries, jalali, money
from ..db.models import Direction, GroupEventKind, Instrument, Kind, PaymentStatus
from ..pdf.invoice_pdf import (
    render_invoice_image,
    render_invoice_pdf,
    render_statement_image,
)
from ..services import backup as backup_service
from ..services import dashboard as dashboard_service
from ..services import export as export_service
from ..services import extract as extract_service
from ..services import gateway as gateway_service
from ..services import group_ledger as group_service
from ..services import ingest as ingest_service
from ..services import invoices as invoice_service
from ..services import ledger as ledger_service
from ..services import moadian as moadian_service
from ..services import ocr as ocr_service
from ..services import pilot as pilot_service
from ..services import products as products_service
from ..services import stt as stt_service
from ..services import reports as report_service
from ..services import subscription as sub_service
from ..services import transactions as tx_service
from . import keyboards, texts

_ITEM_SPLIT = re.compile(r"[×✕xX*]")


# --- کمک‌تابع‌ها ---------------------------------------------------------------


@contextmanager
def _session(context: ContextTypes.DEFAULT_TYPE):
    """سازگاری: به‌جای نشست دیتابیس، ``Store`` مشترک را می‌دهد.

    نوشتن‌ها با ``await`` روی همین شیء انجام می‌شوند و ``.commit()`` بی‌اثر است
    (نوشتن دسته‌ای روی گوگل‌شیت در پس‌زمینه انجام می‌شود).
    """
    yield context.application.bot_data["store"]


def _store(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data["store"]


def _kind_label(kind: str) -> str:
    return "درآمد" if kind == Kind.INCOME else "هزینه"


def _kind_icon(kind: str) -> str:
    return texts.TX_INCOME_ICON if kind == Kind.INCOME else texts.TX_EXPENSE_ICON


def _clear_flow(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("flow", None)
    context.user_data.pop("ledger", None)
    context.user_data.pop("invoice", None)
    context.user_data.pop("edit_tx", None)
    context.user_data.pop("product_tmp", None)


# --- دستورها -----------------------------------------------------------------


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is not None and chat.type in ("group", "supergroup"):
        return await update.message.reply_text(
            texts.GROUP_INTRO, parse_mode="HTML"
        )
    _clear_flow(context)
    uid = update.effective_user.id
    with _session(context) as session:
        user = await tx_service.get_or_create_user(session, uid)
        # شروع دوره‌ی آزمایشی رایگان برای کاربر جدید
        await sub_service.get_or_create_subscription(session, uid)
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
        tx = await tx_service.delete_last(session, uid)
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
        tx = await tx_service.delete_transaction(session, uid, tx_id)
        summary = _tx_summary(tx) if tx else None
    text = texts.UNDO_DONE.format(summary=summary) if summary else texts.UNDO_NONE
    await _safe_edit(query, text)


def _tx_line(tx) -> str:
    line = (
        f"{_kind_icon(tx.kind)} {_kind_label(tx.kind)} — {money.format_amount(tx.amount)}\n"
        f"دسته: {tx.category} • {jalali.format_date(tx.occurred_at)}"
    )
    if tx.description:
        line += f"\n{tx.description}"
    return line


async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور /list — تراکنش‌های اخیر با دکمه‌های اصلاح/حذف."""
    uid = update.effective_user.id
    with _session(context) as session:
        await tx_service.get_or_create_user(session, uid)
        txs = tx_service.recent(session, uid, limit=7)
    if not txs:
        return await update.message.reply_text(
            texts.LIST_EMPTY, reply_markup=keyboards.main_menu()
        )
    await update.message.reply_text(texts.LIST_HEADER)
    for tx in txs:
        await update.message.reply_text(
            _tx_line(tx), reply_markup=keyboards.transaction_actions(tx.id)
        )


async def _handle_edit_amount(update, context, text: str) -> None:
    amount = money.parse_amount(text)
    if amount is None:
        return await update.message.reply_text(texts.EDIT_ASK_AMOUNT)
    tx_id = context.user_data.get("edit_tx")
    uid = update.effective_user.id
    updated = None
    if tx_id is not None:
        with _session(context) as session:
            updated = await tx_service.update_transaction(session, uid, tx_id, amount=amount)
    _clear_flow(context)
    if updated is None:
        return await update.message.reply_text(
            texts.GENERIC_ERROR, reply_markup=keyboards.main_menu()
        )
    await update.message.reply_text(
        texts.EDIT_AMOUNT_DONE.format(amount=money.format_amount(amount)),
        reply_markup=keyboards.main_menu(),
    )


async def on_tx_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه‌های اصلاح مبلغ/دسته و حذف زیر هر تراکنش."""
    query = update.callback_query
    parts = query.data.split(":")  # tx:action:id[:idx]
    action = parts[1] if len(parts) > 1 else ""
    try:
        tx_id = int(parts[2])
    except (IndexError, ValueError):
        return await query.answer()
    uid = update.effective_user.id

    if action == "eamt":
        await query.answer()
        context.user_data["flow"] = "edit_amount"
        context.user_data["edit_tx"] = tx_id
        return await query.message.reply_text(texts.EDIT_ASK_AMOUNT)

    if action == "del":
        await query.answer()
        with _session(context) as session:
            await tx_service.delete_transaction(session, uid, tx_id)
        return await _safe_edit(query, texts.TX_DELETED)

    if action == "ecat":
        with _session(context) as session:
            tx = tx_service.get_transaction(session, uid, tx_id)
        if tx is None:
            return await query.answer(texts.GENERIC_ERROR, show_alert=True)
        await query.answer()
        try:
            await query.edit_message_reply_markup(
                reply_markup=keyboards.category_picker(tx_id, tx.kind)
            )
        except Exception:
            pass
        return

    if action == "setcat":
        try:
            idx = int(parts[3])
        except (IndexError, ValueError):
            return await query.answer()
        new_cat = None
        with _session(context) as session:
            tx = tx_service.get_transaction(session, uid, tx_id)
            if tx is not None:
                options = categories.category_options(tx.kind)
                if 0 <= idx < len(options):
                    await tx_service.update_transaction(
                        session, uid, tx_id, category=options[idx]
                    )
                    new_cat = options[idx]
        await query.answer()
        if new_cat is None:
            return await _safe_edit(query, texts.GENERIC_ERROR)
        return await _safe_edit(query, texts.EDIT_CAT_DONE.format(category=new_cat))


async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور /export — خروجی اکسل تراکنش‌های ماه جاری."""
    uid = update.effective_user.id
    start, end = jalali.month_bounds(jalali.now())
    out_path = os.path.join(tempfile.gettempdir(), f"hesabyar_export_{uid}.xlsx")
    made = False
    with _session(context) as session:
        user = await tx_service.get_or_create_user(session, uid)
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
            user = await tx_service.get_or_create_user(session, uid)
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
            user = await tx_service.get_or_create_user(session, uid)
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
        await tx_service.get_or_create_user(session, uid)
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
    await _route_text(update, context, update.message.text or "")


async def _route_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    """مسیریابی یک پیام متنی (تایپ‌شده یا رونویسی‌شده‌ی ویس) به جریان درست."""
    text = (text or "").strip()
    flow = context.user_data.get("flow")

    # جریان‌های چندمرحله‌ای
    if flow == "onboarding":
        return await _handle_onboarding(update, context, text)
    if flow in ("ledger_party", "ledger_amount", "ledger_due"):
        return await _handle_ledger_flow(update, context, text, flow)
    if flow == "statement_party":
        return await _handle_statement(update, context, text)
    if flow in ("invoice_customer", "invoice_items", "inv_discount", "inv_shipping"):
        return await _handle_invoice_flow(update, context, text, flow)
    if flow in ("prod_name", "prod_price"):
        return await _handle_product_flow(update, context, text, flow)
    if flow == "payment_reference":
        return await _handle_payment_flow(update, context, reference=text)
    if flow == "edit_amount":
        return await _handle_edit_amount(update, context, text)

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
        context.user_data["invoice"] = {"items": [], "discount": 0, "shipping": 0}
        return await update.message.reply_text(texts.INVOICE_ASK_CUSTOMER)
    if text == texts.BTN_SUBSCRIPTION:
        return await _show_subscription(update, context)
    if text == texts.BTN_CANCEL:
        return await cancel(update, context)

    # لینک فاکتور؟ (وقتی پیام لینک دارد و مبلغی داخلش نیست)
    url = ingest_service.find_url(text)
    if url and money.parse_amount(text) is None:
        return await _ingest_from_url(update, context, url)

    # در غیر این صورت: ثبت تراکنش از روی متن
    await _log_transaction(update, context, text)


async def _handle_onboarding(update, context, text: str) -> None:
    name = text.strip()
    if not name:
        return await update.message.reply_text(texts.WELCOME)
    uid = update.effective_user.id
    with _session(context) as session:
        user = await tx_service.get_or_create_user(session, uid)
        user.business_name = name[:200]
        await session.update("users", user)
    _clear_flow(context)
    # یک سؤالِ دکمه‌ای (قابل رد کردن) تا تجربه با صنفِ کاربر جور شود.
    await update.message.reply_text(
        texts.ONBOARD_ASK_INDUSTRY.format(name=name),
        reply_markup=keyboards.industry_picker(),
    )


def _industry_welcome(key: str) -> str:
    """پیامِ «حالا امتحان کن» + نکته‌های همان صنف."""
    msg = texts.ONBOARD_DONE.format(example=industries.example_for(key))
    tips = industries.tips_for(key)
    if tips:
        msg += texts.INDUSTRY_TIPS_HEADER
        for tip in tips:
            msg += f"\n• {tip}"
    return msg


async def on_industry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """انتخابِ صنفِ کسب‌وکار (دکمه‌های ``ind:<key>``)."""
    query = update.callback_query
    await query.answer()
    key = query.data.split(":", 1)[1]
    if industries.get(key) is None:
        return
    uid = update.effective_user.id
    with _session(context) as session:
        user = await tx_service.get_or_create_user(session, uid)
        user.business_type = key
        await session.update("users", user)
    await _safe_edit(query, texts.INDUSTRY_CHANGED.format(
        label=industries.label_for(key)
    ))
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=_industry_welcome(key),
        reply_markup=keyboards.main_menu(),
    )


async def industry_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تغییرِ نوعِ کسب‌وکار (/industry)."""
    await update.message.reply_text(
        texts.INDUSTRY_ASK_AGAIN, reply_markup=keyboards.industry_picker()
    )


async def _log_transaction(update, context, text: str) -> None:
    settings = context.application.bot_data["settings"]
    parsed = await extract_service.extract_transaction(settings, text, base=jalali.now())
    if parsed is None:
        return await update.message.reply_text(texts.UNKNOWN_INPUT)
    uid = update.effective_user.id
    with _session(context) as session:
        user = await tx_service.get_or_create_user(session, uid)
        await sub_service.get_or_create_subscription(session, uid)
        if not sub_service.is_active(session, uid):
            session.commit()
            return await update.message.reply_text(
                texts.SUB_REQUIRED, reply_markup=keyboards.subscription_plans()
            )
        # دسته‌ی دقیق‌ترِ صنفی (اگر کاربر صنفش را انتخاب کرده باشد)
        category = industries.refine_category(
            text, parsed.kind, user.business_type, parsed.category
        )
        tx = await tx_service.add_transaction(
            session,
            uid,
            kind=parsed.kind,
            amount=parsed.amount,
            category=category,
            description=parsed.description,
            occurred_at=parsed.occurred_at,
        )
        session.commit()
        tx_id = tx.id
        # آیا این اولین تراکنشِ کاربر است؟ (برای پیام تشویقیِ آن‌بوردینگ)
        is_first = len(session.list("transactions", lambda t: t.user_id == uid)) == 1
    msg = (
        f"{_kind_icon(parsed.kind)} {_kind_label(parsed.kind)} ثبت شد\n"
        f"مبلغ: {money.format_amount(parsed.amount)}\n"
        f"دسته: {category}\n"
        f"تاریخ: {jalali.format_date(parsed.occurred_at)}"
    )
    if is_first:
        msg += texts.FIRST_TX_CELEBRATION
    await update.message.reply_text(msg, reply_markup=keyboards.undo_transaction(tx_id))


# --- گزارش (callback) ---------------------------------------------------------


async def on_report_period(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    period = query.data.split(":", 1)[1]
    uid = update.effective_user.id
    with _session(context) as session:
        await tx_service.get_or_create_user(session, uid)
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
            await tx_service.get_or_create_user(session, uid)
            session.commit()
            report = ledger_service.build_ledger_report(session, uid)
        return await query.edit_message_text(report)

    if action == "statement":
        context.user_data["flow"] = "statement_party"
        return await query.edit_message_text(texts.STATEMENT_ASK_NAME)

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


_CHEQUE_NO_RE = re.compile(r"[\d۰-۹]{6,}")


def _detect_cheque(text: str) -> tuple:
    """(instrument, cheque_no, cleaned_name) — اگر «چک» در نام باشد.

    شماره‌ی چک (رشته‌ی ۶ رقم به بالا) و واژه‌ی «چک» از نام پاک می‌شوند.
    """
    if "چک" not in text:
        return Instrument.CASH, "", text
    match = _CHEQUE_NO_RE.search(money.to_english_digits(text))
    cheque_no = match.group() if match else ""
    name = _CHEQUE_NO_RE.sub(" ", text).replace("چک", " ")
    name = " ".join(name.split()).strip()
    return Instrument.CHEQUE, cheque_no, (name or "—")


async def _handle_ledger_flow(update, context, text: str, flow: str) -> None:
    data = context.user_data.setdefault("ledger", {})

    if flow == "ledger_party":
        instrument, cheque_no, name = _detect_cheque(text)
        data["party_name"] = name[:200]
        data["instrument"] = instrument
        data["cheque_no"] = cheque_no
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
        is_cheque = data.get("instrument") == Instrument.CHEQUE
        with _session(context) as session:
            await tx_service.get_or_create_user(session, uid)
            await ledger_service.add_entry(
                session,
                uid,
                direction=data["direction"],
                party_name=data.get("party_name", "—"),
                amount=data.get("amount", 0),
                due_date=due_date,
                description="",
                instrument=data.get("instrument", Instrument.CASH),
                cheque_no=data.get("cheque_no", ""),
            )
            session.commit()
            report = ledger_service.build_ledger_report(session, uid)
        _clear_flow(context)
        saved = (
            texts.LEDGER_SAVED_WITH_DUE.format(date=jalali.format_date(due_date))
            if due_date is not None
            else texts.LEDGER_SAVED
        )
        if is_cheque:
            saved = "🧾 چک — " + saved
        await update.message.reply_text(
            f"{saved}\n\n{report}", reply_markup=keyboards.main_menu()
        )


async def _handle_statement(update, context, text: str) -> None:
    """صورتحساب یک طرف‌حساب را به‌صورت کارتِ تصویری (و متن) می‌فرستد."""
    name = text.strip()
    _clear_flow(context)
    if not name:
        return await update.message.reply_text(texts.STATEMENT_ASK_NAME)
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    with _session(context) as session:
        user = await tx_service.get_or_create_user(session, uid)
        data = ledger_service.party_statement_data(session, uid, name, business=user)
        statement = ledger_service.build_party_statement(
            session, uid, name, business=user
        )
    if data is None:
        return await update.message.reply_text(
            texts.STATEMENT_EMPTY.format(name=name),
            reply_markup=keyboards.main_menu(),
        )
    out_path = os.path.join(tempfile.gettempdir(), f"statement_{uid}.png")
    try:
        render_statement_image(data, out_path)
        with open(out_path, "rb") as fh:
            await context.bot.send_photo(
                chat_id, photo=fh,
                caption=texts.STATEMENT_CAPTION.format(name=name),
                reply_markup=keyboards.main_menu(),
            )
    except Exception:  # noqa: BLE001 - اگر رندر تصویر نشد، متن را می‌فرستیم
        await update.message.reply_text(
            statement, parse_mode="HTML", reply_markup=keyboards.main_menu()
        )
    finally:
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass


# --- فاکتور -------------------------------------------------------------------


_FILLER = {"تا", "عدد", "عددی", "به", "قیمت", "تومان", "تومن"}


def _leading_qty(s: str) -> int | None:
    """نخستین عدد صحیح کوچک (۱ تا ۹۹۹) در متن را به‌عنوان تعداد برمی‌گرداند."""
    for tok in money.to_english_digits(s).replace("٬", "").replace(",", "").split():
        if re.fullmatch(r"\d{1,3}", tok):
            return int(tok)
    return None


def _parse_item(text: str, products: dict) -> dict | None:
    """یک قلم فاکتور را از متن می‌سازد.

    قالب‌های پذیرفته: نام کالای ذخیره‌شده (با تعداد اختیاری)، «شرح × تعداد ×
    قیمت»، یا آزاد «نام تعداد قیمت».
    """
    t = (text or "").strip()
    if not t:
        return None
    for name, prod in products.items():  # ۱) تطبیق با کالای ذخیره‌شده
        if name and name in t:
            qty = _leading_qty(t.replace(name, " ")) or 1
            return {"title": name, "quantity": qty, "unit_price": int(prod.unit_price)}
    parts = [p.strip() for p in _ITEM_SPLIT.split(t) if p.strip()]  # ۲) قالب ×
    if len(parts) >= 3:
        qty = money.parse_int(parts[1])
        price = money.parse_amount(parts[2])
        if parts[0] and qty and qty > 0 and price:
            return {"title": parts[0][:200], "quantity": qty, "unit_price": price}
    # ۳) آزاد: «[نام] [تعداد؟] [قیمت]» — نام (واژه‌های بدون رقم) از جلو، سپس
    #    اگر عددِ کوچکِ ابتدایی و عددِ دیگری بعدش بود، اولی تعداد و بقیه قیمت.
    tokens = _ITEM_SPLIT.sub(" ", t).split()

    def _has_digit(word: str) -> bool:
        return bool(re.search(r"\d", money.to_english_digits(word)))

    title_words, i = [], 0
    while i < len(tokens) and not _has_digit(tokens[i]):
        if tokens[i] not in _FILLER:
            title_words.append(tokens[i])
        i += 1
    rest = tokens[i:]
    if not rest:
        return None
    qty = 1
    first = money.to_english_digits(rest[0]).replace("٬", "").replace(",", "")
    if len(rest) >= 2 and re.fullmatch(r"\d{1,3}", first):
        qty = int(first)
        price = money.parse_amount(" ".join(rest[1:]))
    else:
        price = money.parse_amount(" ".join(rest))
    title = " ".join(title_words).strip()
    if price is None or qty <= 0 or not title:
        return None
    return {"title": title[:200], "quantity": qty, "unit_price": price}


def _builder_text(inv: dict) -> str:
    """متنِ خلاصه‌ی فاکتورِ در حال ساخت."""
    lines = [f"🧾 <b>فاکتور برای {html.escape(inv.get('customer_name', 'مشتری'))}</b>", ""]
    items = inv.get("items", [])
    if not items:
        lines.append("هنوز قلمی اضافه نشده.")
    for it in items:
        line_total = int(it["quantity"]) * int(it["unit_price"])
        lines.append(
            f"• {html.escape(it['title'])} × "
            f"{money.to_persian_digits(str(it['quantity']))} = "
            f"{money.format_amount(line_total, with_currency=False)}"
        )
    subtotal = sum(int(i["quantity"]) * int(i["unit_price"]) for i in items)
    discount, shipping = int(inv.get("discount", 0)), int(inv.get("shipping", 0))
    lines.append("")
    lines.append(f"جمع اقلام: {money.format_amount(subtotal)}")
    if discount:
        lines.append(f"تخفیف: −{money.format_amount(discount)}")
    if shipping:
        lines.append(f"ارسال: {money.format_amount(shipping)}")
    lines.append(f"<b>جمع کل: {money.format_amount(subtotal - discount + shipping)}</b>")
    lines.append("")
    lines.append("➕ روی کالاها بزنید یا دستی بنویسید: «نام تعداد قیمت»")
    return "\n".join(lines)


async def _refresh_builder(context: ContextTypes.DEFAULT_TYPE, uid: int) -> None:
    inv = context.user_data.get("invoice")
    if not inv or not inv.get("msg_id"):
        return
    with _session(context) as session:
        products = products_service.list_products(session, uid)
    try:
        await context.bot.edit_message_text(
            chat_id=inv["chat_id"], message_id=inv["msg_id"],
            text=_builder_text(inv), parse_mode="HTML",
            reply_markup=keyboards.invoice_builder(products, bool(inv.get("items"))),
        )
    except Exception:
        pass


async def _handle_invoice_flow(update, context, text: str, flow: str) -> None:
    inv = context.user_data.setdefault(
        "invoice", {"items": [], "discount": 0, "shipping": 0}
    )
    uid = update.effective_user.id

    if flow == "invoice_customer":
        inv["customer_name"] = text[:200]
        context.user_data["flow"] = "invoice_items"
        with _session(context) as session:
            products = products_service.list_products(session, uid)
        sent = await update.message.reply_text(
            _builder_text(inv), parse_mode="HTML",
            reply_markup=keyboards.invoice_builder(products, False),
        )
        inv["msg_id"], inv["chat_id"] = sent.message_id, sent.chat_id
        return

    if flow == "invoice_items":
        with _session(context) as session:
            products = {p.title: p for p in products_service.list_products(session, uid)}
        item = _parse_item(text, products)
        if item is None:
            return await update.message.reply_text(texts.INVOICE_BAD_ITEM)
        inv.setdefault("items", []).append(item)
        return await _refresh_builder(context, uid)

    if flow == "inv_discount":
        inv["discount"] = money.parse_amount(text) or 0
        context.user_data["flow"] = "inv_shipping"
        return await update.message.reply_text(texts.INVOICE_ASK_SHIPPING)

    if flow == "inv_shipping":
        inv["shipping"] = money.parse_amount(text) or 0
        context.user_data["flow"] = "invoice_items"
        await update.message.reply_text(texts.INVOICE_EXTRA_DONE)
        return await _refresh_builder(context, uid)


async def on_invoice_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه‌های ساختِ فاکتور: افزودن کالا، حذف آخرین، تخفیف/ارسال، صدور."""
    query = update.callback_query
    parts = query.data.split(":")  # inv:action[:id]
    action = parts[1] if len(parts) > 1 else ""
    uid = update.effective_user.id
    inv = context.user_data.get("invoice")
    if inv is None:
        return await query.answer()

    if action == "add":
        try:
            pid = int(parts[2])
        except (IndexError, ValueError):
            return await query.answer()
        with _session(context) as session:
            prod = products_service.get_product(session, uid, pid)
        if prod is None:
            return await query.answer()
        inv.setdefault("items", []).append(
            {"title": prod.title, "quantity": 1, "unit_price": int(prod.unit_price)}
        )
        await query.answer("افزوده شد ✅")
        return await _refresh_builder(context, uid)

    if action == "pop":
        if inv.get("items"):
            inv["items"].pop()
        await query.answer("حذف شد")
        return await _refresh_builder(context, uid)

    if action == "extra":
        context.user_data["flow"] = "inv_discount"
        await query.answer()
        return await query.message.reply_text(texts.INVOICE_ASK_DISCOUNT)

    if action == "done":
        await query.answer()
        return await _finalize_invoice(update, context)


async def _finalize_invoice(update, context) -> None:
    inv = context.user_data.get("invoice") or {}
    items = inv.get("items", [])
    chat_id = update.effective_chat.id
    if not items:
        return await context.bot.send_message(
            chat_id, texts.INVOICE_NO_ITEMS, reply_markup=keyboards.main_menu()
        )
    uid = update.effective_user.id
    settings = context.application.bot_data["settings"]

    with _session(context) as session:
        await tx_service.get_or_create_user(session, uid)
        await sub_service.get_or_create_subscription(session, uid)
        active = sub_service.is_active(session, uid)
        session.commit()
    if not active:
        _clear_flow(context)
        return await context.bot.send_message(
            chat_id, texts.SUB_REQUIRED, reply_markup=keyboards.subscription_plans()
        )

    await context.bot.send_message(chat_id, texts.INVOICE_GENERATING)
    payment_note = ""
    if settings.card_number:
        holder = f" به نام {settings.card_holder}" if settings.card_holder else ""
        payment_note = f"پرداخت: کارت‌به‌کارت به {settings.card_number}{holder}"

    img_path = pdf_path = None
    try:
        with _session(context) as session:
            user = await tx_service.get_or_create_user(session, uid)
            invoice = await invoice_service.create_invoice(
                session, uid, customer_name=inv.get("customer_name", "مشتری"),
                items=items, issue_date=jalali.now().date(),
                discount=int(inv.get("discount", 0)),
                shipping=int(inv.get("shipping", 0)),
            )
            await session.flush()  # فاکتور را فوری روی شیت بنویس
            number, invoice_id = invoice.number, invoice.id
            img_path = os.path.join(tempfile.gettempdir(), f"invoice_{invoice_id}.png")
            pdf_path = os.path.join(tempfile.gettempdir(), f"invoice_{invoice_id}.pdf")
            render_invoice_image(invoice, user, img_path, payment_note)
            render_invoice_pdf(invoice, user, pdf_path, payment_note)
        with open(img_path, "rb") as fh:
            await context.bot.send_photo(
                chat_id, photo=fh,
                caption=texts.INVOICE_DONE.format(number=number),
                reply_markup=keyboards.moadian_send(invoice_id),
            )
        with open(pdf_path, "rb") as fh:
            await context.bot.send_document(
                chat_id, document=fh, filename=f"factor-{number}.pdf",
                reply_markup=keyboards.main_menu(),
            )
    finally:
        _clear_flow(context)
        for p in (img_path, pdf_path):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


# --- کالاهای ذخیره‌شده --------------------------------------------------------


async def products_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور /products — مدیریت کالاهای ذخیره‌شده."""
    uid = update.effective_user.id
    with _session(context) as session:
        await tx_service.get_or_create_user(session, uid)
        products = products_service.list_products(session, uid)
    await update.message.reply_text(
        texts.PRODUCTS_HEADER if products else texts.PRODUCTS_EMPTY,
        reply_markup=keyboards.product_list(products),
    )


async def _handle_product_flow(update, context, text: str, flow: str) -> None:
    if flow == "prod_name":
        context.user_data["product_tmp"] = {"title": text[:200]}
        context.user_data["flow"] = "prod_price"
        return await update.message.reply_text(texts.PRODUCT_ASK_PRICE)
    if flow == "prod_price":
        price = money.parse_amount(text)
        if price is None:
            return await update.message.reply_text(texts.PRODUCT_ASK_PRICE)
        title = (context.user_data.get("product_tmp") or {}).get("title", "کالا")
        uid = update.effective_user.id
        with _session(context) as session:
            await products_service.add_product(session, uid, title, price)
            products = products_service.list_products(session, uid)
        _clear_flow(context)
        await update.message.reply_text(
            texts.PRODUCT_SAVED.format(title=title, price=money.format_amount(price)),
            reply_markup=keyboards.product_list(products),
        )


async def on_product_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه‌های افزودن/حذف کالا."""
    query = update.callback_query
    parts = query.data.split(":")  # prod:add / prod:del:<id>
    action = parts[1] if len(parts) > 1 else ""
    uid = update.effective_user.id

    if action == "add":
        context.user_data["flow"] = "prod_name"
        await query.answer()
        return await query.message.reply_text(texts.PRODUCT_ASK_NAME)

    if action == "del":
        try:
            pid = int(parts[2])
        except (IndexError, ValueError):
            return await query.answer()
        with _session(context) as session:
            await products_service.delete_product(session, uid, pid)
            products = products_service.list_products(session, uid)
        await query.answer("حذف شد 🗑")
        try:
            await query.edit_message_reply_markup(
                reply_markup=keyboards.product_list(products)
            )
        except Exception:
            pass


# --- اشتراک و پرداخت ----------------------------------------------------------


async def _show_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    with _session(context) as session:
        await tx_service.get_or_create_user(session, uid)
        await sub_service.get_or_create_subscription(session, uid)
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
        await tx_service.get_or_create_user(session, uid)
        payment = await sub_service.create_payment(
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
            payment = await sub_service.approve_payment(session, pid, admin_id)
            if payment is not None:
                approved = True
                target_uid = payment.user_id
                status_text = sub_service.status_text(session, payment.user_id)
        else:
            payment = await sub_service.reject_payment(session, pid, admin_id)
            if payment is not None:
                target_uid = payment.user_id
        await session.flush()  # وضعیت پرداخت را فوری روی شیت بنویس

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
        await tx_service.get_or_create_user(session, uid)
        payment = await sub_service.create_payment(
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
        approved = await sub_service.approve_payment(session, pid, admin_id=0)
        if approved is not None:
            approved.reference = ref_id
            await session.update("payments", approved)
        status_text = sub_service.status_text(session, uid)
        await session.flush()  # پرداخت آنلاین را فوری روی شیت بنویس
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
        user = await tx_service.get_or_create_user(session, uid)
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


# --- خواندن فاکتور: عکس، فایل، لینک ------------------------------------------


async def _process_receipt_image(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    image_bytes: bytes,
    source_label: str,
) -> None:
    """بایت‌های تصویر را OCR می‌کند و به‌عنوان تراکنش ثبت می‌کند."""
    provider = context.application.bot_data.get("ocr")
    if provider is None or isinstance(provider, ocr_service.NullOcrProvider):
        return await update.message.reply_text(texts.OCR_DISABLED)
    await update.message.reply_text(texts.OCR_READING)
    try:
        extracted = await provider.extract_text(image_bytes)
    except ocr_service.OcrUnavailable:
        return await update.message.reply_text(texts.OCR_DISABLED)
    except Exception:
        return await update.message.reply_text(texts.OCR_FAILED)

    settings = context.application.bot_data["settings"]
    parsed = await extract_service.extract_transaction(
        settings, extracted, base=jalali.now()
    )
    if parsed is None:
        return await update.message.reply_text(texts.OCR_FAILED)

    vendor = getattr(parsed, "vendor", "")
    description = parsed.description or ""
    if vendor and vendor not in description:
        description = f"{vendor} — {description}".strip(" —")

    uid = update.effective_user.id
    with _session(context) as session:
        user = await tx_service.get_or_create_user(session, uid)
        await sub_service.get_or_create_subscription(session, uid)
        if not sub_service.is_active(session, uid):
            session.commit()
            return await update.message.reply_text(
                texts.SUB_REQUIRED, reply_markup=keyboards.subscription_plans()
            )
        category = industries.refine_category(
            extracted, parsed.kind, user.business_type, parsed.category
        )
        tx = await tx_service.add_transaction(
            session, uid, kind=parsed.kind, amount=parsed.amount,
            category=category, description=description,
            occurred_at=parsed.occurred_at,
        )
        session.commit()
        tx_id = tx.id

    lines = [
        f"{source_label} ثبت شد:",
        f"{_kind_icon(parsed.kind)} {_kind_label(parsed.kind)} — "
        f"{money.format_amount(parsed.amount)}",
        f"دسته: {category}",
    ]
    if vendor:
        lines.append(f"فروشنده: {vendor}")
    lines.append(f"تاریخ: {jalali.format_date(parsed.occurred_at)}")
    invoice_number = getattr(parsed, "invoice_number", "")
    if invoice_number:
        lines.append(f"شماره فاکتور: {invoice_number}")
    await update.message.reply_text(
        "\n".join(lines), reply_markup=keyboards.undo_transaction(tx_id)
    )


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عکس فاکتور/رسید (دوربین یا گالری)."""
    if context.user_data.get("flow") == "payment_reference":
        file_id = update.message.photo[-1].file_id
        return await _handle_payment_flow(
            update, context, reference="(عکس رسید)", receipt_file_id=file_id
        )
    tg_file = await update.message.photo[-1].get_file()
    image_bytes = bytes(await tg_file.download_as_bytearray())
    await _process_receipt_image(update, context, image_bytes, texts.INGEST_SOURCE_PHOTO)


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """فایل فاکتور: عکس یا PDF (به‌صورت فایل یا فوروارد)."""
    doc = update.message.document
    if doc is None:
        return
    mime = (doc.mime_type or "").lower()
    name = (doc.file_name or "").lower()
    is_pdf = "pdf" in mime or name.endswith(".pdf")
    is_image = mime.startswith("image/")
    if not (is_pdf or is_image):
        return await update.message.reply_text(texts.INGEST_UNSUPPORTED)
    if context.user_data.get("flow") == "payment_reference":
        return await _handle_payment_flow(
            update, context, reference="(رسید فایل)", receipt_file_id=doc.file_id
        )
    tg_file = await doc.get_file()
    raw = bytes(await tg_file.download_as_bytearray())
    try:
        image_bytes = ingest_service.prepare_image(raw, mime)
    except ingest_service.IngestError as exc:
        return await update.message.reply_text(str(exc))
    await _process_receipt_image(update, context, image_bytes, texts.INGEST_SOURCE_FILE)


async def _ingest_from_url(
    update: Update, context: ContextTypes.DEFAULT_TYPE, url: str
) -> None:
    """خواندن فاکتور از روی یک لینک."""
    provider = context.application.bot_data.get("ocr")
    if provider is None or isinstance(provider, ocr_service.NullOcrProvider):
        return await update.message.reply_text(texts.OCR_DISABLED)
    try:
        raw, content_type = await ingest_service.fetch_bytes(url)
        image_bytes = ingest_service.prepare_image(raw, content_type)
    except ingest_service.IngestError as exc:
        return await update.message.reply_text(f"{texts.INGEST_LINK_FAILED}\n{exc}")
    await _process_receipt_image(update, context, image_bytes, texts.INGEST_SOURCE_LINK)


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پیام صوتی (ویس/فایل صوتی): به متن تبدیل و مثل متن معمولی پردازش می‌شود."""
    msg = update.message
    media = msg.voice or msg.audio
    if media is None:
        return

    provider = context.application.bot_data.get("stt")
    if provider is None or isinstance(provider, stt_service.NullSttProvider):
        return await msg.reply_text(texts.VOICE_DISABLED)

    # سقف مدت تا هزینه و تأخیر کنترل شود (۵ دقیقه).
    duration = getattr(media, "duration", 0) or 0
    if duration > 300:
        return await msg.reply_text(texts.VOICE_TOO_LONG)

    await msg.reply_text(texts.VOICE_TRANSCRIBING)
    try:
        tg_file = await media.get_file()
        audio_bytes = bytes(await tg_file.download_as_bytearray())
    except Exception:
        return await msg.reply_text(texts.VOICE_FAILED)

    mime = getattr(media, "mime_type", None) or "audio/ogg"
    filename = getattr(media, "file_name", None) or "voice.ogg"
    try:
        text = await provider.transcribe(
            audio_bytes, mime_type=mime, filename=filename
        )
    except stt_service.SttUnavailable:
        return await msg.reply_text(texts.VOICE_FAILED)
    except Exception:  # noqa: BLE001 - هر خطای غیرمنتظره‌ی رونویسی
        return await msg.reply_text(texts.VOICE_FAILED)

    text = (text or "").strip()
    if not text:
        return await msg.reply_text(texts.VOICE_EMPTY)

    # آنچه شنیده شد را نشان بده تا کاربر مطمئن شود درست فهمیده‌ایم.
    await msg.reply_text(texts.VOICE_HEARD.format(text=text))
    await _route_text(update, context, text)


# --- حالت گروه (دفتر مالی گروهی) ---------------------------------------------


def _display_name(user) -> str:
    """نام نمایشیِ یک کاربر تلگرام."""
    if user is None:
        return "—"
    name = (getattr(user, "full_name", "") or "").strip()
    if not name:
        uname = (getattr(user, "username", "") or "").strip()
        name = f"@{uname}" if uname else str(getattr(user, "id", "") or "")
    return name or "—"


def _mentioned_party(message) -> tuple:
    """(id, name) طرفِ اشاره‌شده: text_mention، سپس @username، سپس ریپلای."""
    text = message.text or ""
    entities = message.entities or []
    for ent in entities:  # text_mention: شیء کاربر کامل را داریم
        if ent.type == "text_mention" and ent.user is not None:
            return ent.user.id, _display_name(ent.user)
    for ent in entities:  # @username: فقط نام کاربری متنی
        if ent.type == "mention":
            return None, text[ent.offset: ent.offset + ent.length]
    reply = getattr(message, "reply_to_message", None)
    if reply is not None and reply.from_user is not None:
        return reply.from_user.id, _display_name(reply.from_user)
    return None, ""


async def on_group_added(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """وقتی بات به گروه اضافه می‌شود، خودش را معرفی می‌کند."""
    msg = update.message
    if msg is None or not msg.new_chat_members:
        return
    if any(m.id == context.bot.id for m in msg.new_chat_members):
        await msg.reply_text(texts.GROUP_INTRO, parse_mode="HTML")


async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """گزارش وضعیت مالی گروه (/balance)."""
    chat = update.effective_chat
    if chat is None or chat.type not in ("group", "supergroup"):
        return await update.message.reply_text(texts.GROUP_PRIVATE_ONLY)
    store = _store(context)
    await update.message.reply_text(
        group_service.build_group_report(store, chat.id), parse_mode="HTML"
    )


async def pilot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """داشبورد سنجه‌های پایلوت (فقط ادمین)."""
    settings = context.application.bot_data["settings"]
    uid = update.effective_user.id
    if uid not in settings.admin_ids:
        return await update.message.reply_text(texts.ADMIN_NOT_ALLOWED)
    store = _store(context)
    metrics = pilot_service.compute_pilot_metrics(store, jalali.now())
    await update.message.reply_text(
        pilot_service.build_pilot_report(metrics), parse_mode="HTML"
    )


def _group_confirm_body(pending: dict) -> str:
    """متن «ثبتش کنم؟» را از روی دادهٔ در انتظار می‌سازد."""
    amount = pending.get("amount")
    amount_str = money.format_amount(amount) if amount else "؟"
    reason = pending.get("reason") or ""
    reason_line = f"\nبابت: {reason}" if reason else ""
    actor = pending.get("actor_name") or "—"
    cp = pending.get("counterparty_name") or "—"
    if pending["kind"] == GroupEventKind.REQUEST:
        head = texts.GROUP_CONFIRM_REQUEST
        who = f"{actor} از {cp}: {amount_str}"
    else:
        head = texts.GROUP_CONFIRM_PAYMENT
        to = f" به {cp}" if pending.get("counterparty_name") else ""
        who = f"{actor}{to}: {amount_str}"
    return f"{head}\n{who}{reason_line}\n\n{texts.GROUP_CONFIRM_ASK}"


async def on_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """رصد پیام‌های گروه؛ رویداد مالی را تشخیص و برای تأیید پیشنهاد می‌دهد.

    فقط وقتی کار می‌کند که Privacy Mode بات خاموش باشد (تا همه‌ی پیام‌ها را ببیند).
    """
    msg = update.message
    if msg is None or not msg.text:
        return
    parsed = group_nlp.detect_group_event(msg.text)
    if parsed is None:
        return
    sender = update.effective_user
    if sender is None:
        return

    chat_id = msg.chat_id
    store = _store(context)
    cp_id, cp_name = _mentioned_party(msg)
    pending = {
        "kind": parsed.kind,
        "chat_id": chat_id,
        "actor_id": sender.id,
        "actor_name": _display_name(sender),
        "reason": parsed.reason,
        "amount": parsed.amount,
        "counterparty_id": cp_id,
        "counterparty_name": cp_name,
        "request_id": None,
    }

    if parsed.kind == GroupEventKind.PAYMENT:
        # آیا این پرداخت به یک درخواستِ بازِ همین شخص می‌خورد؟
        req = group_service.find_open_request_for(
            store, chat_id, sender.id, parsed.amount
        )
        if req is not None:
            pending["request_id"] = req.id
            pending["amount"] = parsed.amount or req.amount
            if not pending["reason"]:
                pending["reason"] = req.reason
            if not pending["counterparty_id"] and not pending["counterparty_name"]:
                pending["counterparty_id"] = req.actor_id
                pending["counterparty_name"] = req.actor_name
        if not pending["amount"]:
            return  # بدون مبلغ و بدون درخواستِ متناظر، چیزی برای ثبت نیست
    else:  # REQUEST
        if not parsed.amount:
            return  # درخواستِ بدون مبلغ را نادیده بگیر (نویز)

    token = msg.message_id
    context.chat_data.setdefault("grp_pending", {})[token] = pending
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(texts.BTN_GROUP_CONFIRM, callback_data=f"grp:ok:{token}"),
        InlineKeyboardButton(texts.BTN_GROUP_REJECT, callback_data=f"grp:no:{token}"),
    ]])
    await msg.reply_text(
        _group_confirm_body(pending), reply_markup=keyboard, parse_mode="HTML"
    )


async def _grp_edit(query, text: str) -> None:
    try:
        await query.edit_message_text(text, parse_mode="HTML")
    except Exception:
        pass


async def on_group_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه‌های «✅ ثبت کن / ❌ نه» زیر پیشنهادِ رویداد گروه."""
    query = update.callback_query
    await query.answer()
    try:
        _, action, token_s = query.data.split(":")
        token = int(token_s)
    except (ValueError, AttributeError):
        return
    pending = (context.chat_data.get("grp_pending") or {}).pop(token, None)
    if pending is None:
        return await _grp_edit(query, texts.GROUP_STALE)
    if action == "no":
        return await _grp_edit(query, texts.GROUP_DISCARDED)

    store = _store(context)
    chat_id = pending["chat_id"]
    if pending["kind"] == GroupEventKind.REQUEST:
        await group_service.add_request(
            store, chat_id,
            requester_id=pending["actor_id"],
            requester_name=pending["actor_name"],
            payer_id=pending["counterparty_id"],
            payer_name=pending["counterparty_name"],
            amount=pending["amount"], reason=pending["reason"],
        )
        head = texts.GROUP_SAVED_REQUEST
    else:
        await group_service.add_payment(
            store, chat_id,
            payer_id=pending["actor_id"],
            payer_name=pending["actor_name"],
            payee_id=pending["counterparty_id"],
            payee_name=pending["counterparty_name"],
            amount=pending["amount"], reason=pending["reason"],
            request_id=pending["request_id"],
        )
        head = (
            texts.GROUP_SAVED_PAYMENT_SETTLED
            if pending["request_id"]
            else texts.GROUP_SAVED_PAYMENT
        )
    await store.flush()  # رویداد مالیِ گروه را فوری روی شیت بنویس
    report = group_service.build_group_report(store, chat_id)
    await _grp_edit(query, f"{head}\n\n{report}")


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
    application.add_handler(CommandHandler("list", list_cmd))
    application.add_handler(CommandHandler("products", products_cmd))
    application.add_handler(CommandHandler("balance", balance_cmd))
    application.add_handler(CommandHandler("pilot", pilot_cmd))
    application.add_handler(CommandHandler("industry", industry_cmd))
    application.add_handler(CallbackQueryHandler(on_report_period, pattern=r"^report:"))
    application.add_handler(CallbackQueryHandler(on_dashboard, pattern=r"^dash:"))
    application.add_handler(CallbackQueryHandler(on_ledger_action, pattern=r"^ledger:"))
    application.add_handler(CallbackQueryHandler(on_subscription, pattern=r"^sub:"))
    application.add_handler(CallbackQueryHandler(on_payment_review, pattern=r"^pay:"))
    application.add_handler(CallbackQueryHandler(on_zarinpal_verify, pattern=r"^zpv:"))
    application.add_handler(CallbackQueryHandler(on_undo, pattern=r"^tx:undo:"))
    application.add_handler(
        CallbackQueryHandler(on_tx_action, pattern=r"^tx:(eamt|ecat|setcat|del):")
    )
    application.add_handler(CallbackQueryHandler(on_moadian, pattern=r"^moadian:"))
    application.add_handler(CallbackQueryHandler(on_invoice_action, pattern=r"^inv:"))
    application.add_handler(CallbackQueryHandler(on_product_action, pattern=r"^prod:"))
    application.add_handler(CallbackQueryHandler(on_group_confirm, pattern=r"^grp:"))
    application.add_handler(CallbackQueryHandler(on_industry, pattern=r"^ind:"))
    # پیام‌های خصوصی (۱:۱) — جریان‌های شخصیِ کاربر
    private = filters.ChatType.PRIVATE
    application.add_handler(MessageHandler(filters.PHOTO & private, on_photo))
    application.add_handler(MessageHandler(filters.Document.ALL & private, on_document))
    application.add_handler(
        MessageHandler((filters.VOICE | filters.AUDIO) & private, on_voice)
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & private, on_text)
    )
    # پیام‌های گروه — دفتر مالی گروهی (نیازمند خاموش‌بودن Privacy Mode)
    application.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_group_added)
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
            on_group_message,
        )
    )
