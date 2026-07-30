"""تشخیص سبکِ رویدادهای مالی در پیام‌های گروه.

یک پیام گروه مثل «@علی لطفاً ۲ میلیون بابت خرید پرینتر پرداخت کن» یا
«پرداخت شد» را می‌گیرد و فقط **نوع رویداد (درخواست/پرداخت) + مبلغ + بابت** را
برمی‌گرداند. اینکه «چه کسی به چه کسی» است، در لایه‌ی هندلر از روی فرستنده و
منشن/ریپلای تعیین می‌شود (نه اینجا).

این ماژول خالص و بدون I/O است تا کاملاً تست‌پذیر باشد.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import datetime as dt

from ..db.models import GroupEventKind
from . import money, nlp
from .nlp import _clean_description, _keyword_max_pos

#: کفِ مبلغ برای ثبتِ تراکنش در گروه (تومان).
#: در گروه پیامِ غیرمالی زیاد است؛ عددهای کوچک معمولاً ساعت/تعداد/شماره‌اند
#: («جلسه ساعت ۳») نه مبلغ.
MIN_GROUP_AMOUNT = 1_000

#: نشانه‌های «پرداخت انجام شد» (گذشته/انجام‌شده).
PAYMENT_CUES: tuple[str, ...] = (
    "پرداخت شد",
    "پرداخت شده",
    "پرداخت کردم",
    "پرداخت کردیم",
    "پرداختم",
    "واریز شد",
    "واریز شده",
    "واریز کردم",
    "واریز کردیم",
    "کارت به کارت کردم",
    "کارت به کارت شد",
    "تسویه شد",
    "تسویه کردم",
    "ریختم به حساب",
    "به حسابش ریختم",
    "حسابش کردم",
)

#: نشانه‌های «درخواست پرداخت» (امری/آینده).
REQUEST_CUES: tuple[str, ...] = (
    "پرداخت کن",
    "پرداخت کنید",
    "پرداخت کنه",
    "پرداختش کن",
    "بپرداز",
    "بپردازید",
    "واریز کن",
    "واریز کنید",
    "واریز کنه",
    "کارت به کارت کن",
    "تسویه کن",
    "تسویه کنید",
    "حسابش کن",
    "درخواست پرداخت",
    "پرداخت بشه",
    "پرداخت شود",
)

#: واژه‌هایی که هنگام ساخت «بابت» باید حذف شوند (فعل/فیلر).
_STRIP_WORDS: frozenset[str] = frozenset({
    "پرداخت", "پرداختم", "کن", "کنید", "کنه", "کردم", "کردیم", "کرد",
    "شد", "شده", "شود", "بشه", "واریز", "بپرداز", "بپردازید", "تسویه",
    "کارت", "حساب", "حسابش", "ریختم", "درخواست", "لطفا", "لطفاً", "رو",
    "را", "به", "بهش", "بابت", "برای", "جهت", "میکنم", "کردید", "کنم",
})

_REASON_MARKERS: tuple[str, ...] = ("بابت", "برای", "جهت")


@dataclass
class ParsedGroupEvent:
    """نتیجه‌ی تشخیص یک رویداد مالی در گروه.

    :ivar kind: ``GroupEventKind.REQUEST`` یا ``GroupEventKind.PAYMENT``.
    :ivar amount: مبلغ به تومان، یا ``None`` اگر در متن نبود (مثلاً «پرداخت شد»
        در پاسخ به یک درخواست که مبلغش از خودِ درخواست می‌آید).
    :ivar reason: «بابتِ» تشخیص‌داده‌شده (best-effort، ممکن است خالی باشد).
    :ivar raw: متن خام.
    """

    kind: str
    amount: Optional[int]
    reason: str
    raw: str


def _strip_cue_words(text: str) -> str:
    return " ".join(t for t in text.split() if t not in _STRIP_WORDS).strip()


def _extract_reason(text: str) -> str:
    """«بابتِ» رویداد را استخراج می‌کند (best-effort)."""
    s = (text or "").replace("‌", " ")
    for marker in _REASON_MARKERS:
        idx = s.find(marker)
        if idx != -1:
            cleaned = _strip_cue_words(_clean_description(s[idx + len(marker):]))
            if cleaned:
                return cleaned
    return _strip_cue_words(_clean_description(s))


def detect_group_event(text: str) -> Optional[ParsedGroupEvent]:
    """اگر پیام یک رویداد مالی به‌نظر برسد، آن را برمی‌گرداند؛ وگرنه ``None``.

    نکته: تشخیص «پرداخت» بر «درخواست» اولویت دارد وقتی هر دو نشانه در متن باشند
    (نشانه‌ای که دیرتر آمده برنده است، مثل فعل اصلی جمله).
    """
    if not text or not text.strip():
        return None

    haystack = text.replace("‌", " ")
    pay_pos = _keyword_max_pos(haystack, PAYMENT_CUES)
    req_pos = _keyword_max_pos(haystack, REQUEST_CUES)
    if pay_pos < 0 and req_pos < 0:
        return None

    kind = GroupEventKind.PAYMENT if pay_pos >= req_pos else GroupEventKind.REQUEST
    return ParsedGroupEvent(
        kind=kind,
        amount=money.parse_amount(text),
        reason=_extract_reason(text),
        raw=text,
    )


def detect_group_transaction(text: str, base: dt.datetime | None = None):
    """فروش/هزینه‌ی خودِ کسب‌وکار در پیامِ گروه؛ ``None`` اگر مطمئن نباشیم.

    در گفت‌وگوی خصوصی هر جمله‌ی دارای مبلغ را ثبت می‌کنیم، ولی در گروه پیامِ
    غیرمالی فراوان است؛ پس **سخت‌گیرانه** عمل می‌کنیم و دو شرط را با هم می‌خواهیم:

    1. یک فعلِ صریحِ مالی در متن باشد (فروختم/خریدم/دادم/پرداختم/گرفتم…)؛
       صرفِ وجودِ عدد کافی نیست.
    2. مبلغ از :data:`MIN_GROUP_AMOUNT` بیشتر باشد تا «جلسه ساعت ۳» یا
       «۲ تا کارتن» به‌عنوان مبلغ خوانده نشود.
    """
    if not text or not text.strip():
        return None

    haystack = text.replace("‌", " ")
    has_verb = (
        _keyword_max_pos(haystack, nlp.INCOME_KEYWORDS) >= 0
        or _keyword_max_pos(haystack, nlp.EXPENSE_KEYWORDS) >= 0
    )
    if not has_verb:
        return None

    parsed = nlp.parse_transaction(text, base=base)
    if parsed is None or parsed.amount < MIN_GROUP_AMOUNT:
        return None
    return parsed
