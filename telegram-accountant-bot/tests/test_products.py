from types import SimpleNamespace

from hesabyar.core import jalali
from hesabyar.services import invoices as inv
from hesabyar.services import products as prod
from hesabyar.services import transactions as tx

UID = 21


class TestProducts:
    async def test_add_and_list(self, store):
        await tx.get_or_create_user(store, UID)
        await prod.add_product(store, UID, "مانتو مجلسی", 1_850_000)
        await prod.add_product(store, UID, "شال نخی", 320_000)
        items = prod.list_products(store, UID)
        assert len(items) == 2
        assert items[0].title == "شال نخی"  # جدیدترین اول

    async def test_get_and_delete_scoped(self, store):
        await tx.get_or_create_user(store, UID)
        p = await prod.add_product(store, UID, "کیف", 900_000)
        assert prod.get_product(store, UID, p.id) is not None
        assert prod.get_product(store, 999, p.id) is None
        assert await prod.delete_product(store, 999, p.id) is None  # کاربر دیگر
        assert await prod.delete_product(store, UID, p.id) is not None
        assert prod.get_product(store, UID, p.id) is None


class TestInvoiceDiscountShipping:
    async def test_totals(self, store):
        await tx.get_or_create_user(store, UID)
        invoice = await inv.create_invoice(
            store, UID, customer_name="رضا",
            items=[{"title": "کالا", "quantity": 2, "unit_price": 1_000_000}],
            issue_date=jalali.now().date(), discount=300_000, shipping=50_000,
        )
        assert invoice.subtotal == 2_000_000
        assert invoice.total == 2_000_000 - 300_000 + 50_000

    async def test_defaults_zero(self, store):
        await tx.get_or_create_user(store, UID)
        invoice = await inv.create_invoice(
            store, UID, customer_name="رضا",
            items=[{"title": "کالا", "quantity": 1, "unit_price": 500_000}],
            issue_date=jalali.now().date(),
        )
        assert invoice.total == 500_000


class TestInvoiceImage:
    async def test_png_created(self, store, tmp_path):
        from hesabyar.pdf.invoice_pdf import render_invoice_image

        user = await tx.get_or_create_user(store, UID)
        user.business_name = "بوتیک آرا"
        invoice = await inv.create_invoice(
            store, UID, customer_name="خانم رضایی",
            items=[{"title": "مانتو", "quantity": 2, "unit_price": 1_850_000}],
            issue_date=jalali.now().date(), shipping=60_000,
        )
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
