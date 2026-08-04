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
    """منوی اصلی همیشگی زیر کادر تایپ: ۶ بخش، دو‌تا در هر ردیف."""
    keyboard = [
        [KeyboardButton(texts.BTN_REPORT), KeyboardButton(texts.BTN_TRANSACTIONS)],
        [KeyboardButton(texts.BTN_LEDGER), KeyboardButton(texts.BTN_INVOICE)],
        [KeyboardButton(texts.BTN_BUSINESS), KeyboardButton(texts.BTN_ACCOUNT)],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def _back_row() -> list:
    """ردیف آخرِ هر زیرمنو: بازگشت به منوی اصلی."""
    return [InlineKeyboardButton(texts.BTN_BACK_MAIN, callback_data="menu:main")]


#: تنها ``callback_data``ی خروج از جریان‌های چندمرحله‌ای.
CANCEL_DATA = "flow:cancel"


def _cancel_row() -> list:
    return [InlineKeyboardButton(texts.BTN_FLOW_CANCEL, callback_data=CANCEL_DATA)]


def with_cancel(markup: InlineKeyboardMarkup | None = None) -> InlineKeyboardMarkup:
    """یک ردیفِ «❌ لغو عملیات» به انتهای کیبورد اضافه می‌کند.

    بدون آرگومان، کیبوردِ تک‌دکمه‌ایِ لغو می‌سازد — برای مرحله‌هایی که کاربر
    باید متن آزاد تایپ کند و کیبورد شیشه‌ای دیگری ندارند.
    اگر ردیفِ لغو از قبل باشد، دوباره اضافه نمی‌شود.
    """
    rows = [list(row) for row in markup.inline_keyboard] if markup is not None else []
    if rows and any(b.callback_data == CANCEL_DATA for b in rows[-1]):
        return markup
    return InlineKeyboardMarkup([*rows, _cancel_row()])


def cancel_only() -> InlineKeyboardMarkup:
    """کیبوردِ فقط-لغو، زیرِ پیام‌هایی که منتظر تایپِ کاربرند."""
    return with_cancel()


def report_menu() -> InlineKeyboardMarkup:
    """زیرمنوی گزارش و داشبورد."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("امروز", callback_data="report:day"),
            InlineKeyboardButton("این هفته", callback_data="report:week"),
            InlineKeyboardButton("این ماه", callback_data="report:month"),
        ],
        [InlineKeyboardButton(texts.BTN_DASHBOARD, callback_data="dash:show")],
        [InlineKeyboardButton(texts.BTN_M_EXPORT, callback_data="act:export")],
        _back_row(),
    ])


def transactions_menu() -> InlineKeyboardMarkup:
    """زیرمنوی تراکنش‌ها."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(texts.BTN_M_LIST, callback_data="act:list")],
        [
            InlineKeyboardButton(texts.BTN_M_SEARCH, callback_data="act:search"),
            InlineKeyboardButton(texts.BTN_M_UNDO, callback_data="act:undo"),
        ],
        _back_row(),
    ])


def invoice_menu() -> InlineKeyboardMarkup:
    """زیرمنوی فاکتور و کالاها."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(texts.BTN_M_NEW_INVOICE, callback_data="act:newinvoice")],
        [
            InlineKeyboardButton(texts.BTN_M_PRODUCTS, callback_data="act:products"),
            InlineKeyboardButton(texts.BTN_M_INVOICES, callback_data="act:invoices"),
        ],
        _back_row(),
    ])


def business_menu() -> InlineKeyboardMarkup:
    """زیرمنوی کسب‌وکار: صنف، شعبه‌ها و نرخ دلار."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(texts.BTN_M_INDUSTRY, callback_data="act:industry")],
        [
            InlineKeyboardButton(texts.BTN_M_BRANCHES, callback_data="act:branches"),
            InlineKeyboardButton(texts.BTN_M_JOIN, callback_data="act:join"),
        ],
        [
            InlineKeyboardButton(texts.BTN_M_DOLLAR, callback_data="act:dollar"),
            InlineKeyboardButton(texts.BTN_M_RATE, callback_data="act:rate"),
        ],
        [InlineKeyboardButton(texts.BTN_M_LEAVE, callback_data="act:leave")],
        _back_row(),
    ])


def account_menu() -> InlineKeyboardMarkup:
    """زیرمنوی اشتراک و پشتیبانی."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(texts.BTN_M_PLANS, callback_data="act:plans")],
        [
            InlineKeyboardButton(texts.BTN_M_BACKUP, callback_data="act:backup"),
            InlineKeyboardButton(texts.BTN_M_HELP, callback_data="act:help"),
        ],
        _back_row(),
    ])


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


def transaction_confirmed_actions(transaction_id: int) -> InlineKeyboardMarkup:
    """کارهای زیرِ پیامِ تأییدِ هر تراکنش: لغو، و ثبتِ دوباره‌ی همان چیز.

    «تکرار» برای خرج‌های همیشگی است — کرایه‌ی روزانه‌ی پیک، خریدِ هرروزه‌ی
    نان — که کاربر نباید هر بار از نو بنویسدشان.
    """
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(texts.BTN_UNDO_TX, callback_data=f"tx:undo:{transaction_id}"),
        InlineKeyboardButton(texts.BTN_REPEAT_TX, callback_data=f"tx:repeat:{transaction_id}"),
    ]])


#: نام قدیمی — همان کیبورد را می‌دهد.
undo_transaction = transaction_confirmed_actions


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
    return with_cancel(InlineKeyboardMarkup(rows))


def recent_customers_picker(customers) -> InlineKeyboardMarkup:
    """مشتریانِ اخیر به‌صورت دکمه، زیرِ سؤالِ «نامِ مشتری؟».

    کاربر یا یکی را می‌زند، یا «✍️ اسم جدید»، یا همان‌طور که همیشه بود
    اسم را تایپ می‌کند — هر سه راه باز است.
    """
    rows = [
        [InlineKeyboardButton(c.name[:40], callback_data=f"cust:pick:{c.id}")]
        for c in customers
    ]
    rows.append([InlineKeyboardButton(texts.BTN_CUSTOMER_NEW, callback_data="cust:new")])
    return with_cancel(InlineKeyboardMarkup(rows))


def invoice_nlp_confirm() -> InlineKeyboardMarkup:
    """تأییدِ فاکتوری که از روی یک جمله‌ی آزاد فهمیده شده.

    «لغو» عمداً همان ``flow:cancel`` فاز ۴ است تا حالتِ نیمه‌کاره یک‌جا و به
    یک شکل پاک شود.
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(texts.BTN_INVNLP_CONFIRM, callback_data="invnlp:confirm")],
        [InlineKeyboardButton(texts.BTN_INVNLP_EDIT, callback_data="invnlp:edit")],
        [InlineKeyboardButton(texts.BTN_INVNLP_CANCEL, callback_data=CANCEL_DATA)],
    ])


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
    return with_cancel(InlineKeyboardMarkup(rows))


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


def rating_stars(invoice_id: int) -> InlineKeyboardMarkup:
    """ستاره‌های امتیازدهی زیر فاکتورِ مشتری."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⭐" * n, callback_data=f"rate:{invoice_id}:{n}")
        for n in (1, 2, 3, 4, 5)
    ]])


def debtor_reminders(pairs) -> InlineKeyboardMarkup | None:
    """دکمه‌ی «یادآوری به مشتری» برای هر بدهکارِ قابل‌دسترس."""
    rows = [
        [InlineKeyboardButton(
            f"📩 یادآوری به {e.party_name}", callback_data=f"dremind:{e.id}"
        )]
        for e, _tg in list(pairs)[:10]
    ]
    return InlineKeyboardMarkup(rows) if rows else None


def branch_menu() -> InlineKeyboardMarkup:
    """منوی مدیریت شعبه‌ها."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ شعبه‌ی جدید", callback_data="branch:add")],
        [InlineKeyboardButton("📊 گزارش امروزِ شعبه‌ها", callback_data="branch:report")],
    ])


def industry_picker() -> InlineKeyboardMarkup:
    """انتخابگر صنفِ کسب‌وکار (یک دکمه در هر ردیف تا متن‌ها جا شوند).

    ردیفِ آخر «لغو» است تا این سؤال در شروعِ کار قابلِ رد کردن باشد.
    """
    rows = [
        [InlineKeyboardButton(ind.label, callback_data=f"ind:{ind.key}")]
        for ind in industries.all_industries()
    ]
    return with_cancel(InlineKeyboardMarkup(rows))


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
            [InlineKeyboardButton(texts.BTN_M_REMIND, callback_data="act:remind")],
            _back_row(),
        ]
    )
