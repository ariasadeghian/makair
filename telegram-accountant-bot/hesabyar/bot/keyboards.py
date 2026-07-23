"""کیبوردهای بات (منوی اصلی و دکمه‌های شیشه‌ای)."""
from __future__ import annotations

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from ..core import categories
from ..core.money import format_amount
from ..plans import PLAN_ORDER, PLANS
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
    """دکمه‌های خرید پلن‌های اشتراک."""
    rows = []
    for key in PLAN_ORDER:
        plan = PLANS[key]
        label = f"{plan['label']} — {format_amount(plan['price'])}"
        rows.append([InlineKeyboardButton(label, callback_data=f"sub:buy:{key}")])
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
        ]
    )
