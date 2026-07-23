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
