from types import SimpleNamespace

from hesabyar.core import jalali
from hesabyar.services import invoices as inv
from hesabyar.services import products as prod
from hesabyar.services import transactions as tx

UID = 21


class TestProducts:
    def test_add_and_list(self, session):
        tx.get_or_create_user(session, UID)
        prod.add_product(session, UID, "مانتو مجلسی", 1_850_000)
        prod.add_product(session, UID, "شال نخی", 320_000)
        items = prod.list_products(session, UID)
        assert len(items) == 2
        assert items[0].title == "شال نخی"  # جدیدترین اول

    def test_get_and_delete_scoped(self, session):
        tx.get_or_create_user(session, UID)
        p = prod.add_product(session, UID, "کیف", 900_000)
        assert prod.get_product(session, UID, p.id) is not None
        assert prod.get_product(session, 999, p.id) is None
        assert prod.delete_product(session, 999, p.id) is None  # کاربر دیگر
        assert prod.delete_product(session, UID, p.id) is not None
        assert prod.get_product(session, UID, p.id) is None


class TestInvoiceDiscountShipping:
    def test_totals(self, session):
        tx.get_or_create_user(session, UID)
        invoice = inv.create_invoice(
            session, UID, customer_name="رضا",
            items=[{"title": "کالا", "quantity": 2, "unit_price": 1_000_000}],
            issue_date=jalali.now().date(), discount=300_000, shipping=50_000,
        )
        session.commit()
        assert invoice.subtotal == 2_000_000
        assert invoice.total == 2_000_000 - 300_000 + 50_000

    def test_defaults_zero(self, session):
        tx.get_or_create_user(session, UID)
        invoice = inv.create_invoice(
            session, UID, customer_name="رضا",
            items=[{"title": "کالا", "quantity": 1, "unit_price": 500_000}],
            issue_date=jalali.now().date(),
        )
        session.commit()
        assert invoice.total == 500_000


class TestInvoiceImage:
    def test_png_created(self, session, tmp_path):
        from hesabyar.pdf.invoice_pdf import render_invoice_image

        user = tx.get_or_create_user(session, UID)
        user.business_name = "بوتیک آرا"
        invoice = inv.create_invoice(
            session, UID, customer_name="خانم رضایی",
            items=[{"title": "مانتو", "quantity": 2, "unit_price": 1_850_000}],
            issue_date=jalali.now().date(), shipping=60_000,
        )
        session.commit()
        out = str(tmp_path / "factor.png")
        render_invoice_image(invoice, user, out, payment_note="پرداخت: کارت به ...")
        with open(out, "rb") as fh:
            assert fh.read(8) == b"\x89PNG\r\n\x1a\n"


class TestParseItem:
    def _p(self):
        from hesabyar.bot import handlers
        return handlers._parse_item

    def test_free_form_name_qty_price(self):
        r = self._p()("مانتو ۲ ۱۸۵۰۰۰۰", {})
        assert r == {"title": "مانتو", "quantity": 2, "unit_price": 1_850_000}

    def test_saved_product(self):
        prods = {"مانتو": SimpleNamespace(unit_price=1_850_000)}
        assert self._p()("مانتو", prods)["unit_price"] == 1_850_000

    def test_saved_product_with_qty(self):
        prods = {"مانتو": SimpleNamespace(unit_price=1_850_000)}
        assert self._p()("۳ مانتو", prods)["quantity"] == 3

    def test_cross_format(self):
        r = self._p()("کفش × ۲ × ۴۰۰ هزار", {})
        assert r == {"title": "کفش", "quantity": 2, "unit_price": 400_000}

    def test_no_price(self):
        assert self._p()("سلام", {}) is None
