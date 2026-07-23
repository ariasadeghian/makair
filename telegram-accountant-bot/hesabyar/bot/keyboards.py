"""کیبوردهای بات (منوی اصلی و دکمه‌های شیشه‌ای)."""
from __future__ import annotations

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from . import texts


def main_menu() -> ReplyKeyboardMarkup:
    """منوی اصلی همیشگی زیر کادر تایپ."""
    keyboard = [
        [KeyboardButton(texts.BTN_REPORT), KeyboardButton(texts.BTN_LEDGER)],
        [KeyboardButton(texts.BTN_INVOICE), KeyboardButton(texts.BTN_HELP)],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


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
