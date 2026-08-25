"""کار با تاریخ و زمان شمسی.

از کتابخانه‌ی :mod:`jdatetime` استفاده می‌کند. منطقه‌ی زمانی ایران از سال
۱۴۰۱ ساعت تابستانی ندارد، پس افست ثابت ``+03:30`` امن و قطعی است.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Optional

import jdatetime

from .money import to_english_digits, to_persian_digits

TEHRAN = dt.timezone(dt.timedelta(hours=3, minutes=30), "Iran")

_MONTH_NAMES = [
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
]

# نام روزهای هفته به ترتیب شنبه..جمعه (jdatetime: شنبه=۰)
_WEEKDAY_NAMES = [
    "شنبه",
    "یک‌شنبه",
    "دوشنبه",
    "سه‌شنبه",
    "چهارشنبه",
    "پنج‌شنبه",
    "جمعه",
]

_RELATIVE_DAYS = {
    "امروز": 0,
    "همین امروز": 0,
    "دیروز": -1,
    "پریروز": -2,
    "پس‌پریروز": -3,
    "پس پریروز": -3,
    "فردا": 1,
    "پس‌فردا": 2,
    "پس فردا": 2,
}

_EXPLICIT_DATE = re.compile(r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})")


def now() -> dt.datetime:
    """زمان کنونی با منطقه‌ی زمانی ایران."""
    return dt.datetime.now(TEHRAN)


def to_jalali(value: dt.datetime | dt.date) -> jdatetime.date:
    if isinstance(value, dt.datetime):
        return jdatetime.datetime.fromgregorian(datetime=value).date()
    return jdatetime.date.fromgregorian(date=value)


def month_name(month: int) -> str:
    return _MONTH_NAMES[(month - 1) % 12]


def weekday_name(value: dt.datetime | dt.date) -> str:
    j = to_jalali(value)
    return _WEEKDAY_NAMES[j.weekday()]


def format_date(value: dt.datetime | dt.date) -> str:
    """قالب «۱۴۰۳/۰۵/۰۱»."""
    j = to_jalali(value)
    return to_persian_digits(f"{j.year:04d}/{j.month:02d}/{j.day:02d}")


def format_date_long(value: dt.datetime | dt.date) -> str:
    """قالب «۱ مرداد ۱۴۰۳»."""
    j = to_jalali(value)
    return to_persian_digits(f"{j.day} {month_name(j.month)} {j.year}")


def format_datetime(value: dt.datetime) -> str:
    """قالب «۱۴۰۳/۰۵/۰۱ - ۱۴:۳۰»."""
    if value.tzinfo is not None:
        value = value.astimezone(TEHRAN)
    date_part = format_date(value)
    time_part = to_persian_digits(f"{value.hour:02d}:{value.minute:02d}")
    return f"{date_part} - {time_part}"


def parse_relative_date(text: str, base: Optional[dt.datetime] = None) -> Optional[dt.date]:
    """استخراج تاریخ از متن.

    ابتدا واژه‌های نسبی (امروز، دیروز، …) و سپس تاریخ صریح شمسی
    (مثل ``۱۴۰۳/۵/۱``) را می‌آزماید. اگر چیزی پیدا نشد ``None``.
    خروجی یک :class:`datetime.date` میلادی است.
    """
    base = base or now()
    base_date = base.date() if isinstance(base, dt.datetime) else base

    lowered = text.replace("‌", " ")
    for word, delta in _RELATIVE_DAYS.items():
        if word in lowered:
            return base_date + dt.timedelta(days=delta)

    match = _EXPLICIT_DATE.search(to_english_digits(text))
    if match:
        year, month, day = (int(g) for g in match.groups())
        try:
            return jdatetime.date(year, month, day).togregorian()
        except Exception:
            return None
    return None


# --- بازه‌های گزارش -----------------------------------------------------------


def _start_of_day(value: dt.datetime) -> dt.datetime:
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def day_bounds(base: Optional[dt.datetime] = None) -> tuple[dt.datetime, dt.datetime]:
    """بازه‌ی «امروز»."""
    base = base or now()
    start = _start_of_day(base)
    return start, base


def week_bounds(base: Optional[dt.datetime] = None) -> tuple[dt.datetime, dt.datetime]:
    """بازه‌ی هفته‌ی جاری شمسی (از شنبه)."""
    base = base or now()
    j = to_jalali(base)
    start = _start_of_day(base) - dt.timedelta(days=j.weekday())
    return start, base


def month_bounds(base: Optional[dt.datetime] = None) -> tuple[dt.datetime, dt.datetime]:
    """بازه‌ی ماه جاری شمسی (از روز اول ماه)."""
    base = base or now()
    j = to_jalali(base)
    first = jdatetime.date(j.year, j.month, 1).togregorian()
    start = dt.datetime(
        first.year, first.month, first.day, tzinfo=base.tzinfo
    )
    return start, base
