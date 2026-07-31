"""کیبوردهای بات (منوی اصلی و دکمه‌های شیشه‌ای)."""
from __future__ import annotations

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from ..core import categories, industries
from ..core.money import format_amount
from ..plans import PLANS, TIER_ORDER, TIERS, plans_for_tier
from . import texts


def main_menu() -> ReplyKeyboardMarkup:
    """منوی اصلی همیشگی زیر کادر تایپ."""
    keyboard = [
        [KeyboardButton(texts.BTN_REPORT), KeyboardButton(texts.BTN_LEDGER)],
        [KeyboardButton(texts.BTN_INVOICE), KeyboardButton(texts.BTN_SUBSCRIPTION)],
        [KeyboardButton(texts.BTN_HELP)],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def subscription_plans() -> InlineKeyboardMarkup:
    """دکمه‌های خرید پلن‌ها — هر سطح در یک ردیف (ماهانه و یک‌ساله کنار هم)."""
    rows: list = []
    for tier in TIER_ORDER:
        row = []
        for key in plans_for_tier(tier):
            plan = PLANS[key]
            period = "ماهانه" if plan["days"] <= 31 else "سالانه"
            label = f"{TIERS[tier]['label']} {period} — {format_amount(plan['price'], with_currency=False)}"
            row.append(InlineKeyboardButton(label, callback_data=f"sub:buy:{key}"))
        if row:
            rows.append(row)
    return InlineKeyboardMarkup(rows)


def payment_review(payment_id: int) -> InlineKeyboardMarkup:
    """دکمه‌های تأیید/رد پرداخت برای مدیر."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ تأیید", callback_data=f"pay:approve:{payment_id}"),
                InlineKeyboardButton("❌ رد", callback_data=f"pay:reject:{payment_id}"),
            ]
        ]
    )


def undo_transaction(transaction_id: int) -> InlineKeyboardMarkup:
    """دکمه‌ی لغو همین ثبت، زیر پیام تأیید تراکنش."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(texts.BTN_UNDO_TX, callback_data=f"tx:undo:{transaction_id}")]]
    )


def zarinpal_pay(pay_url: str, payment_id: int) -> InlineKeyboardMarkup:
    """دکمه‌ی پرداخت آنلاین و بررسی پرداخت."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(texts.BTN_PAY_NOW, url=pay_url)],
            [InlineKeyboardButton(texts.BTN_PAY_VERIFY, callback_data=f"zpv:{payment_id}")],
        ]
    )


def moadian_send(invoice_id: int) -> InlineKeyboardMarkup:
    """دکمه‌ی ارسال فاکتور به سامانه‌ی مودیان."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(texts.BTN_MOADIAN_SEND, callback_data=f"moadian:{invoice_id}")]]
    )


def transaction_actions(transaction_id: int) -> InlineKeyboardMarkup:
    """دکمه‌های اصلاح/حذف یک تراکنش در فهرست."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✏️ مبلغ", callback_data=f"tx:eamt:{transaction_id}"),
                InlineKeyboardButton("🏷 دسته", callback_data=f"tx:ecat:{transaction_id}"),
                InlineKeyboardButton("🗑 حذف", callback_data=f"tx:del:{transaction_id}"),
            ]
        ]
    )


def invoice_builder(products, has_items: bool) -> InlineKeyboardMarkup:
    """کیبورد ساختِ فاکتور: کالاهای ذخیره‌شده + کنترل‌ها."""
    rows: list = []
    for p in list(products)[:8]:
        label = f"{p.title} — {format_amount(p.unit_price, with_currency=False)}"
        rows.append([InlineKeyboardButton(f"➕ {label}", callback_data=f"inv:add:{p.id}")])
    rows.append([InlineKeyboardButton("✅ صدور فاکتور", callback_data="inv:done")])
    controls = [InlineKeyboardButton("🏷 تخفیف/ارسال", callback_data="inv:extra")]
    if has_items:
        controls.append(InlineKeyboardButton("↩️ حذف آخرین", callback_data="inv:pop"))
    rows.append(controls)
    return InlineKeyboardMarkup(rows)


def product_list(products) -> InlineKeyboardMarkup:
    """فهرست کالاها؛ هر کالا یک دکمه‌ی حذف، به‌علاوه‌ی افزودن."""
    rows: list = []
    for p in list(products)[:30]:
        label = f"🗑 {p.title} — {format_amount(p.unit_price, with_currency=False)}"
        rows.append([InlineKeyboardButton(label, callback_data=f"prod:del:{p.id}")])
    rows.append([InlineKeyboardButton("➕ افزودن کالا", callback_data="prod:add")])
    return InlineKeyboardMarkup(rows)


def category_picker(transaction_id: int, kind: str) -> InlineKeyboardMarkup:
    """انتخابگر دسته برای ویرایش (دو ستون)."""
    options = categories.category_options(kind)
    rows: list = []
    row: list = []
    for index, label in enumerate(options):
        row.append(
            InlineKeyboardButton(label, callback_data=f"tx:setcat:{transaction_id}:{index}")
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def ledger_settle_list(entries) -> InlineKeyboardMarkup | None:
    """دکمه‌ی «تسویه شد» برای هر ردیفِ بازِ دفتر (حداکثر ۱۰ ردیف).

    اگر ردیفی نباشد ``None`` برمی‌گرداند تا کیبوردِ خالی نفرستیم.
    """
    rows: list = []
    for e in list(entries)[:10]:
        tag = "🧾 " if getattr(e, "is_cheque", False) else ""
        label = (
            f"✅ تسویه: {tag}{e.party_name} — "
            f"{format_amount(e.amount, with_currency=False)}"
        )
        rows.append([InlineKeyboardButton(label, callback_data=f"ledger:settle:{e.id}")])
    return InlineKeyboardMarkup(rows) if rows else None


def invoice_history(invoices) -> InlineKeyboardMarkup | None:
    """فهرست فاکتورهای اخیر؛ لمسِ هر کدام = ارسال دوباره‌ی عکس و PDF."""
    rows: list = []
    for inv in list(invoices)[:10]:
        label = (
            f"🧾 {inv.number} — {inv.customer_name} — "
            f"{format_amount(inv.total, with_currency=False)}"
        )
        rows.append([InlineKeyboardButton(label, callback_data=f"invh:{inv.id}")])
    return InlineKeyboardMarkup(rows) if rows else None


def industry_picker() -> InlineKeyboardMarkup:
    """انتخابگر صنفِ کسب‌وکار (یک دکمه در هر ردیف تا متن‌ها جا شوند)."""
    rows = [
        [InlineKeyboardButton(ind.label, callback_data=f"ind:{ind.key}")]
        for ind in industries.all_industries()
    ]
    return InlineKeyboardMarkup(rows)


def report_periods() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("امروز", callback_data="report:day"),
                InlineKeyboardButton("این هفته", callback_data="report:week"),
                InlineKeyboardButton("این ماه", callback_data="report:month"),
            ],
            [InlineKeyboardButton(texts.BTN_DASHBOARD, callback_data="dash:show")],
        ]
    )


def ledger_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(texts.BTN_ADD_RECEIVABLE, callback_data="ledger:add:receivable"),
                InlineKeyboardButton(texts.BTN_ADD_PAYABLE, callback_data="ledger:add:payable"),
            ],
            [InlineKeyboardButton(texts.BTN_LEDGER_LIST, callback_data="ledger:list")],
            [InlineKeyboardButton(texts.BTN_PARTY_STATEMENT, callback_data="ledger:statement")],
        ]
    )
