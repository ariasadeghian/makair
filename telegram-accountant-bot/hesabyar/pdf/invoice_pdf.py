"""تولید فاکتور فروش به‌صورت فایل PDF فارسی راست‌به‌چپ.

این ماژول با کمک :mod:`reportlab` و شکل‌دهی متن فارسی
(:mod:`arabic_reshaper` + :mod:`bidi`) یک فاکتور A4 راست‌چین می‌سازد.

نکته: شیء ``invoice`` می‌تواند یک شیء در حافظه (بدون نشست دیتابیس) باشد؛
این ماژول تنها به ویژگی‌های ``invoice.items``، ``invoice.total`` و
``item.line_total`` (که propertyهای مدل‌اند) تکیه می‌کند.

همه‌ی مبالغ عدد صحیح و به «تومان» هستند و با
:func:`hesabyar.core.money.format_amount` قالب‌بندی می‌شوند.
"""
from __future__ import annotations

import os
from typing import Any

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..core import jalali, money

#: نام فونتی که در reportlab ثبت می‌شود.
_FONT_NAME = "Vazirmatn"

#: مسیر پیش‌فرض فونت (کنار همین ماژول: ``pdf/fonts/Vazirmatn-Regular.ttf``).
_DEFAULT_FONT_PATH = os.path.join(
    os.path.dirname(__file__), "fonts", "Vazirmatn-Regular.ttf"
)


def _resolve_font_path() -> str:
    """مسیر فایل فونت را پیدا می‌کند.

    ابتدا فونت کنار ماژول را می‌آزماید و اگر نبود از متغیر محیطی
    ``HESABYAR_PDF_FONT`` استفاده می‌کند. اگر هیچ‌کدام نبود خطا می‌دهد.
    """
    if os.path.isfile(_DEFAULT_FONT_PATH):
        return _DEFAULT_FONT_PATH
    env_path = os.environ.get("HESABYAR_PDF_FONT")
    if env_path and os.path.isfile(env_path):
        return env_path
    raise FileNotFoundError(
        "فایل فونت Vazirmatn یافت نشد؛ آن را کنار ماژول قرار دهید یا "
        "متغیر محیطی HESABYAR_PDF_FONT را تنظیم کنید."
    )


def register_font() -> str:
    """فونت Vazirmatn را در reportlab ثبت می‌کند و نام آن را برمی‌گرداند.

    این تابع idempotent است؛ اگر فونت پیش‌تر ثبت شده باشد دوباره ثبت
    نمی‌کند و تنها نام آن را برمی‌گرداند.
    """
    if _FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return _FONT_NAME
    font_path = _resolve_font_path()
    pdfmetrics.registerFont(TTFont(_FONT_NAME, font_path))
    return _FONT_NAME


def shape_fa(text: str) -> str:
    """متن فارسی را برای نمایش راست‌به‌چپ آماده می‌کند.

    ابتدا با :func:`arabic_reshaper.reshape` حروف را به شکل چسبیده‌ی درست
    درمی‌آورد و سپس با :func:`bidi.algorithm.get_display` ترتیب دیداری
    راست‌به‌چپ را اعمال می‌کند.
    """
    reshaped = arabic_reshaper.reshape(str(text))
    return get_display(reshaped)


def _para(text: str, style: ParagraphStyle) -> Paragraph:
    """یک پاراگراف با متن شکل‌دهی‌شده‌ی فارسی می‌سازد."""
    return Paragraph(shape_fa(text), style)


def render_invoice_pdf(invoice: Any, business: Any, out_path: str) -> str:
    """یک فاکتور فروش A4 راست‌چین در مسیر ``out_path`` می‌سازد.

    :param invoice: شیء فاکتور (مدل :class:`Invoice` یا هم‌ریخت آن). باید
        ویژگی‌های ``number``، ``issue_date``، ``customer_name``،
        ``customer_phone``، ``customer_address``، ``note``، ``items`` و
        ``total`` را داشته باشد.
    :param business: شیء کسب‌وکار (مدل :class:`User` یا هم‌ریخت آن) با
        ویژگی‌های اختیاری ``business_name``، ``phone`` و ``address``.
        می‌تواند ``None`` باشد.
    :param out_path: مسیر فایل خروجی PDF.
    :returns: همان ``out_path``.
    """
    font_name = register_font()

    # --- سبک‌های متنی راست‌چین ------------------------------------------------
    header_style = ParagraphStyle(
        "Header", fontName=font_name, fontSize=18, alignment=TA_CENTER,
        leading=24,
    )
    subheader_style = ParagraphStyle(
        "SubHeader", fontName=font_name, fontSize=11, alignment=TA_CENTER,
        leading=16, textColor=colors.HexColor("#555555"),
    )
    title_style = ParagraphStyle(
        "Title", fontName=font_name, fontSize=15, alignment=TA_CENTER,
        leading=22,
    )
    normal_style = ParagraphStyle(
        "Normal", fontName=font_name, fontSize=11, alignment=TA_RIGHT,
        leading=18,
    )
    total_style = ParagraphStyle(
        "Total", fontName=font_name, fontSize=13, alignment=TA_RIGHT,
        leading=20,
    )

    story: list = []

    # --- سربرگ: نام کسب‌وکار و تلفن -------------------------------------------
    business_name = getattr(business, "business_name", None)
    if business_name:
        story.append(_para(business_name, header_style))
    business_phone = getattr(business, "phone", None)
    if business_phone:
        story.append(_para(f"تلفن: {business_phone}", subheader_style))
    story.append(Spacer(1, 6 * mm))

    # --- عنوان فاکتور --------------------------------------------------------
    story.append(_para("فاکتور فروش", title_style))
    story.append(Spacer(1, 4 * mm))

    # --- شماره و تاریخ فاکتور -------------------------------------------------
    number = getattr(invoice, "number", "") or ""
    issue_date = getattr(invoice, "issue_date", None)
    date_text = jalali.format_date(issue_date) if issue_date is not None else ""
    story.append(_para(f"شماره فاکتور: {number}", normal_style))
    story.append(_para(f"تاریخ: {date_text}", normal_style))
    story.append(Spacer(1, 4 * mm))

    # --- مشخصات مشتری --------------------------------------------------------
    customer_name = getattr(invoice, "customer_name", "") or ""
    story.append(_para(f"مشتری: {customer_name}", normal_style))
    customer_phone = getattr(invoice, "customer_phone", "") or ""
    if customer_phone:
        story.append(_para(f"تلفن مشتری: {customer_phone}", normal_style))
    customer_address = getattr(invoice, "customer_address", "") or ""
    if customer_address:
        story.append(_para(f"نشانی: {customer_address}", normal_style))
    story.append(Spacer(1, 6 * mm))

    # --- جدول اقلام ----------------------------------------------------------
    # ستون‌ها از چپ به راست چیده می‌شوند؛ برای راست‌به‌راست‌بودن دیداری،
    # ترتیب منطقی را وارونه می‌کنیم تا «ردیف» در سمت راست قرار گیرد.
    # ترتیب دیداری (چپ→راست): جمع ردیف | قیمت واحد | تعداد | شرح | ردیف
    head = [
        shape_fa("جمع ردیف"),
        shape_fa("قیمت واحد"),
        shape_fa("تعداد"),
        shape_fa("شرح"),
        shape_fa("ردیف"),
    ]
    table_data: list[list[str]] = [head]

    items = list(getattr(invoice, "items", []) or [])
    for index, item in enumerate(items, start=1):
        quantity = int(getattr(item, "quantity", 0))
        unit_price = int(getattr(item, "unit_price", 0))
        line_total = int(getattr(item, "line_total", quantity * unit_price))
        title = getattr(item, "title", "") or ""
        table_data.append(
            [
                shape_fa(money.format_amount(line_total, with_currency=False)),
                shape_fa(money.format_amount(unit_price, with_currency=False)),
                shape_fa(money.to_persian_digits(str(quantity))),
                shape_fa(title),
                shape_fa(money.to_persian_digits(str(index))),
            ]
        )

    col_widths = [30 * mm, 30 * mm, 16 * mm, 60 * mm, 12 * mm]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#888888")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFEFEF")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                # ستون «شرح» راست‌چین باشد.
                ("ALIGN", (3, 0), (3, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 6 * mm))

    # --- جمع کل --------------------------------------------------------------
    total = int(getattr(invoice, "total", 0))
    story.append(_para(f"جمع کل: {money.format_amount(total)}", total_style))

    # --- یادداشت (در صورت وجود) ----------------------------------------------
    note = getattr(invoice, "note", "") or ""
    if note:
        story.append(Spacer(1, 4 * mm))
        story.append(_para(f"توضیحات: {note}", normal_style))

    # --- ساخت سند ------------------------------------------------------------
    doc = SimpleDocTemplate(
        out_path,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="فاکتور فروش",
    )
    doc.build(story)
    return out_path
