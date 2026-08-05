"""تست ماژول تولید فاکتور PDF.

این تست به دیتابیس نیاز ندارد؛ مدل‌ها مستقیم در حافظه ساخته می‌شوند
(بدون نشست) و تنها به propertyهای ``line_total`` و ``total`` تکیه می‌کنیم.
هیچ اتصال شبکه‌ای در کار نیست.
"""
import datetime as dt

import jdatetime

from hesabyar.core import jalali
from hesabyar.db.models import Invoice, InvoiceItem, User
from hesabyar.pdf import invoice_pdf


def _build_invoice() -> tuple[Invoice, User]:
    """یک فاکتور نمونه با چند قلم و کسب‌وکار را در حافظه می‌سازد."""
    business = User(
        id=555_111,
        business_name="فروشگاه نمونه",
        phone="۰۹۱۲۳۴۵۶۷۸۹",
        address="تهران، خیابان آزادی",
    )

    issue_date = jdatetime.date(1403, 5, 1).togregorian()
    invoice = Invoice(
        number="۱۴۰۳-۰۰۰۱",
        seq=1,
        customer_name="آقای رضایی",
        customer_phone="۰۹۳۵۱۱۱۲۲۳۳",
        customer_address="کرج، بلوار طالقانی",
        issue_date=issue_date,
        note="با تشکر از خرید شما",
    )
    # ست‌کردن مستقیم اقلام روی رابطه (شیء transient بدون نشست).
    invoice.items = [
        InvoiceItem(title="دفتر ۱۰۰ برگ", quantity=3, unit_price=45_000),
        InvoiceItem(title="خودکار آبی", quantity=10, unit_price=8_000),
        InvoiceItem(title="ماژیک وایت‌برد", quantity=2, unit_price=25_000),
    ]
    return invoice, business


class TestRegisterFont:
    def test_returns_font_name(self):
        assert invoice_pdf.register_font() == "Vazirmatn"

    def test_idempotent(self):
        # فراخوانی دوباره نباید خطا بدهد و باید همان نام را برگرداند.
        first = invoice_pdf.register_font()
        second = invoice_pdf.register_font()
        assert first == second == "Vazirmatn"


class TestShapeFa:
    def test_shapes_persian_text(self):
        shaped = invoice_pdf.shape_fa("سلام")
        # خروجی رشته است و خالی نیست.
        assert isinstance(shaped, str)
        assert shaped != ""


class TestModelProperties:
    def test_line_total_and_total(self):
        invoice, _ = _build_invoice()
        # جمع ردیف‌ها درست محاسبه شود.
        assert invoice.items[0].line_total == 135_000
        assert invoice.items[1].line_total == 80_000
        assert invoice.items[2].line_total == 50_000
        # جمع کل = مجموع ردیف‌ها.
        assert invoice.total == 265_000


class TestRenderInvoicePdf:
    def test_creates_valid_pdf(self, tmp_path):
        invoice, business = _build_invoice()
        out_path = str(tmp_path / "invoice.pdf")

        result = invoice_pdf.render_invoice_pdf(invoice, business, out_path)

        # مسیر خروجی برگردانده شود.
        assert result == out_path
        # فایل ساخته شده باشد.
        assert (tmp_path / "invoice.pdf").exists()

        data = (tmp_path / "invoice.pdf").read_bytes()
        # با امضای PDF شروع شود.
        assert data[:4] == b"%PDF"
        # اندازه‌ی منطقی داشته باشد.
        assert len(data) > 1000

    def test_works_without_business(self, tmp_path):
        # حتی بدون کسب‌وکار (business=None) هم باید فاکتور ساخته شود.
        invoice, _ = _build_invoice()
        out_path = str(tmp_path / "invoice_no_business.pdf")

        invoice_pdf.render_invoice_pdf(invoice, None, out_path)

        data = (tmp_path / "invoice_no_business.pdf").read_bytes()
        assert data[:4] == b"%PDF"
        assert len(data) > 1000

    def test_datetime_issue_date(self, tmp_path):
        # اگر issue_date یک datetime باشد هم باید کار کند.
        invoice, business = _build_invoice()
        invoice.issue_date = dt.datetime(2024, 7, 22, 10, 0, tzinfo=jalali.TEHRAN)
        out_path = str(tmp_path / "invoice_dt.pdf")

        invoice_pdf.render_invoice_pdf(invoice, business, out_path)

        data = (tmp_path / "invoice_dt.pdf").read_bytes()
        assert data[:4] == b"%PDF"
        assert len(data) > 1000


class TestRtlLineWrapping:
    """شکستنِ خطِ متنِ فارسیِ بلند.

    :func:`invoice_pdf.shape_fa` متن را به ترتیبِ *دیداری* درمی‌آورد؛ اگر
    شکستنِ خط را به reportlab بسپاریم، آن رشته‌ی از-پیش-وارونه‌شده را مثل
    متنِ چپ‌به‌راست می‌شکند و ابتدای جمله می‌افتد خطِ آخر — یعنی «تلفن:» یک
    خط پایین‌تر از شماره‌اش چاپ می‌شود. این کلاس نگهبانِ همان است.
    """

    def _style(self):
        from reportlab.lib.styles import ParagraphStyle

        return ParagraphStyle(
            "T", fontName=invoice_pdf.register_font(), fontSize=11, leading=16)

    def _width(self, text, style):
        from reportlab.pdfbase import pdfmetrics

        return pdfmetrics.stringWidth(
            invoice_pdf.shape_fa(text), style.fontName, style.fontSize)

    #: همان سربرگی که با پرشدنِ فیلدهای فاز ۱۵ سرریز می‌کند.
    CONTACT = ("تلفن: ۰۲۱۸۸۱۲۳۴۵۶ • موبایل: ۰۹۱۲۱۱۱۲۲۳۳ • ایمیل: info@shirin.ir"
               " • اینستاگرام: @shirin.cake • وب‌سایت: shirin.ir")

    def test_empty_text_is_no_line(self):
        assert invoice_pdf._fit_lines("", self._style(), 400) == []
        assert invoice_pdf._fit_lines(None, self._style(), 400) == []

    def test_short_text_stays_on_one_line(self):
        style = self._style()
        assert invoice_pdf._fit_lines("تلفن: ۰۲۱۸۸۱۲۳۴۵۶", style, 400) == [
            "تلفن: ۰۲۱۸۸۱۲۳۴۵۶"]

    def test_long_contact_line_is_split(self):
        style = self._style()
        lines = invoice_pdf._fit_lines(self.CONTACT, style, invoice_pdf._TEXT_WIDTH)
        assert len(lines) > 1

    def test_every_produced_line_actually_fits(self):
        style = self._style()
        for line in invoice_pdf._fit_lines(
                self.CONTACT, style, invoice_pdf._TEXT_WIDTH):
            assert self._width(line, style) <= invoice_pdf._TEXT_WIDTH

    def test_the_first_token_lands_on_the_first_line(self):
        """رگرسیونِ اصلی: «تلفن:» نباید بیفتد خطِ آخر."""
        lines = invoice_pdf._fit_lines(
            self.CONTACT, self._style(), invoice_pdf._TEXT_WIDTH)
        assert lines[0].startswith("تلفن: ۰۲۱۸۸۱۲۳۴۵۶")

    def test_a_label_is_never_torn_from_its_value(self):
        style = self._style()
        lines = invoice_pdf._fit_lines(self.CONTACT, style, invoice_pdf._TEXT_WIDTH)
        for line in lines:
            for chunk in line.split(" • "):
                assert ": " in chunk, f"تکه‌ی نصفه: {chunk!r}"

    def test_nothing_is_lost_in_the_split(self):
        style = self._style()
        lines = invoice_pdf._fit_lines(self.CONTACT, style, invoice_pdf._TEXT_WIDTH)
        assert " • ".join(lines) == self.CONTACT

    def test_plain_text_wraps_on_spaces(self):
        style = self._style()
        address = "نشانی: " + "تهران، خیابان کارگر شمالی، کوچه‌ی دوم، پلاک ۴۵ " * 3
        lines = invoice_pdf._fit_lines(address, style, invoice_pdf._TEXT_WIDTH)
        assert len(lines) > 1
        assert lines[0].startswith("نشانی:")
        assert " ".join(lines) == " ".join(address.split())

    def test_one_unbreakable_token_is_kept_not_dropped(self):
        """توکنی که خودش از عرض بلندتر است باید بیاید، نه اینکه گم شود."""
        style = self._style()
        giant = "ا" * 400
        assert invoice_pdf._fit_lines(giant, style, 50) == [giant]

    def test_paras_returns_one_paragraph_per_line(self):
        style = self._style()
        lines = invoice_pdf._fit_lines(self.CONTACT, style, invoice_pdf._TEXT_WIDTH)
        assert len(invoice_pdf._paras(
            self.CONTACT, style, invoice_pdf._TEXT_WIDTH)) == len(lines)

    def test_text_width_matches_the_page_margins(self):
        """عرضِ مفید باید با حاشیه‌ی واقعیِ سند بخواند، وگرنه محاسبه دروغ است."""
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm

        assert invoice_pdf._TEXT_WIDTH == A4[0] - 2 * invoice_pdf._MARGIN_MM * mm

    def test_a_crowded_header_still_renders(self, tmp_path):
        invoice, business = _build_invoice()
        business.address = "تهران، میدان انقلاب، خیابان کارگر شمالی، پلاک ۴۵"
        business.postal_code = "1418765432"
        business.mobile = "09121112233"
        business.email = "info@shirin.ir"
        business.instagram = "shirin.cake"
        business.website = "shirin.ir"
        business.economic_code = "411111111111"
        out = tmp_path / "crowded.pdf"
        invoice_pdf.render_invoice_pdf(invoice, business, str(out))
        assert out.read_bytes()[:4] == b"%PDF"
