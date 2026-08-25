"""تطبیقِ تقریبیِ نام‌ها — «مبلمان» و «مبل» یک چیزند.

کاربر هر بار یک اسم را کمی جور دیگری می‌نویسد: «مبل»، «مبلمان»، «مبل راحتی».
بدون تطبیقِ تقریبی، هر املا یک کالای تازه در فهرست می‌سازد و گزارش‌ها تکه‌تکه
می‌شوند.

فقط :mod:`difflib` از کتابخانه‌ی استاندارد استفاده می‌شود؛ وابستگیِ تازه‌ای
اضافه نشده. روی نامِ **طرف‌حساب‌ها** عمداً به کار نمی‌رود — آنجا «رضا» و
«رضایی» را یکی کردن، دو نفرِ واقعی را در هم می‌کند و اشتباهش گران است.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Iterable, Optional

#: آستانه‌ی پیش‌فرضِ «به‌اندازه‌ی کافی شبیه».
DEFAULT_THRESHOLD = 0.72

#: کوتاه‌تر از این، شباهت معنا ندارد («با» شبیهِ همه‌چیز است).
MIN_LENGTH = 3

#: اگر یک واژه کاملاً داخلِ دیگری باشد («مبل» در «مبلمان»)، شباهتش دست‌کم
#: این‌قدر است — SequenceMatcher به‌تنهایی چنین جفتی را ۰٫۶۷ می‌دهد و رد
#: می‌شود، در حالی که برای کاربر همان چیزند.
CONTAINMENT_FLOOR = 0.75

#: یکسان‌سازی حروفِ عربی/فارسی که کاربرها به‌جای هم تایپ می‌کنند.
_LETTER_FIXES = str.maketrans({
    "ي": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "أ": "ا", "إ": "ا", "آ": "ا",
    "ؤ": "و", "ئ": "ی", "‌": " ", "‏": " ", "‎": " ",
})

#: اعرابِ عربی که در تایپ گاهی جا می‌مانند.
_DIACRITICS = re.compile(r"[ً-ْٰ]")


def normalize(text: str) -> str:
    """نرمال‌سازیِ متن برای مقایسه: حروفِ یکسان، بدون اعراب و فاصله‌ی اضافه."""
    if not text:
        return ""
    out = unicodedata.normalize("NFKC", text).translate(_LETTER_FIXES)
    out = _DIACRITICS.sub("", out)
    return " ".join(out.split()).casefold()


def similarity(first: str, second: str) -> float:
    """شباهتِ دو نام، بین ۰ و ۱."""
    left, right = normalize(first), normalize(second)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    score = SequenceMatcher(None, left, right).ratio()
    short, long = sorted((left, right), key=len)
    if len(short) >= MIN_LENGTH and short in long:
        contained = len(short) / len(long)
        score = max(score, CONTAINMENT_FLOOR + (1 - CONTAINMENT_FLOOR) * contained)
    return score


def best_match(
    query: str,
    candidates: Iterable[str],
    threshold: float = DEFAULT_THRESHOLD,
) -> Optional[str]:
    """نزدیک‌ترین گزینه به ``query``، یا ``None`` اگر هیچ‌کدام کافی نبود.

    خروجی همیشه یکی از خودِ ``candidates`` است (نه شکلِ نرمال‌شده‌اش)، تا
    مقدارِ ذخیره‌شده دست‌نخورده بماند. مساوی که شد، کوتاه‌ترین برنده است —
    اسمِ پایه بر شکل‌های طولانی‌ترش ترجیح دارد.
    """
    target = normalize(query)
    if not target:
        return None
    if len(target) < MIN_LENGTH:  # واژه‌ی دوحرفی شبیهِ همه‌چیز است
        return next((c for c in candidates if normalize(c) == target), None)
    best, best_score = None, 0.0
    for candidate in candidates:
        if not candidate:
            continue
        score = similarity(target, candidate)
        if score > best_score or (score == best_score and best is not None
                                  and len(candidate) < len(best)):
            best, best_score = candidate, score
    return best if best_score >= threshold else None


def canonical(
    query: str,
    known: Iterable[str],
    threshold: float = DEFAULT_THRESHOLD,
) -> str:
    """نامِ موجودِ نزدیک را برمی‌گرداند، وگرنه خودِ ``query`` را.

    نقطه‌ی استفاده‌ی معمول: به‌جای ساختنِ «مبلمان» تازه، همان «مبلِ» موجود.
    """
    match = best_match(query, known, threshold)
    return match if match is not None else query
