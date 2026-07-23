"""کیبوردهای بات (منوی اصلی و دکمه‌های شیشه‌ای)."""
from __future__ import annotations

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

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


def report_periods() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("امروز", callback_data="report:day"),
                InlineKeyboardButton("این هفته", callback_data="report:week"),
                InlineKeyboardButton("این ماه", callback_data="report:month"),
            ]
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
