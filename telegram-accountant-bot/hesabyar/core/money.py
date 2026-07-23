"""پردازش مبالغ پولی فارسی.

این ماژول مسئول تبدیل نوشته‌ی کاربر به عدد (تومان) و برعکس است. نمونه‌ها::

    parse_amount("۵۰۰ هزار تومان")      -> 500000
    parse_amount("۲.۵ میلیون")           -> 2500000
    parse_amount("دو میلیون و سیصد هزار") -> 2300000
    parse_amount("۱۲۳٬۰۰۰ تومان")        -> 123000
    parse_amount("۵۰۰۰ ریال")            -> 500        (ریال به تومان)
    format_amount(1200000)               -> "۱٬۲۰۰٬۰۰۰ تومان"

همه‌ی مقادیر داخلی به «تومان» و عدد صحیح‌اند.
"""
from __future__ import annotations

import re
from typing import Optional

# --- نگاشت ارقام -------------------------------------------------------------

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_ENGLISH_DIGITS = "0123456789"

_TO_ENGLISH = {ord(p): e for p, e in zip(_PERSIAN_DIGITS, _ENGLISH_DIGITS)}
_TO_ENGLISH.update({ord(a): e for a, e in zip(_ARABIC_DIGITS, _ENGLISH_DIGITS)})
_TO_PERSIAN = {ord(e): p for e, p in zip(_ENGLISH_DIGITS, _PERSIAN_DIGITS)}

# --- واژه‌های عددی ------------------------------------------------------------

_UNITS = {
    "صفر": 0,
    "یک": 1,
    "دو": 2,
    "سه": 3,
    "چهار": 4,
    "پنج": 5,
    "پنچ": 5,
    "شش": 6,
    "شیش": 6,
    "هفت": 7,
    "هشت": 8,
    "نه": 9,
    "ده": 10,
    "یازده": 11,
    "دوازده": 12,
    "سیزده": 13,
    "چهارده": 14,
    "پانزده": 15,
    "پونزده": 15,
    "شانزده": 16,
    "شونزده": 16,
    "هفده": 17,
    "هیفده": 17,
    "هجده": 18,
    "هیجده": 18,
    "نوزده": 19,
    "بیست": 20,
    "سی": 30,
    "چهل": 40,
    "پنجاه": 50,
    "شصت": 60,
    "هفتاد": 70,
    "هشتاد": 80,
    "نود": 90,
    "صد": 100,
    "یکصد": 100,
    "دویست": 200,
    "سیصد": 300,
    "چهارصد": 400,
    "پانصد": 500,
    "پونصد": 500,
    "ششصد": 600,
    "شیشصد": 600,
    "هفتصد": 700,
    "هفصد": 700,
    "هشتصد": 800,
    "نهصد": 900,
}

_SCALES = {
    "هزار": 1_000,
    "میلیون": 1_000_000,
    "ملیون": 1_000_000,
    "میلیارد": 1_000_000_000,
    "ملیارد": 1_000_000_000,
    "بیلیون": 1_000_000_000,
}

_CURRENCY_TOMAN = {"تومان", "تومن", "ت", "تومانه"}
_CURRENCY_RIAL = {"ریال", "ريال"}
_CURRENCY_WORDS = _CURRENCY_TOMAN | _CURRENCY_RIAL

# جداکننده‌های هزارگان و اعشار
_THOUSANDS_SEP = re.compile(r"(?<=\d)[,٬،](?=\d)")
_DECIMAL_SEP = "٫"


def to_english_digits(text: str) -> str:
    """تبدیل ارقام فارسی/عربی به انگلیسی."""
    return text.translate(_TO_ENGLISH)


def to_persian_digits(text: str) -> str:
    """تبدیل ارقام انگلیسی به فارسی."""
    return text.translate(_TO_PERSIAN)


def normalize(text: str) -> str:
    """یکسان‌سازی متن برای پردازش عددی."""
    text = to_english_digits(text)
    text = text.replace(_DECIMAL_SEP, ".")
    text = _THOUSANDS_SEP.sub("", text)  # حذف جداکننده‌ی هزارگان داخل عدد
    text = text.replace("‌", " ")  # نیم‌فاصله → فاصله
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def format_amount(
    toman: int, with_currency: bool = True, currency: str = "تومان"
) -> str:
    """قالب‌بندی مبلغ به رشته‌ی فارسی با جداکننده‌ی هزارگان."""
    n = int(round(toman))
    sign = "-" if n < 0 else ""
    grouped = f"{abs(n):,}".replace(",", "٬")
    persian = to_persian_digits(grouped)
    result = f"{sign}{persian}"
    if with_currency:
        result = f"{result} {currency}"
    return result


# --- تحلیل عبارت عددی ---------------------------------------------------------


def _token_value(token: str):
    """ارزش یک توکن را برمی‌گرداند.

    خروجی یکی از این‌هاست: ``("num", value)`` برای عدد، ``("scale", value)``
    برای مقیاس (هزار/میلیون/…)، ``("and",)`` برای «و»، یا ``None``.
    """
    if token == "و":
        return ("and",)
    if token in _SCALES:
        return ("scale", _SCALES[token])
    if token in _UNITS:
        return ("num", float(_UNITS[token]))
    # عدد خام (با یا بدون اعشار)
    if re.fullmatch(r"\d+(?:\.\d+)?", token):
        return ("num", float(token))
    return None


def _eval_run(values: list) -> Optional[float]:
    """ارزیابی یک دنباله‌ی عددی با در نظر گرفتن مقیاس‌ها."""
    total = 0.0
    current = 0.0
    seen = False
    for value in values:
        if value[0] == "and":
            continue
        if value[0] == "num":
            current += value[1]
            seen = True
        elif value[0] == "scale":
            if current == 0:
                current = 1.0
            current *= value[1]
            total += current
            current = 0.0
            seen = True
    total += current
    return total if seen else None


def _iter_number_runs(tokens: list[str]):
    """یافتن دنباله‌های پیوسته‌ی عددی در فهرست توکن‌ها.

    هر خروجی یک سه‌تایی ``(start_index, end_index, values)`` است.
    """
    runs = []
    current: list = []
    start: Optional[int] = None
    for idx, token in enumerate(tokens):
        tv = _token_value(token)
        if tv is None:
            if current:
                runs.append((start, idx - 1, current))
                current, start = [], None
            continue
        if tv[0] == "and":
            if current:  # «و» فقط داخل یک دنباله معنا دارد
                current.append(tv)
            continue
        if start is None:
            start = idx
        current.append(tv)
    if current:
        runs.append((start, len(tokens) - 1, current))
    return runs


def _run_currency(tokens: list[str], start: int, end: int, full_text: str) -> str:
    """تشخیص واحد پولی یک دنباله بر اساس توکن مجاور.

    خروجی ``"rial"`` یا ``"toman"``.
    """
    after = tokens[end + 1] if end + 1 < len(tokens) else ""
    before = tokens[start - 1] if start - 1 >= 0 else ""
    if after in _CURRENCY_RIAL or before in _CURRENCY_RIAL:
        return "rial"
    if after in _CURRENCY_TOMAN or before in _CURRENCY_TOMAN:
        return "toman"
    # اگر واژه‌ی مجاور نبود، به کل متن نگاه کن
    if any(w in tokens for w in _CURRENCY_RIAL) and not any(
        w in tokens for w in _CURRENCY_TOMAN
    ):
        return "rial"
    return "toman"


def parse_amount(text: str) -> Optional[int]:
    """استخراج مبلغ (به تومان) از یک نوشته‌ی فارسی.

    اگر عددی پیدا نشود ``None`` برمی‌گرداند. وقتی چند عدد در متن باشد،
    عددی که کنارش واژه‌ی واحد پول است (یا بزرگ‌ترین عدد) انتخاب می‌شود.
    """
    if not text:
        return None
    norm = normalize(text)
    tokens = norm.split()
    runs = _iter_number_runs(tokens)
    if not runs:
        return None

    candidates = []
    for start, end, values in runs:
        val = _eval_run(values)
        if val is None:
            continue
        currency = _run_currency(tokens, start, end, norm)
        after = tokens[end + 1] if end + 1 < len(tokens) else ""
        before = tokens[start - 1] if start - 1 >= 0 else ""
        adjacent = after in _CURRENCY_WORDS or before in _CURRENCY_WORDS
        candidates.append((adjacent, val, currency))

    if not candidates:
        return None

    # اولویت با عددی که کنارش واحد پول است؛ در غیر این صورت بزرگ‌ترین عدد
    with_currency = [c for c in candidates if c[0]]
    pool = with_currency if with_currency else candidates
    _, value, currency = max(pool, key=lambda c: c[1])

    toman = value / 10 if currency == "rial" else value
    return int(round(toman))


def parse_int(text: str) -> Optional[int]:
    """پارس یک عدد صحیح ساده (برای تعداد کالا و مانند آن)."""
    if not text:
        return None
    norm = normalize(text)
    tokens = norm.split()
    runs = _iter_number_runs(tokens)
    if not runs:
        return None
    val = _eval_run(runs[0][2])
    if val is None:
        return None
    return int(round(val))
