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
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..core import jalali, money, seller

#: نام فونتی که در reportlab ثبت می‌شود.
_FONT_NAME = "Vazirmatn"

#: نام فونت ضخیم (برای سربرگ، عنوان و جمع کل).
_FONT_BOLD = "Vazirmatn-Bold"

_FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")

#: مسیر پیش‌فرض فونت (کنار همین ماژول: ``pdf/fonts/Vazirmatn-Regular.ttf``).
_DEFAULT_FONT_PATH = os.path.join(_FONTS_DIR, "Vazirmatn-Regular.ttf")
_DEFAULT_BOLD_PATH = os.path.join(_FONTS_DIR, "Vazirmatn-Bold.ttf")


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


def register_bold_font() -> str:
    """فونت ضخیم را ثبت می‌کند؛ اگر نبود، به فونت معمولی برمی‌گردد.

    نبودِ فایلِ ضخیم نباید صدور فاکتور را بشکند، پس در آن حالت نام فونت
    معمولی برگردانده می‌شود.
    """
    if _FONT_BOLD in pdfmetrics.getRegisteredFontNames():
        return _FONT_BOLD
    bold_path = os.environ.get("HESABYAR_PDF_FONT_BOLD") or _DEFAULT_BOLD_PATH
    if not os.path.isfile(bold_path):
        return register_font()
    pdfmetrics.registerFont(TTFont(_FONT_BOLD, bold_path))
    return _FONT_BOLD


#: نشانه‌ی چپ‌به‌راست (U+200E) برای نگه‌داشتن ترتیب توکن‌های عددی/لاتین
_LRM = "‎"


def ltr(text: str) -> str:
    """یک توکن را با نشانه‌ی چپ‌به‌راست احاطه می‌کند.

    برای رشته‌هایی مثل شماره‌ی فاکتور «۱۴۰۵-۰۰۰۲» که خط تیره دارند لازم است؛
    وگرنه الگوریتم دوجهته در متن راست‌به‌چپ دو بخش عدد را جابه‌جا نشان می‌دهد
    («۰۰۰۲-۱۴۰۵»).
    """
    return f"{_LRM}{text}{_LRM}"


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


#: حاشیه‌ی سند (میلی‌متر) — هم به ``SimpleDocTemplate`` می‌رود و هم مبنای
#: محاسبه‌ی عرضِ مفید است، تا این دو هیچ‌وقت از هم دور نیفتند.
_MARGIN_MM = 18
#: عرضی که متن واقعاً در آن جا می‌شود.
_TEXT_WIDTH = A4[0] - 2 * _MARGIN_MM * mm

#: جداکننده‌ی آیتم‌های تماس در سربرگ — نباید وسطش شکسته شود.
_BULLET = " • "


def _fit_lines(text: str, style: ParagraphStyle, max_width: float) -> list[str]:
    """متنِ *منطقی* را به خط‌هایی می‌شکند که هرکدام در ``max_width`` جا شوند.

    چرا دستی؟ چون :func:`shape_fa` متن را به ترتیبِ *دیداری* درمی‌آورد و
    reportlab آن رشته‌ی از-پیش-وارونه‌شده را مثل متن چپ‌به‌راست می‌شکند؛
    نتیجه این می‌شود که ابتدای جمله می‌افتد خطِ آخر — «تلفن:» یک خط پایین‌تر
    از شماره‌اش. پس اول می‌شکنیم، بعد هر خط را جدا شکل می‌دهیم.

    آیتم‌های تماس (جداشده با «•») واحدِ اتمی‌اند تا برچسب از مقدارش جدا نشود.
    """
    text = str(text or "")
    if not text:
        return []
    tokens = text.split(_BULLET) if _BULLET in text else text.split()
    joiner = _BULLET if _BULLET in text else " "

    def too_wide(candidate: str) -> bool:
        return pdfmetrics.stringWidth(
            shape_fa(candidate), style.fontName, style.fontSize) > max_width

    lines: list[str] = []
    current = ""
    for token in tokens:
        candidate = f"{current}{joiner}{token}" if current else token
        if current and too_wide(candidate):
            lines.append(current)
            current = token
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _paras(text: str, style: ParagraphStyle,
           max_width: float = _TEXT_WIDTH) -> list[Paragraph]:
    """همان :func:`_para`، ولی متنِ بلند را درست می‌شکند."""
    return [_para(line, style) for line in _fit_lines(text, style, max_width)]


#: بیشترین اندازه‌ی لوگو روی سربرگ (میلی‌متر).
LOGO_MAX_W, LOGO_MAX_H = 55, 22
#: بیشترین اندازه‌ی مهر و امضا در پای سند (میلی‌متر).
STAMP_MAX_W, STAMP_MAX_H = 45, 30


def _fitted_image(path: str, max_w_mm: float, max_h_mm: float, align: str = "CENTER"):
    """تصویر را بدون کش‌آمدن در یک کادر جا می‌دهد؛ ``None`` اگر نشد.

    نسبتِ ابعاد حفظ می‌شود — لوگویی که کشیده شده باشد بدتر از نبودنِ لوگوست.
    خطا هرگز بالا نمی‌رود: سندِ بی‌لوگو بهتر از سندِ صادرنشده است.
    """
    if not path or not os.path.isfile(path):
        return None
    try:
        from PIL import Image as PILImage

        with PILImage.open(path) as img:
            src_w, src_h = img.size
        if not src_w or not src_h:
            return None
        scale = min(max_w_mm / src_w, max_h_mm / src_h)
        flowable = Image(path, width=src_w * scale * mm, height=src_h * scale * mm,
                         mask="auto")
        flowable.hAlign = align
        return flowable
    except Exception:
        return None


def _watermark_para(watermark: str, font_name: str) -> Paragraph:
    """امضای کوچکِ بات برای پای سند (سطح برنزی)."""
    style = ParagraphStyle(
        "Watermark", fontName=font_name, fontSize=8, alignment=TA_CENTER,
        leading=12, textColor=colors.HexColor("#9A9A9A"),
    )
    return _para(watermark, style)


def render_invoice_pdf(
    invoice: Any, business: Any, out_path: str, payment_note: str = "",
    watermark: str = "", logo_path: str = "", stamp_path: str = "",
) -> str:
    """یک فاکتور فروش A4 راست‌چین در مسیر ``out_path`` می‌سازد.

    :param invoice: شیء فاکتور (مدل :class:`Invoice` یا هم‌ریخت آن). باید
        ویژگی‌های ``number``، ``issue_date``، ``customer_name``،
        ``customer_phone``، ``customer_address``، ``note``، ``items`` و
        ``total`` را داشته باشد.
    :param business: شیء کسب‌وکار (مدل :class:`User` یا هم‌ریخت آن) با
        ویژگی‌های اختیاری ``business_name``، ``phone`` و ``address``.
        می‌تواند ``None`` باشد.
    :param out_path: مسیر فایل خروجی PDF.
    :param logo_path: مسیرِ فایلِ لوگو (بالای سربرگ). خالی یعنی بدون لوگو.
    :param stamp_path: مسیرِ فایلِ مهر و امضا (پای سند). خالی یعنی بدون مهر.
    :returns: همان ``out_path``.
    """
    font_name = register_font()
    bold_name = register_bold_font()

    # --- سبک‌های متنی راست‌چین ------------------------------------------------
    header_style = ParagraphStyle(
        "Header", fontName=bold_name, fontSize=18, alignment=TA_CENTER,
        leading=24,
    )
    subheader_style = ParagraphStyle(
        "SubHeader", fontName=font_name, fontSize=11, alignment=TA_CENTER,
        leading=16, textColor=colors.HexColor("#555555"),
    )
    title_style = ParagraphStyle(
        "Title", fontName=bold_name, fontSize=15, alignment=TA_CENTER,
        leading=22,
    )
    normal_style = ParagraphStyle(
        "Normal", fontName=font_name, fontSize=11, alignment=TA_RIGHT,
        leading=18,
    )
    total_style = ParagraphStyle(
        "Total", fontName=bold_name, fontSize=13, alignment=TA_RIGHT,
        leading=20,
    )

    story: list = []

    # --- سربرگ: مشخصاتِ فروشنده ----------------------------------------------
    # اول از اسنپ‌شاتِ خودِ فاکتور خوانده می‌شود؛ ``business`` فقط برای
    # فاکتورهای قدیمی است که هنوز اسنپ‌شات ندارند.
    source = seller.source_for(invoice, business)
    logo = _fitted_image(logo_path, LOGO_MAX_W, LOGO_MAX_H)
    if logo is not None:
        story.append(logo)
        story.append(Spacer(1, 3 * mm))
    business_name = seller.value_of(source, "business_name")
    if business_name:
        story.extend(_paras(business_name, header_style))
    for line in seller.header_lines(source):
        story.extend(_paras(line, subheader_style))
    story.append(Spacer(1, 6 * mm))

    # --- عنوان فاکتور --------------------------------------------------------
    story.append(_para("فاکتور فروش", title_style))
    if getattr(invoice, "is_void", False):
        void_style = ParagraphStyle(
            "Void", fontName=bold_name, fontSize=14, alignment=TA_CENTER,
            leading=22, textColor=colors.HexColor("#A33B30"),
        )
        story.append(_para("این فاکتور باطل شده است", void_style))
    story.append(Spacer(1, 4 * mm))

    # --- شماره و تاریخ فاکتور -------------------------------------------------
    number = getattr(invoice, "number", "") or ""
    issue_date = getattr(invoice, "issue_date", None)
    date_text = jalali.format_date(issue_date) if issue_date is not None else ""
    story.append(_para(f"شماره فاکتور: {ltr(number)}", normal_style))
    story.append(_para(f"تاریخ: {date_text}", normal_style))
    story.append(Spacer(1, 4 * mm))

    # --- مشخصات مشتری --------------------------------------------------------
    customer_name = getattr(invoice, "customer_name", "") or ""
    story.extend(_paras(f"مشتری: {customer_name}", normal_style))
    customer_phone = getattr(invoice, "customer_phone", "") or ""
    if customer_phone:
        # رقمِ فارسی، هم‌شکلِ بقیه‌ی سند و بدون جابه‌جاییِ دوجهته
        story.append(_para(
            f"تلفن مشتری: {money.to_persian_digits(customer_phone)}", normal_style))
    customer_address = getattr(invoice, "customer_address", "") or ""
    if customer_address:
        story.extend(_paras(f"نشانی: {customer_address}", normal_style))
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
                ("FONTNAME", (0, 0), (-1, 0), bold_name),  # سطر هدر
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

    # --- جمع‌بندی: اقلام، تخفیف، ارسال، جمع کل --------------------------------
    subtotal = int(getattr(invoice, "subtotal", getattr(invoice, "total", 0)))
    discount = int(getattr(invoice, "discount", 0) or 0)
    shipping = int(getattr(invoice, "shipping", 0) or 0)
    total = int(getattr(invoice, "total", subtotal))
    if discount or shipping:
        story.append(_para(f"جمع اقلام: {money.format_amount(subtotal)}", normal_style))
        if discount:
            story.append(
                _para(f"تخفیف: −{money.format_amount(discount)}", normal_style)
            )
        if shipping:
            story.append(
                _para(f"هزینه ارسال: {money.format_amount(shipping)}", normal_style)
            )
    story.append(_para(f"جمع کل: {money.format_amount(total)}", total_style))

    # --- اطلاعات پرداخت (در صورت وجود) ---------------------------------------
    if payment_note:
        story.append(Spacer(1, 4 * mm))
        story.extend(_paras(payment_note, normal_style))

    # --- یادداشت (در صورت وجود) ----------------------------------------------
    note = getattr(invoice, "note", "") or ""
    if note:
        story.append(Spacer(1, 4 * mm))
        story.extend(_paras(f"توضیحات: {note}", normal_style))

    # --- مهر و امضای فروشنده --------------------------------------------------
    # در ایران همین تکه است که «رسید» را «سند» می‌کند؛ راست‌چین، پای سند،
    # با برچسبی که بگوید مالِ کیست.
    stamp = _fitted_image(stamp_path, STAMP_MAX_W, STAMP_MAX_H, align="RIGHT")
    if stamp is not None:
        story.append(Spacer(1, 6 * mm))
        story.append(stamp)
        stamp_style = ParagraphStyle(
            "Stamp", fontName=font_name, fontSize=9, alignment=TA_RIGHT,
            leading=14, textColor=colors.HexColor("#666666"),
            rightIndent=(STAMP_MAX_W / 2 - 12) * mm,
        )
        story.append(_para("مهر و امضای فروشنده", stamp_style))

    # --- امضای بات (سطح برنزی) ------------------------------------------------
    if watermark:
        story.append(Spacer(1, 8 * mm))
        story.append(_watermark_para(watermark, font_name))

    # --- ساخت سند ------------------------------------------------------------
    doc = SimpleDocTemplate(
        out_path,
        pagesize=A4,
        rightMargin=_MARGIN_MM * mm,
        leftMargin=_MARGIN_MM * mm,
        topMargin=_MARGIN_MM * mm,
        bottomMargin=_MARGIN_MM * mm,
        title="فاکتور فروش",
    )
    doc.build(story)
    return out_path


def render_invoice_image(
    invoice: Any,
    business: Any,
    out_path: str,
    payment_note: str = "",
    dpi: int = 150,
    watermark: str = "",
    logo_path: str = "",
    stamp_path: str = "",
) -> str:
    """فاکتور را به‌صورت تصویر PNG می‌سازد (برای فوروارد آسان در پیام‌رسان‌ها).

    ابتدا PDF ساخته می‌شود، سپس صفحه‌ی اول با pymupdf به PNG تبدیل می‌شود.
    """
    import os
    import tempfile

    import fitz  # pymupdf

    fd, tmp_pdf = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        render_invoice_pdf(invoice, business, tmp_pdf, payment_note, watermark,
                           logo_path=logo_path, stamp_path=stamp_path)
        with fitz.open(tmp_pdf) as doc:
            doc[0].get_pixmap(dpi=dpi).save(out_path)
    finally:
        if os.path.exists(tmp_pdf):
            try:
                os.remove(tmp_pdf)
            except OSError:
                pass
    return out_path


def render_statement_pdf(data: dict, out_path: str, watermark: str = "") -> str:
    """کارتِ «صورتحساب طرف‌حساب» را به‌صورت یک PDF جمع‌وجور می‌سازد.

    ``data`` همان دیکشنریِ خروجی
    :func:`hesabyar.services.ledger.party_statement_data` است:
    ``party``، ``business_name``، ``date``، ``entries`` (فهرست
    ``{label, amount, due_date, is_cheque}``) و ``net``.
    اندازه‌ی صفحه بر اساس تعداد ردیف‌ها محاسبه می‌شود تا کارت بدون فضای خالیِ
    اضافه و مناسبِ فوروارد باشد.
    """
    font_name = register_font()
    bold_name = register_bold_font()
    entries = list(data.get("entries") or [])
    n = max(1, len(entries))
    page_w = 120 * mm
    # ارتفاعِ سخاوتمند تا هیچ‌وقت محتوا (به‌ویژه خطِ مانده) نصفه نشود؛
    # فضای خالیِ اضافه بعداً در تصویر auto-crop می‌شود.
    page_h = (80 + n * 14) * mm

    title_style = ParagraphStyle(
        "StTitle", fontName=bold_name, fontSize=16, alignment=TA_CENTER, leading=24,
    )
    biz_style = ParagraphStyle(
        "StBiz", fontName=bold_name, fontSize=13, alignment=TA_CENTER, leading=20,
    )
    sub_style = ParagraphStyle(
        "StSub", fontName=font_name, fontSize=10, alignment=TA_CENTER, leading=16,
        textColor=colors.HexColor("#666666"),
    )

    story: list = []
    if data.get("business_name"):
        story.append(_para(data["business_name"], biz_style))
    story.append(_para("صورتحساب", title_style))
    story.append(_para(f"طرف‌حساب: {data.get('party', '')}", sub_style))
    story.append(Spacer(1, 4 * mm))

    head = [shape_fa("مبلغ (تومان)"), shape_fa("سررسید"), shape_fa("شرح")]
    table_data: list[list[str]] = [head]
    for row in entries:
        due = jalali.format_date(row["due_date"]) if row.get("due_date") else "—"
        tag = "چک " if row.get("is_cheque") else ""
        desc = f"{tag}{row.get('label', '')} شما"
        table_data.append([
            shape_fa(money.format_amount(row["amount"], with_currency=False)),
            shape_fa(due),
            shape_fa(desc),
        ])
    table = Table(table_data, colWidths=[34 * mm, 30 * mm, 44 * mm])
    table.setStyle(
        TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font_name),
            ("FONTNAME", (0, 0), (-1, 0), bold_name),  # سطر هدر
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BBBBBB")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFEFEF")),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("ALIGN", (2, 0), (2, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    story.append(table)
    story.append(Spacer(1, 5 * mm))

    net = int(data.get("net", 0))
    if net > 0:
        balance_text = f"مانده: {money.format_amount(net)} بدهکار"
    elif net < 0:
        balance_text = f"مانده: {money.format_amount(-net)} بستانکار"
    else:
        balance_text = "مانده: تسویه"
    balance_style = ParagraphStyle(
        "StBal", fontName=bold_name, fontSize=15, alignment=TA_CENTER, leading=24,
        textColor=colors.HexColor("#1f3a5f"),
    )
    story.append(_para(balance_text, balance_style))
    story.append(Spacer(1, 2 * mm))
    date_val = data.get("date")
    if date_val is not None:
        story.append(_para(f"تاریخ: {jalali.format_date(date_val)}", sub_style))
    if watermark:
        story.append(Spacer(1, 3 * mm))
        story.append(_watermark_para(watermark, font_name))

    doc = SimpleDocTemplate(
        out_path, pagesize=(page_w, page_h),
        rightMargin=10 * mm, leftMargin=10 * mm,
        topMargin=8 * mm, bottomMargin=8 * mm, title="صورتحساب",
    )
    doc.build(story)
    return out_path


def _autocrop_whitespace(path: str, pad: int = 26) -> None:
    """حاشیه‌ی سفیدِ اطرافِ یک PNG را می‌بُرد تا کارت جمع‌وجور شود.

    اگر Pillow در دسترس نباشد یا تصویر تماماً سفید باشد، بی‌سروصدا رد می‌شود.
    """
    try:
        from PIL import Image, ImageChops
    except Exception:  # noqa: BLE001 - بدون Pillow فقط crop نمی‌شود
        return
    try:
        img = Image.open(path).convert("RGB")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bbox = ImageChops.difference(img, bg).getbbox()
        if not bbox:
            return
        left = max(0, bbox[0] - pad)
        top = max(0, bbox[1] - pad)
        right = min(img.width, bbox[2] + pad)
        bottom = min(img.height, bbox[3] + pad)
        img.crop((left, top, right, bottom)).save(path)
    except Exception:  # noqa: BLE001 - crop یک صیقلِ اختیاری است
        return


def render_statement_image(
    data: dict, out_path: str, dpi: int = 150, watermark: str = ""
) -> str:
    """صورتحساب طرف‌حساب را به‌صورت تصویر PNG می‌سازد (برای فوروارد آسان)."""
    import os
    import tempfile

    import fitz  # pymupdf

    fd, tmp_pdf = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        render_statement_pdf(data, tmp_pdf, watermark)
        with fitz.open(tmp_pdf) as doc:
            doc[0].get_pixmap(dpi=dpi).save(out_path)
        _autocrop_whitespace(out_path)
    finally:
        if os.path.exists(tmp_pdf):
            try:
                os.remove(tmp_pdf)
            except OSError:
                pass
    return out_path
