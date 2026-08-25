"""تشخیصِ نیتِ طلب/بدهی از یک جمله‌ی فارسیِ آزاد.

جمله‌ای مثل «من ۲ میلیون به رضا بدهکارم» یک تراکنش نیست — یک **وعده‌ی
پرداخت** است. اگر بیفتد دستِ :mod:`hesabyar.core.nlp` (که فقط دنبالِ
مبلغ و کلیدواژه‌ی خرید/فروش می‌گردد)، چون هیچ‌کدام از کلیدواژه‌هایش را ندارد
به‌صورتِ هزینه‌ی «متفرقه» ثبت می‌شود — یعنی بدهی، به‌جای دفترِ طلب و بدهی،
گم می‌شود توی گزارشِ خرج‌وخرجِ روزمره. این ماژول باید **قبل** از رسیدن به
آن مسیر، جمله را بگیرد.

نکته‌ی زبانی‌ای که کارِ این ماژول را از یک چک‌کردنِ ساده‌ی کلیدواژه جدا
می‌کند: «بدهکار» در دو جهتِ کاملاً برعکس به کار می‌رود —

    علی به من بدهکار است   ⇐ طلبِ من از علی‌ست   (receivable)
    من به علی بدهکارم      ⇐ بدهیِ من به علی‌ست   (payable)

یعنی حرفِ اضافه («به من» در برابرِ «به علی») و شخصِ فعل («بدهکار **است**»
در برابرِ «بدهکار**م**») هستند که جهت را می‌سازند، نه خودِ کلمه‌ی «بدهکار».
پس اینجا هر الگو را با هر دو قید — trigger *و* جهتِ حرفِ اضافه/شخص — چک
می‌کند، و اگر جمله با هیچ الگویی جور درنیاید ``None`` برمی‌گرداند تا مسیرِ
عادیِ تراکنش کارِ خودش را بکند؛ حدس‌زدن از روی یک کلمه، بدترین کار است.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ..db.models import Direction
from . import money

# --- واژگان ----------------------------------------------------------------------

#: نشانه‌ی ارزانِ اینکه اصلاً ارزشِ پارسِ کامل را دارد — قبل از این ماژول،
#: چیزی حتی نگاهِ دومی نمی‌اندازد.
_TRIGGER_WORDS: tuple[str, ...] = (
    "بدهکار", "طلبکار", "طلب", "بدهی", "بدهد", "بدهم",
)

#: واژه‌هایی که مرزِ نام‌اند — نه بخشی از نامِ طرف‌حساب.
_STOP: frozenset = frozenset({
    "من", "به", "از", "با", "را", "رو", "هم", "و", "که",
    "باید", "نباید",
    "بدهکار", "بدهکارم", "بدهکاری", "بدهکاره", "بدهکاریم", "بدهکارید",
    "بدهکارین", "بدهکارند", "بدهکاراست",
    "طلب", "طلبکار", "طلبکارم", "طلبکاری", "طلبکاره", "طلبکاریم",
    "بدهی", "بدهد", "بدهم", "بده", "بدم",
    "دارم", "داری", "دارد", "داره", "داریم",
    "است", "هست", "شد", "شده", "شدم", "بود", "بودم", "میشه", "می‌شه",
})

#: عنوان‌هایی که پیش از نام می‌آیند؛ بعدشان یک واژه‌ی دیگر هم نام است
#: (هم‌قدم با ``invoice_nlp._HONORIFICS`` تا رفتار در کل بات یکی بماند).
_HONORIFICS: frozenset = frozenset({
    "آقای", "اقای", "آقا", "خانم", "خانوم", "جناب", "سرکار", "دکتر", "مهندس",
    "حاج", "حاجی", "استاد",
})

_PUNCT = " .,،؛:!؟?()[]«»\"'"


@dataclass
class ParsedLedgerIntent:
    """نتیجه‌ی پارسِ یک جمله‌ی طلب/بدهی — هنوز ثبت نشده."""

    direction: str  # Direction.RECEIVABLE / Direction.PAYABLE
    party_name: str
    amount: int
    raw_text: str = ""


# --- ابزارهای توکنی ----------------------------------------------------------------


def _normalize(text: str) -> str:
    out = money.to_english_digits(text or "").replace("‌", " ")
    return re.sub(r"\s+", " ", out).strip()


def _clean(word: str) -> str:
    return word.strip(_PUNCT)


def _is_numberish(word: str) -> bool:
    """آیا این توکن بخشی از مبلغ است (رقم، عددِ نوشتاری، مقیاس، واحد پول)؟"""
    w = _clean(word)
    if not w:
        return True
    if re.fullmatch(r"\d+(?:\.\d+)?", w):
        return True
    return w in money._UNITS or w in money._SCALES or w in money._CURRENCY_WORDS


def _take_name(words: list[str], start: int) -> str:
    """نامِ طرف‌حساب را از ``words[start:]`` می‌گیرد — تا اولین مرز.

    مرز یعنی: عدد/واحدِ پول، یکی از کلمه‌های ``_STOP``، یا نبودِ کلمه.
    """
    collected: list[str] = []
    idx = start
    while idx < len(words) and len(collected) < 3:
        w = _clean(words[idx])
        if not w or _is_numberish(w) or w in _STOP:
            break
        collected.append(w)
        idx += 1
    if not collected:
        return ""
    keep = 2 if collected[0] in _HONORIFICS and len(collected) > 1 else 1
    return " ".join(collected[:keep])


def _word_positions(words: list[str], target: str) -> list[int]:
    return [i for i, w in enumerate(words) if _clean(w) == target]


def _has_word(words: list[str], target: str) -> bool:
    return any(_clean(w) == target for w in words)


def _has_phrase(words: list[str], w1: str, w2: str) -> bool:
    """آیا ``w1`` بلافاصله و به‌ترتیب پیش از ``w2`` آمده؟ («به من»، «از من»)."""
    for i in _word_positions(words, w1):
        if i + 1 < len(words) and _clean(words[i + 1]) == w2:
            return True
    return False


# --- تشخیصِ الگو ---------------------------------------------------------------------


def looks_like_ledger(text: str) -> bool:
    """دروازه‌ی ارزان: آیا اصلاً ارزشِ پارسِ کامل را دارد؟

    قبل از پارسِ کامل تا جمله‌های عادیِ تراکنش («پرداخت کردم»، «فروختم»)
    دست‌نخورده به مسیرِ خودشان بروند.
    """
    if not text:
        return False
    haystack = _normalize(text)
    return any(re.search(rf"\b{re.escape(w)}", haystack) for w in _TRIGGER_WORDS)


def _find_payable(words: list[str]) -> Optional[str]:
    """بدهیِ من به کسی — «به NAME ... بدهکارم» / «... بدهی دارم» / «باید ... بدهم».

    شرطِ لازم: «به NAME» (نه «به من») به‌همراهِ فعلِ اول‌شخص.
    """
    trigger = (
        _has_word(words, "بدهکارم") or _has_word(words, "بدهکاریم")
        or (_has_word(words, "بدهکار")
            and any(_clean(w) in ("شدم", "شدیم", "هستم") for w in words))
        or (_has_word(words, "بدهی") and any(_clean(w) in ("دارم", "داریم") for w in words))
        or (_has_word(words, "بدهم") and _has_word(words, "باید"))
    )
    if not trigger:
        return None
    for i in _word_positions(words, "به"):
        if i + 1 < len(words) and _clean(words[i + 1]) == "من":
            continue  # «به من» — این طرفِ بدهی نیست، خودِ کاربر است
        name = _take_name(words, i + 1)
        if name:
            return name
    return None


def _find_receivable_from(words: list[str]) -> Optional[str]:
    """طلبِ من از کسی — «از NAME ... طلب دارم» / «... طلبکارم»."""
    trigger = (
        _has_word(words, "طلبکارم") or _has_word(words, "طلبکاریم")
        or (_has_word(words, "طلب") and any(_clean(w) in ("دارم", "داریم") for w in words))
    )
    if not trigger:
        return None
    for i in _word_positions(words, "از"):
        if i + 1 < len(words) and _clean(words[i + 1]) == "من":
            continue
        name = _take_name(words, i + 1)
        if name:
            return name
    return None


def _find_receivable_subject(words: list[str]) -> Optional[str]:
    """طلبِ من از کسی، گفته‌شده با فاعلِ سوم‌شخص —
    «NAME ... به من ... بدهکار است/بدهکاره» / «NAME باید ... به من ... بدهد».

    طرف‌حساب فاعلِ جمله است، یعنی همان ابتدای متن.
    """
    if not _has_phrase(words, "به", "من"):
        return None
    trigger = (
        _has_word(words, "بدهکاره")
        or (_has_word(words, "بدهکار")
            and any(_clean(w) in ("است", "هست", "شد", "شده", "بود") for w in words))
        or (_has_word(words, "بدهد") and _has_word(words, "باید"))
    )
    if not trigger:
        return None
    return _take_name(words, 0)


# --- ورودیِ اصلی ---------------------------------------------------------------------


def parse_ledger_text(text: str) -> Optional[ParsedLedgerIntent]:
    """یک جمله‌ی طلب/بدهیِ فارسی را پارس می‌کند؛ در صورتِ شک ``None``.

    ``None`` یعنی «مطمئن نیستم» — لایه‌ی بات باید به مسیرِ عادیِ تراکنش
    برگردد، نه اینکه جهتِ بدهی را حدس بزند؛ حدسِ اشتباه اینجا یعنی طلب و
    بدهی جابه‌جا می‌شود، که از ثبت‌نشدن هم بدتر است.
    """
    if not text or not text.strip():
        return None
    normalized = _normalize(text)
    words = normalized.split()
    if not words:
        return None

    amount = money.parse_amount(normalized)
    if not amount or amount <= 0:
        return None

    party = _find_payable(words)
    if party:
        return ParsedLedgerIntent(
            direction=Direction.PAYABLE, party_name=party[:200],
            amount=amount, raw_text=text.strip(),
        )

    party = _find_receivable_from(words)
    if party:
        return ParsedLedgerIntent(
            direction=Direction.RECEIVABLE, party_name=party[:200],
            amount=amount, raw_text=text.strip(),
        )

    party = _find_receivable_subject(words)
    if party:
        return ParsedLedgerIntent(
            direction=Direction.RECEIVABLE, party_name=party[:200],
            amount=amount, raw_text=text.strip(),
        )

    return None
