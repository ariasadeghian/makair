"""تشخیص دسته‌ی هزینه/درآمد بر اساس کلیدواژه‌های فارسی.

ساده و قابل‌گسترش؛ برای MVP نیازی به مدل یادگیری ماشین نیست.
"""
from __future__ import annotations

from . import fuzzy
from ..db.models import Kind

#: آستانه‌ی تطبیقِ تقریبیِ کلیدواژه‌ها — سخت‌گیرانه‌تر از پیش‌فرض، چون
#: کلیدواژه‌ها کوتاه و پرشمارند و اشتباهِ اینجا دسته‌ی تراکنش را عوض می‌کند.
FUZZY_THRESHOLD = 0.85

# ترتیب مهم است: نخستین دسته‌ای که کلیدواژه‌اش پیدا شود انتخاب می‌شود.
EXPENSE_CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    ("اجاره", ("اجاره", "رهن", "ودیعه")),
    ("قبوض", ("قبض", "برق", "آب", "گاز", "تلفن", "اینترنت", "شارژ", "موبایل")),
    ("حقوق و دستمزد", ("حقوق", "دستمزد", "پرسنل", "کارگر", "کارمند", "پاداش")),
    (
        "خرید کالا و مواد اولیه",
        ("مواد اولیه", "جنس", "کالا", "بار", "خرید مواد", "متریال", "قطعه"),
    ),
    ("حمل و نقل", ("پیک", "باربری", "کرایه", "بنزین", "گازوئیل", "تاکسی", "اسنپ", "حمل")),
    (
        "بازاریابی و تبلیغات",
        ("تبلیغ", "تبلیغات", "ادز", "ads", "بازاریابی", "پیج", "بنر", "کاتالوگ"),
    ),
    ("مالیات و بیمه", ("مالیات", "عوارض", "بیمه", "دارایی")),
    ("تعمیر و نگهداری", ("تعمیر", "سرویس", "نگهداری", "قطعه یدکی")),
    ("پذیرایی و خوراک", ("پذیرایی", "ناهار", "شام", "غذا", "رستوران", "کافه", "قهوه")),
    ("ملزومات اداری", ("لوازم‌التحریر", "کاغذ", "پرینت", "نوشت‌افزار", "ملزومات")),
]

INCOME_CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    ("فروش کالا", ("فروش", "فروختم", "فروخت", "فاکتور فروش")),
    ("درآمد خدمات", ("خدمات", "خدمت", "اجرت", "دستمزد خدمت", "کارمزد")),
    ("دریافت طلب", ("طلب", "وصول", "تسویه")),
]

DEFAULT_EXPENSE = "متفرقه"
DEFAULT_INCOME = "فروش کالا"


def category_options(kind: str) -> list[str]:
    """فهرست دسته‌های قابل‌انتخاب برای ویرایش (بر اساس نوع تراکنش)."""
    if kind == Kind.INCOME:
        labels = [label for label, _ in INCOME_CATEGORIES]
        if "سایر درآمد" not in labels:
            labels.append("سایر درآمد")
        return labels
    labels = [label for label, _ in EXPENSE_CATEGORIES]
    if DEFAULT_EXPENSE not in labels:
        labels.append(DEFAULT_EXPENSE)
    return labels


def _fuzzy_category(text: str, table: list) -> str | None:
    """دسته را از روی واژه‌ای که *تقریباً* کلیدواژه است پیدا می‌کند.

    برای غلطِ تایپی و شکل‌های دیگرِ یک واژه («تبلیقات»، «کاغذی») تا یک
    اشتباهِ کوچک کلِ تراکنش را به «متفرقه» نیندازد.
    """
    keyword_label = {}
    for label, keywords in table:
        for kw in keywords:
            keyword_label.setdefault(kw.replace("‌", " "), label)

    best_label, best_score = None, FUZZY_THRESHOLD
    for word in fuzzy.normalize(text).split():
        if len(word) < fuzzy.MIN_LENGTH:
            continue
        for keyword, label in keyword_label.items():
            score = fuzzy.similarity(word, keyword)
            if score > best_score:
                best_label, best_score = label, score
    return best_label


def detect_category(text: str, kind: str) -> str:
    """دسته‌ی مناسب را بر اساس متن و نوع تراکنش برمی‌گرداند."""
    haystack = (text or "").replace("‌", " ")
    table = INCOME_CATEGORIES if kind == Kind.INCOME else EXPENSE_CATEGORIES
    for label, keywords in table:
        for kw in keywords:
            if kw.replace("‌", " ") in haystack:
                return label
    near = _fuzzy_category(haystack, table)
    if near is not None:
        return near
    return DEFAULT_INCOME if kind == Kind.INCOME else DEFAULT_EXPENSE
