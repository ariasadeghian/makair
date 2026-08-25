"""سربرگِ فاکتور: مشخصاتی که کاربر یک‌بار وارد می‌کند و روی هر سند می‌نشیند.

اینجا **تنها منبعِ حقیقت** برای فهرستِ فیلدهاست: برچسب فارسی، اعتبارسنجی،
ترتیبِ نمایش، و اینکه روی سربرگِ چاپی چه شکلی درمی‌آید. مدل‌ها، کیبورد و
رندرکننده‌ی PDF همه از همین‌جا می‌خوانند تا سه جا از هم دور نیفتند.

نکته‌ی مهم — **قفلِ سند:** موقعِ صدور، این مشخصات روی خودِ ردیفِ فاکتور
کپی می‌شوند (ستون‌های ``seller_*``) و رندرکننده از فاکتور می‌خواند، نه از
پروفایلِ فعلیِ کاربر. اگر مغازه‌دار شش ماه بعد شماره‌اش را عوض کند،
فاکتورهای قدیمی همان چیزی می‌مانند که مشتری در دست دارد.
"""
from __future__ import annotations

import re
from typing import Callable, NamedTuple, Optional

from . import money


class Field(NamedTuple):
    """یک خانه‌ی سربرگ."""

    key: str            #: نامِ ستون روی مدل ``User``
    label: str          #: برچسب فارسی برای دکمه و سربرگ
    icon: str           #: نشانه‌ی دکمه
    hint: str           #: راهنمای ورودی
    clean: Callable     #: نرمال‌سازی؛ ``None`` یعنی ورودی نامعتبر
    on_header: bool = True   #: روی سربرگِ چاپی بیاید؟


# --- نرمال‌سازی و اعتبارسنجی -----------------------------------------------------

_DIGITS = re.compile(r"[^\d+]")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")


def _plain(value: str, limit: int = 200) -> Optional[str]:
    text = " ".join((value or "").split())
    return text[:limit] or None


def _digits(value: str, low: int, high: int) -> Optional[str]:
    """شماره‌ها: ارقام فارسی به انگلیسی، جداکننده‌ها حذف، طول چک می‌شود."""
    raw = _DIGITS.sub("", money.to_english_digits(value or ""))
    return raw if low <= len(raw.lstrip("+")) <= high else None


def _phone(value: str) -> Optional[str]:
    return _digits(value, 6, 15)


def _email(value: str) -> Optional[str]:
    text = (value or "").strip().replace(" ", "")
    return text[:120] if _EMAIL.match(text) else None


def _instagram(value: str) -> Optional[str]:
    """«@shop»، «instagram.com/shop» و «shop» همه یک چیزند."""
    text = (value or "").strip().replace(" ", "")
    text = re.sub(r"^https?://", "", text, flags=re.I)
    text = re.sub(r"^(www\.)?instagram\.com/", "", text, flags=re.I)
    text = text.split("?")[0].strip("/@")
    return text[:60] if re.fullmatch(r"[A-Za-z0-9._]{1,60}", text) else None


def _website(value: str) -> Optional[str]:
    text = (value or "").strip().replace(" ", "")
    text = re.sub(r"^https?://", "", text, flags=re.I).strip("/")
    return text[:120] if re.fullmatch(r"[A-Za-z0-9.\-/_]{4,120}", text) else None


def _postal(value: str) -> Optional[str]:
    return _digits(value, 10, 10)


def _economic(value: str) -> Optional[str]:
    return _digits(value, 6, 16)


# --- فیلدها (ترتیب = ترتیبِ نمایش و ترتیبِ سربرگ) ---------------------------------

FIELDS: tuple[Field, ...] = (
    Field("business_name", "نام کسب‌وکار", "🏪",
          "نامی که روی فاکتور چاپ می‌شود — مثلاً «قنادی شیرین»",
          lambda v: _plain(v, 200)),
    Field("address", "نشانی", "📍",
          "نشانیِ کامل، همان‌طور که می‌خواهی روی فاکتور بیاید",
          lambda v: _plain(v, 300)),
    Field("phone", "تلفن", "☎️",
          "شماره‌ی ثابت با کد شهر — مثلاً ۰۲۱۸۸۱۲۳۴۵۶",
          _phone),
    Field("mobile", "موبایل", "📱",
          "شماره‌ی همراه — مثلاً ۰۹۱۲۱۲۳۴۵۶۷",
          _phone),
    Field("postal_code", "کد پستی", "📮",
          "کد پستی ۱۰ رقمی",
          _postal),
    Field("email", "ایمیل", "✉️",
          "مثلاً shop@example.com",
          _email),
    Field("instagram", "اینستاگرام", "📷",
          "آی‌دی یا لینک — مثلاً @myshop",
          _instagram),
    Field("website", "وب‌سایت", "🌐",
          "مثلاً myshop.ir",
          _website),
    Field("economic_code", "شماره اقتصادی", "🧾",
          "برای فاکتور رسمی — فقط رقم",
          _economic),
    Field("national_id", "شناسه ملی", "🆔",
          "شناسه‌ی ملیِ شخص حقوقی یا کد ملی — فقط رقم",
          _economic),
)

class ImageField(NamedTuple):
    """تصویری که روی سند می‌نشیند — با ``file_id`` تلگرام نگه داشته می‌شود.

    گوگل‌شیت جای باینری نیست؛ ``file_id`` برای همان بات دائمی است و موقعِ
    رندر یک‌بار دانلود و در حافظه کش می‌شود.
    """

    key: str
    label: str
    icon: str
    hint: str


IMAGE_FIELDS: tuple[ImageField, ...] = (
    ImageField("logo_file_id", "لوگو", "🖼",
               "عکسِ لوگو را بفرست — بالای فاکتور، وسط‌چین چاپ می‌شود.\n"
               "پس‌زمینه‌ی شفاف (PNG) بهترین نتیجه را می‌دهد."),
    ImageField("stamp_file_id", "مهر و امضا", "🖊",
               "عکسِ مهر یا امضا را بفرست — پایینِ فاکتور، کنارِ جمع کل "
               "می‌نشیند.\nروی کاغذ سفید عکس بگیر تا تمیز دربیاید."),
)

#: دسترسی سریع با کلید.
BY_KEY: dict = {f.key: f for f in FIELDS}
IMAGE_BY_KEY: dict = {f.key: f for f in IMAGE_FIELDS}

#: همه‌ی کلیدهایی که در اسنپ‌شاتِ فاکتور فریز می‌شوند (متنی + تصویری).
_ALL_KEYS: tuple[str, ...] = tuple(f.key for f in FIELDS) + tuple(
    f.key for f in IMAGE_FIELDS)

#: نامِ ستون‌های اسنپ‌شات روی جدول ``invoices``.
SNAPSHOT_COLUMNS: tuple[str, ...] = tuple(f"seller_{k}" for k in _ALL_KEYS)


def get(field_key: str) -> Optional[Field]:
    return BY_KEY.get(field_key)


def get_image(field_key: str) -> Optional[ImageField]:
    return IMAGE_BY_KEY.get(field_key)


def any_field(field_key: str):
    """فیلد را از هر دو فهرست پیدا می‌کند — برای کارهایی مثل «خالی کن»
    که فرقی بین متن و تصویر ندارند."""
    return BY_KEY.get(field_key) or IMAGE_BY_KEY.get(field_key)


def value_of(source, field_key: str) -> str:
    """مقدارِ یک فیلد از پروفایلِ کاربر یا از اسنپ‌شاتِ فاکتور."""
    if source is None:
        return ""
    snap = getattr(source, f"seller_{field_key}", None)
    if snap:
        return str(snap)
    return str(getattr(source, field_key, "") or "")


def snapshot(user) -> dict:
    """اسنپ‌شاتِ مشخصاتِ فروشنده برای فریزکردن روی فاکتور.

    لوگو و مهر هم فریز می‌شوند: اگر کسب‌وکار بعداً لوگویش را عوض کند،
    فاکتورهای قدیمی باید همان لوگویی را داشته باشند که مشتری دیده است.
    """
    return {f"seller_{k}": str(getattr(user, k, "") or "") for k in _ALL_KEYS}


def image_of(source, field_key: str) -> str:
    """``file_id`` تصویر از اسنپ‌شاتِ فاکتور یا از پروفایل."""
    return value_of(source, field_key)


def source_for(invoice, business):
    """کدام‌یک سربرگ را می‌دهد: اسنپ‌شاتِ فاکتور، یا پروفایلِ فعلیِ کاربر.

    قاعده یکی است و باید یک جا بماند: اگر فاکتور اسنپ‌شات دارد، همان حرفِ
    آخر است. فاکتورهای پیش از اسنپ‌شات (داده‌ی قدیمی) از پروفایل پر می‌شوند
    تا خالی نمانند.
    """
    return invoice if value_of(invoice, "business_name") else business


def is_complete_enough(user) -> bool:
    """آیا سربرگ آن‌قدر پر شده که فاکتور حرفه‌ای دربیاید؟"""
    return bool(value_of(user, "business_name")) and any(
        value_of(user, key) for key in ("phone", "mobile", "address")
    )


def missing_labels(user) -> list[str]:
    """برچسبِ فیلدهای خالی — برای پیشنهادِ تکمیل."""
    return [f.label for f in FIELDS if not value_of(user, f.key)]


# --- سربرگِ چاپی -----------------------------------------------------------------

#: فیلدهایی که کنار هم روی یک خط جمع می‌شوند (تماس).
_CONTACT_KEYS = ("phone", "mobile", "email", "instagram", "website")
#: فیلدهای مالیاتی، روی خطِ خودشان.
_TAX_KEYS = ("economic_code", "national_id")
#: شماره‌هایی که روی سند با رقمِ فارسی چاپ می‌شوند — هم رسم‌الخطِ درست است و
#: هم رقمِ لاتین وسطِ متنِ راست‌چین جای‌به‌جا نمی‌شود. ایمیل و آدرسِ وب البته نه.
_PERSIAN_DIGIT_KEYS = frozenset({
    "phone", "mobile", "postal_code", "economic_code", "national_id",
})


def display(source, field_key: str) -> str:
    """مقدارِ آماده‌ی چاپ (شماره‌ها با رقمِ فارسی)."""
    value = value_of(source, field_key)
    if value and field_key in _PERSIAN_DIGIT_KEYS:
        return money.to_persian_digits(value)
    return value


def header_lines(source) -> list[str]:
    """خط‌های سربرگ، به همان ترتیبی که روی فاکتور چاپ می‌شوند.

    ``source`` می‌تواند فاکتور (با ستون‌های ``seller_*``) یا کاربر باشد؛
    خطِ خالی هرگز چاپ نمی‌شود.
    """
    lines: list[str] = []

    address = value_of(source, "address")
    postal = display(source, "postal_code")
    if address:
        lines.append(f"نشانی: {address}" + (f" — کد پستی {postal}" if postal else ""))
    elif postal:
        lines.append(f"کد پستی: {postal}")

    contact = []
    for key in _CONTACT_KEYS:
        value = display(source, key)
        if not value:
            continue
        if key == "instagram":
            value = f"@{value}"
        contact.append(f"{BY_KEY[key].label}: {value}")
    if contact:
        lines.append(" • ".join(contact))

    tax = [f"{BY_KEY[k].label}: {display(source, k)}"
           for k in _TAX_KEYS if value_of(source, k)]
    if tax:
        lines.append(" • ".join(tax))

    return lines
