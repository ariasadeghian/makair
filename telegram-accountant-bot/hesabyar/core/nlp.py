"""پردازش زبان طبیعی سبک برای تبدیل نوشته‌ی کاربر به یک تراکنش.

این ماژول یک جمله‌ی فارسی مثل «دیروز ۵۰۰ هزار بابت خرید مواد اولیه دادم» را
می‌گیرد و آن را به یک :class:`ParsedTransaction` تبدیل می‌کند: نوع (درآمد/هزینه)،
مبلغ (تومان)، دسته، شرح پاک‌شده و زمان رخداد (aware، منطقه‌ی تهران).

برای پردازش عدد از :mod:`hesabyar.core.money`، برای تاریخ از
:mod:`hesabyar.core.jalali` و برای دسته‌بندی از
:mod:`hesabyar.core.categories` استفاده می‌شود؛ این ماژول‌ها پایه‌اند و اینجا
فقط استفاده می‌شوند.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Optional

from . import categories, jalali, money
from ..db.models import Kind

# --- کلیدواژه‌های تشخیص نوع تراکنش --------------------------------------------

#: واژه‌هایی که به «هزینه» اشاره دارند.
EXPENSE_KEYWORDS: tuple[str, ...] = (
    "خرید",
    "خریدم",
    "دادم",
    "پرداخت",
    "پرداختم",
    "خرج",
    "هزینه",
    "حساب کردم",
    "رد کردم",
)

#: واژه‌هایی که به «درآمد» اشاره دارند.
INCOME_KEYWORDS: tuple[str, ...] = (
    "فروش",
    "فروختم",
    "فروختیم",
    "گرفتم",
    "دریافت",
    "درآمد",
    "واریز",
    "وصول",
)

# --- ابزارهای پاک‌سازی شرح ----------------------------------------------------

#: الگوی تاریخ صریح شمسی مثل «۱۴۰۳/۵/۱» (پس از تبدیل ارقام به انگلیسی).
_EXPLICIT_DATE_RE = re.compile(r"\d{4}[/\-.]\d{1,2}[/\-.]\d{1,2}")

#: الگوی یک عدد خام (با یا بدون اعشار).
_BARE_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

#: واژه‌های تاریخ نسبی که باید از شرح حذف شوند (بلندترها اول).
_DATE_WORDS: tuple[str, ...] = (
    "همین امروز",
    "پس‌پریروز",
    "پس پریروز",
    "پس‌فردا",
    "پس فردا",
    "امروز",
    "دیروز",
    "پریروز",
    "فردا",
)

# واژه‌های عددی/مقیاس/واحد پول را از ماژول money می‌گیریم تا هماهنگ بماند.
_SCALE_WORDS: frozenset[str] = frozenset(getattr(money, "_SCALES", {}))
_NUMBER_WORDS: frozenset[str] = frozenset(getattr(money, "_UNITS", {}))
_CURRENCY_WORDS: frozenset[str] = frozenset(getattr(money, "_CURRENCY_WORDS", set()))


@dataclass
class ParsedTransaction:
    """نتیجه‌ی پردازش یک جمله‌ی تراکنش.

    :ivar kind: نوع تراکنش، یکی از ``Kind.INCOME`` یا ``Kind.EXPENSE``.
    :ivar amount: مبلغ به تومان (عدد صحیح مثبت).
    :ivar category: دسته‌ی تشخیص‌داده‌شده.
    :ivar description: شرح پاک‌شده (بدون مبلغ/واحد پول/واژه‌ی تاریخ).
    :ivar occurred_at: زمان رخداد؛ همیشه aware و در منطقه‌ی تهران.
    :ivar raw: متن خام ورودی کاربر.
    """

    kind: str
    amount: int
    category: str
    description: str
    occurred_at: dt.datetime
    raw: str


def _detect_kind(text: str) -> str:
    """تشخیص نوع تراکنش بر اساس کلیدواژه‌ها.

    اگر هم واژه‌ی درآمد و هم هزینه در متن باشد، واژه‌ای که «دیرتر» آمده برنده
    است (فعل اصلی جمله معمولاً پایان جمله است). اگر هیچ کلیدواژه‌ای نباشد،
    پیش‌فرض «هزینه» برمی‌گردد.
    """
    haystack = (text or "").replace("‌", " ")
    income_pos = max(
        (haystack.find(kw) for kw in INCOME_KEYWORDS if kw in haystack),
        default=-1,
    )
    expense_pos = max(
        (haystack.find(kw) for kw in EXPENSE_KEYWORDS if kw in haystack),
        default=-1,
    )
    if income_pos > expense_pos:
        return Kind.INCOME
    return Kind.EXPENSE


def _is_amount_token(token: str) -> bool:
    """آیا این توکن بخشی از مبلغ/واحد پول است و باید از شرح حذف شود؟"""
    cleaned = money.to_english_digits(token).strip("٬،,.٫ ")
    if not cleaned:  # فقط علامت نگارشی
        return True
    if cleaned in _CURRENCY_WORDS:
        return True
    if cleaned in _SCALE_WORDS:
        return True
    if cleaned in _NUMBER_WORDS:
        return True
    if _BARE_NUMBER_RE.fullmatch(cleaned):
        return True
    return False


def _clean_description(text: str) -> str:
    """ساخت شرح خوانا با حذف بخش تاریخ، مبلغ و واحد پول (best-effort)."""
    if not text:
        return ""
    s = text.replace("‌", " ")
    # حذف تاریخ صریح شمسی (ارقام را انگلیسی می‌کنیم تا الگو بگیرد)
    s = _EXPLICIT_DATE_RE.sub(" ", money.to_english_digits(s))
    # حذف واژه‌های تاریخ نسبی
    for word in _DATE_WORDS:
        s = s.replace(word, " ")
    # حذف توکن‌های مربوط به مبلغ/عدد/واحد پول
    tokens = [t for t in s.split() if not _is_amount_token(t)]
    return " ".join(tokens).strip()


def _resolve_occurred_at(text: str, base: Optional[dt.datetime]) -> dt.datetime:
    """تعیین زمان رخداد: تاریخِ متن + ساعتِ ``base`` (یا اکنون)، همیشه aware."""
    base_dt = base or jalali.now()
    if base_dt.tzinfo is None:  # تضمین aware بودن
        base_dt = base_dt.replace(tzinfo=jalali.TEHRAN)
    # تاریخ نسبی/صریح؛ در نبود، همان تاریخِ base
    the_date = jalali.parse_relative_date(text, base_dt) or base_dt.date()
    return dt.datetime(
        the_date.year,
        the_date.month,
        the_date.day,
        base_dt.hour,
        base_dt.minute,
        base_dt.second,
        base_dt.microsecond,
        tzinfo=base_dt.tzinfo,
    )


def parse_transaction(
    text: str, base: Optional[dt.datetime] = None
) -> Optional[ParsedTransaction]:
    """پردازش یک جمله‌ی فارسی به یک تراکنش.

    اگر هیچ مبلغی در متن پیدا نشود، ``None`` برمی‌گرداند.

    :param text: نوشته‌ی کاربر.
    :param base: زمان مبنا برای تاریخ‌های نسبی و ساعتِ رخداد؛ پیش‌فرض «اکنون».
    """
    if not text or not text.strip():
        return None

    amount = money.parse_amount(text)
    if amount is None:
        return None

    kind = _detect_kind(text)
    category = categories.detect_category(text, kind)
    description = _clean_description(text)
    occurred_at = _resolve_occurred_at(text, base)

    return ParsedTransaction(
        kind=kind,
        amount=amount,
        category=category,
        description=description,
        occurred_at=occurred_at,
        raw=text,
    )
