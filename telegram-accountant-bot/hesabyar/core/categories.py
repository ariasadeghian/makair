"""تشخیص دسته‌ی هزینه/درآمد بر اساس کلیدواژه‌های فارسی.

ساده و قابل‌گسترش؛ برای MVP نیازی به مدل یادگیری ماشین نیست.
"""
from __future__ import annotations

from ..db.models import Kind

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


def detect_category(text: str, kind: str) -> str:
    """دسته‌ی مناسب را بر اساس متن و نوع تراکنش برمی‌گرداند."""
    haystack = (text or "").replace("‌", " ")
    table = INCOME_CATEGORIES if kind == Kind.INCOME else EXPENSE_CATEGORIES
    for label, keywords in table:
        for kw in keywords:
            if kw.replace("‌", " ") in haystack:
                return label
    return DEFAULT_INCOME if kind == Kind.INCOME else DEFAULT_EXPENSE
