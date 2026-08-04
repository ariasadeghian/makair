"""ساختِ فاکتور از یک جمله‌ی فارسیِ آزاد.

یک جمله مثل «فاکتور به اسم دارا ۳ تا محصول مبل درجه ۲ به قیمت ۲۵ میلیون تومان
هر واحد» را به :class:`ParsedInvoice` تبدیل می‌کند: نامِ مشتری و فهرستِ اقلام
با تعداد و قیمتِ واحد.

تفاوتش با :mod:`hesabyar.core.nlp` این است که آن ماژول یک تراکنشِ تک‌مبلغی
می‌سازد و اینجا چند قلم کالا با تعداد و قیمت از یک جمله بیرون می‌آید. کارِ
عددی (فارسی/انگلیسی، «هزار»/«میلیون»، ریال↔تومان) به
:mod:`hesabyar.core.money` سپرده می‌شود و اینجا دوباره نوشته نمی‌شود.

خروجی هرگز مستقیم ثبت نمی‌شود؛ لایه‌ی بات اول آن را برای تأیید نشان می‌دهد.
اگر نامِ مشتری یا حتی یک قلمِ معتبر پیدا نشود، ``None`` برمی‌گردد تا جریانِ
دستیِ ساختِ فاکتور کار خودش را بکند.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from . import money

# --- واژگان -------------------------------------------------------------------

#: واژه‌هایی که یعنی کاربر فاکتور می‌خواهد، نه ثبتِ یک تراکنش.
INVOICE_KEYWORDS: tuple[str, ...] = (
    "فاکتور", "فاكتور", "صورتحساب", "صورت حساب", "پیش فاکتور", "پیش‌فاکتور",
)

#: نشانه‌های شروعِ نامِ مشتری. ترتیب مهم است — بلندترین اول.
_NAME_MARKERS: tuple[str, ...] = (
    "به اسم", "به نام", "بنام", "به‌نام", "برای", "واسه", "جهت",
)

#: عنوان‌هایی که پیش از نام می‌آیند؛ بعدشان یک واژه‌ی دیگر هم نام است.
_HONORIFICS: frozenset = frozenset({
    "آقای", "اقای", "آقا", "خانم", "خانوم", "جناب", "سرکار", "دکتر", "مهندس",
    "حاج", "حاجی", "استاد", "شرکت", "فروشگاه", "کارگاه", "بازرگانی", "گروه",
    "مغازه", "دفتر", "رستوران", "آژانس", "کافه", "سوپر", "انبار",
})

#: «ی»ِ اضافه که بعد از نیم‌فاصله توکنِ جدا می‌شود («مغازه‌ی حسن»).
_EZAFE = "ی"

#: واژه‌هایی که نامِ مشتری قطعاً به آن‌ها نمی‌رسد.
_NAME_STOP: frozenset = frozenset({
    "فاکتور", "فاكتور", "صورتحساب", "حساب", "پیش", "بزن", "بساز", "صادر",
    "کن", "بنویس", "کنید", "بزنید", "لطفا", "لطفاً", "با", "و", "از", "به",
})

#: واحدهای شمارش — عددِ قبلشان «تعداد» است، نه قیمت.
_COUNTERS: frozenset = frozenset({
    "تا", "عدد", "عددی", "دست", "دستی", "جفت", "کیلو", "کیلوگرم", "گرم",
    "متر", "متری", "بسته", "جعبه", "کارتن", "شاخه", "رول", "ورق", "لیتر",
    "طاقه", "قواره", "پاکت", "کیسه", "تن", "قوطی", "بطری", "پک",
})

#: واژه‌هایی که در نامِ کالا معنایی ندارند و باید حذف شوند.
_FILLER: frozenset = frozenset({
    "محصول", "محصولات", "کالا", "کالای", "جنس", "قیمت", "مبلغ", "قیمتش",
    "به", "با", "از", "هر", "واحد", "کل", "کلی", "روی", "هم", "سرجمع",
    "جمعا", "جمعاً", "مجموعا", "مجموعاً", "مجموع", "در", "کلا", "کلاً",
    "دانه", "دونه", "یکی", "کدوم", "کدام", "تومان", "تومن", "ریال", "ريال",
    "و", "را", "رو",
})

#: قیمتِ نوشته‌شده «جمعِ کل» است، نه قیمتِ هر واحد.
_TOTAL_HINTS: tuple[str, ...] = (
    "قیمت کل", "قیمت کلی", "جمعا", "جمعاً", "روی هم", "رویهم", "سرجمع",
    "در مجموع", "مجموعا", "مجموعاً", "کلا", "کلاً", "جمع کل", "همه با هم",
)

#: قیمتِ نوشته‌شده برای «هر واحد» است.
_UNIT_HINTS: tuple[str, ...] = (
    "هر واحد", "هرواحد", "هر کدوم", "هرکدوم", "هر کدام", "هرکدام", "واحدی",
    "دانه ای", "دونه ای", "هر دانه", "هر عدد", "هر یکی", "تایی", "هر کیلو",
)

#: پسوندهای صفتیِ قیمت («۳ میلیونی») که money آن‌ها را نمی‌شناسد.
_SUFFIX_FIXES: tuple[tuple[str, str], ...] = (
    ("میلیاردی", "میلیارد"), ("ملیاردی", "میلیارد"),
    ("میلیونی", "میلیون"), ("ملیونی", "میلیون"),
    ("هزارتومنی", "هزار"), ("هزارتومانی", "هزار"), ("هزاری", "هزار"),
    ("تومنی", "تومان"), ("تومانی", "تومان"),
)

#: واژه‌هایی که درست قبل از قیمت می‌آیند و جزو نامِ کالا نیستند —
#: «پارچه متری ۳۵۰ هزار»، «کاغذ هرکدوم ۲ میلیون».
_PRICE_LEAD: frozenset = frozenset({
    "هرکدوم", "هرکدام", "هرواحد", "واحدی", "تایی", "رویهم", "قیمت", "مبلغ",
    "کل", "کلی", "جمعا", "جمعاً", "مجموعا", "مجموعاً", "سرجمع", "به", "با",
    "هر", "روی", "هم", "در", "مجموع", "دانه", "دونه", "کدوم", "کدام", "واحد",
})

#: جداکننده‌های قطعیِ اقلام.
_HARD_SPLIT = re.compile(r"[،,;؛+]|\bو\s+همچنین\b")

#: کمینه‌ی عددی که به‌تنهایی «قیمت» به حساب می‌آید (بدون واژه‌ی مقیاس/پول).
MIN_BARE_PRICE = 1_000

#: بیشترین تعدادی که برای یک قلم پذیرفته می‌شود.
MAX_QUANTITY = 100_000


# --- ساختارها -----------------------------------------------------------------


@dataclass
class ParsedInvoiceItem:
    """یک قلمِ فاکتور که از متن بیرون کشیده شده."""

    title: str
    quantity: int
    unit_price: int

    @property
    def total(self) -> int:
        return self.quantity * self.unit_price

    def as_dict(self) -> dict:
        """قالبی که ``services/invoices.create_invoice`` می‌خواهد."""
        return {
            "title": self.title,
            "quantity": int(self.quantity),
            "unit_price": int(self.unit_price),
        }


@dataclass
class ParsedInvoice:
    """نتیجه‌ی پارسِ یک جمله‌ی فاکتور — هنوز ثبت نشده."""

    customer_name: str
    items: list[ParsedInvoiceItem] = field(default_factory=list)
    raw_text: str = ""
    confidence: float = 0.0

    @property
    def total(self) -> int:
        return sum(item.total for item in self.items)

    def as_items(self) -> list[dict]:
        return [item.as_dict() for item in self.items]


# --- کمک‌تابع‌ها ----------------------------------------------------------------


def looks_like_invoice(text: str) -> bool:
    """آیا اصلاً ارزشِ پارس‌کردن به‌عنوان فاکتور را دارد؟

    دروازه‌ی ارزان قبل از پارسِ کامل، تا جمله‌های عادیِ تراکنش دست‌نخورده به
    مسیرِ خودشان بروند.
    """
    if not text:
        return False
    haystack = _normalize(text)
    return any(keyword in haystack for keyword in INVOICE_KEYWORDS)


def _normalize(text: str) -> str:
    """یکسان‌سازی: رقمِ انگلیسی، بدون نیم‌فاصله، و پسوندهای صفتیِ قیمت باز شده."""
    out = money.normalize(text or "")
    for suffix, base in _SUFFIX_FIXES:
        out = re.sub(rf"(?<=\S){suffix}\b", f" {base}", out)
        out = re.sub(rf"\b{suffix}\b", base, out)
    return re.sub(r"\s+", " ", out).strip()


def _has_hint(text: str, hints: tuple[str, ...]) -> bool:
    return any(hint in text for hint in hints)


def _clean_word(word: str) -> str:
    return word.strip(" .:؛،,!؟?()[]«»\"'").strip()


def _extract_customer(text: str) -> tuple[str, int, int]:
    """(نامِ مشتری، اندیسِ شروعِ عبارت، اندیسِ پایانِ آن).

    نامِ خالی یعنی پیدا نشد — و آن‌وقت اصلاً فاکتوری در کار نیست.
    """
    for marker in _NAME_MARKERS:
        match = re.search(rf"(?:^|\s|:){re.escape(marker)}\s+", text)
        if match is None:
            continue
        rest = text[match.end():]
        words: list[str] = []
        bounded = False  # نام با علامتِ نگارشی تمام شد؟
        for raw in rest.split():
            word = _clean_word(raw)
            if not word or word in _NAME_STOP or re.search(r"\d", word):
                break
            if word != _EZAFE:  # «مغازه‌ی حسن» ⇒ «مغازه حسن»
                words.append(word)
            if raw != word:  # «علی،» ⇒ مرزِ صریحِ نام
                bounded = True
                break
            if len(words) >= 3:
                break
        # «برای امیر مانیتور ۱۲ میلیون» — «مانیتور» کالاست نه فامیلِ امیر.
        # بدون مرزِ صریح، فقط یک واژه نام است؛ مگر عنوانی مثل «آقای» جلویش باشد.
        if words and not bounded:
            keep = 2 if words[0] in _HONORIFICS and len(words) > 1 else 1
            words = words[:keep]
        name = " ".join(words).strip()
        if name:
            start = match.start() if match.start() == 0 else match.start() + 1
            return name, start, match.end() + len(name)
    return "", -1, -1


#: واژه‌های دستوری که در ابتدای ناحیه‌ی اقلام می‌آیند و کالا نیستند.
_COMMAND_WORDS: frozenset = frozenset({
    "فاکتور", "فاكتور", "صورتحساب", "صورت", "حساب", "پیش", "بزن", "بساز",
    "صادر", "کن", "بنویس", "کنید", "بزنید", "لطفا", "لطفاً", "را", "رو",
    "هم", "با", "شامل", "شاملِ", "این", "موارد", "اینا", "اینها",
})


def _strip_command_words(region: str) -> str:
    """واژه‌های «فاکتور بزن» و مانندش را از ابتدای ناحیه برمی‌دارد.

    نمی‌شود ناحیه را تا اولین رقم بُرید — «مانیتور ۱۲ میلیون» نامِ کالا را
    جلوتر از عدد دارد و آن‌طور حذف می‌شد.
    """
    words = region.split()
    index = 0
    while index < len(words) and _clean_word(words[index]) in _COMMAND_WORDS:
        index += 1
    return " ".join(words[index:]).strip()


def _items_region(text: str, name_start: int, name_end: int) -> str:
    """بخشی از جمله که اقلام داخلش است."""
    region = text[name_end:] if name_end > 0 else text
    if ":" in region:  # «فاکتور بزن: ...» ⇒ هرچه بعد از دونقطه
        region = region.split(":")[-1]
    region = _strip_command_words(region.strip(" ،,؛;:"))
    if not _has_number(region) and name_start > 0:
        # اقلام قبل از نامِ مشتری آمده‌اند: «۲ صندلی ۵۰۰ هزار برای علی»
        before = _strip_command_words(text[:name_start].strip(" ،,؛;:"))
        if _has_number(before):
            return before
    return region


def _has_number(text: str) -> bool:
    """آیا عددی (رقمی یا نوشتاری مثل «یک») در متن هست؟"""
    return bool(money.number_runs(text.split()))


def _split_items(region: str) -> list[str]:
    """تکه‌کردنِ ناحیه‌ی اقلام.

    اول با جداکننده‌های قطعی (ویرگول و…)، بعد با « و » — ولی « و » فقط وقتی
    شکسته می‌شود که هر دو طرفش خودشان یک قلمِ معتبر باشند؛ وگرنه «دو میلیون و
    پانصد هزار» نصف می‌شد.
    """
    chunks = [c.strip() for c in _HARD_SPLIT.split(region) if c and c.strip()]
    out: list[str] = []
    for chunk in chunks:
        out.extend(_split_on_and(chunk))
    return out


def _split_on_and(chunk: str) -> list[str]:
    parts = re.split(r"\s+و\s+", chunk)
    if len(parts) < 2:
        return [chunk]
    result: list[str] = []
    buffer = parts[0]
    for part in parts[1:]:
        if _parse_item(buffer) is not None and _parse_item(part) is not None:
            result.append(buffer)
            buffer = part
        else:
            buffer = f"{buffer} و {part}"
    result.append(buffer)
    return result


def _parse_item(chunk: str) -> Optional[ParsedInvoiceItem]:
    """یک تکه‌متن را به قلمِ فاکتور تبدیل می‌کند (یا ``None``)."""
    text = _normalize(chunk)
    tokens = text.split()
    if not tokens:
        return None
    runs = money.number_runs(tokens)
    if not runs:
        return None

    scored = []
    for start, end, values in runs:
        value = money.eval_run(values)
        if value is None:
            continue
        after = tokens[end + 1] if end + 1 < len(tokens) else ""
        before = tokens[start - 1] if start > 0 else ""
        scored.append({
            "start": start, "end": end, "value": value,
            "has_scale": any(v[0] == "scale" for v in values),
            "after": after, "before": before,
            "currency": money.run_currency(tokens, start, end, text),
        })
    if not scored:
        return None

    # --- قیمت: بزرگ‌ترین عددی که نشانه‌ی پول دارد ---------------------------
    def _is_price(run: dict) -> bool:
        return (
            run["has_scale"]
            or run["after"] in money.CURRENCY_WORDS
            or run["before"] in money.CURRENCY_WORDS
            or run["value"] >= MIN_BARE_PRICE
        )

    price_runs = [r for r in scored if _is_price(r)]
    if not price_runs:
        return None
    price_run = max(price_runs, key=lambda r: r["value"])
    value = price_run["value"]
    if price_run["currency"] == "rial":  # ریال ⇒ تومان، مثل money.parse_amount
        value /= 10
    price = int(round(value))
    if price <= 0:
        return None

    # --- تعداد: عددِ کوچکی که واحدِ شمارش دارد یا اولِ جمله است ---------------
    quantity, qty_run = 1, None
    for run in scored:
        if run is price_run or run["value"] < 1 or run["value"] > MAX_QUANTITY:
            continue
        if run["value"] != int(run["value"]):
            continue
        explicit = run["after"] in _COUNTERS
        leading = run["start"] == 0
        if explicit or leading:
            quantity, qty_run = int(run["value"]), run
            break

    # --- نامِ کالا: آنچه از تعداد و قیمت باقی می‌ماند -------------------------
    drop: set = set(range(price_run["start"], price_run["end"] + 1))
    if qty_run is not None:
        drop |= set(range(qty_run["start"], qty_run["end"] + 1))
        if qty_run["after"] in _COUNTERS:
            drop.add(qty_run["end"] + 1)
    if price_run["end"] + 1 < len(tokens):
        if tokens[price_run["end"] + 1] in money.CURRENCY_WORDS:
            drop.add(price_run["end"] + 1)
    # واژه‌های چسبیده به قیمت («متری ۳۵۰ هزار») جزو نامِ کالا نیستند
    index = price_run["start"] - 1
    while index >= 0 and (
        _clean_word(tokens[index]) in _PRICE_LEAD
        or _clean_word(tokens[index]) in _COUNTERS
    ):
        drop.add(index)
        index -= 1

    words = [
        tok for idx, tok in enumerate(tokens)
        if idx not in drop and _clean_word(tok) not in _FILLER
    ]
    title = money.to_persian_digits(" ".join(_clean_word(w) for w in words)).strip()
    title = re.sub(r"\s+", " ", title)
    if not title:
        return None

    # --- «قیمت کل» یا «هر واحد»؟ ---------------------------------------------
    if quantity > 1 and _has_hint(text, _TOTAL_HINTS) and not _has_hint(text, _UNIT_HINTS):
        unit_price = int(round(price / quantity))
    else:
        unit_price = price
    if unit_price <= 0:
        return None
    return ParsedInvoiceItem(title=title[:200], quantity=quantity, unit_price=unit_price)


def _confidence(text: str, customer: str, items: list[ParsedInvoiceItem]) -> float:
    score = 0.4
    if any(keyword in text for keyword in INVOICE_KEYWORDS):
        score += 0.2
    if _has_hint(text, _NAME_MARKERS):
        score += 0.2
    if any(word in text for word in money.CURRENCY_WORDS):
        score += 0.1
    if _has_hint(text, _TOTAL_HINTS) or _has_hint(text, _UNIT_HINTS):
        score += 0.1
    if len(customer.split()) > 3 or not items:
        score -= 0.2
    return round(max(0.0, min(1.0, score)), 2)


# --- ورودیِ اصلی ---------------------------------------------------------------


def parse_invoice_text(text: str) -> Optional[ParsedInvoice]:
    """یک جمله‌ی فاکتور را پارس می‌کند؛ در صورت شک ``None``.

    ``None`` یعنی «مطمئن نیستم» — لایه‌ی بات باید به جریانِ دستی برگردد، نه
    اینکه چیزی را حدسی ثبت کند.
    """
    if not text or not text.strip():
        return None
    normalized = _normalize(text)
    customer, name_start, name_end = _extract_customer(normalized)
    if not customer:
        return None
    region = _items_region(normalized, name_start, name_end)
    if not region:
        return None
    items = [item for item in (_parse_item(c) for c in _split_items(region)) if item]
    if not items:
        return None
    return ParsedInvoice(
        customer_name=customer[:200],
        items=items,
        raw_text=text.strip(),
        confidence=_confidence(normalized, customer, items),
    )
