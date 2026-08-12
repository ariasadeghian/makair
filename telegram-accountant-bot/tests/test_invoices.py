"""تست سرویس صدور و مدیریت فاکتور (invoices)."""
import datetime as dt

import jdatetime

from hesabyar.core import jalali, money
from hesabyar.db.models import Invoice
from hesabyar.services import invoices, transactions

USER_ID = 555_111
OTHER_USER_ID = 666_222


def _date(year: int, month: int, day: int) -> dt.date:
    """ساخت یک datetime.date میلادی از تاریخ شمسی."""
    return jdatetime.date(year, month, day).togregorian()


def _dt(year: int, month: int, day: int, hh: int = 12, mm: int = 0) -> dt.datetime:
    """ساخت datetime aware تهران از تاریخ شمسی."""
    g = jdatetime.date(year, month, day).togregorian()
    return dt.datetime(g.year, g.month, g.day, hh, mm, tzinfo=jalali.TEHRAN)


def _sample_items() -> list[dict]:
    """چند قلم نمونه برای فاکتور."""
    return [
        {"title": "لپ‌تاپ", "quantity": 2, "unit_price": 30_000_000},
        {"title": "ماوس", "quantity": 3, "unit_price": 500_000},
    ]


class TestFirstInvoiceMilestone:
    async def test_stamps_first_invoice_once(self, store):
        await transactions.get_or_create_user(store, USER_ID)
        first = await invoices.create_invoice(
            store, USER_ID, customer_name="علی", items=_sample_items(),
            issue_date=_date(1403, 5, 1),
        )
        assert (store.get("users", USER_ID)).first_invoice_at == first.created_at

        await invoices.create_invoice(
            store, USER_ID, customer_name="رضا", items=_sample_items(),
            issue_date=_date(1403, 5, 2),
        )
        # دومین فاکتور مهرِ اول را جابه‌جا نمی‌کند.
        assert (store.get("users", USER_ID)).first_invoice_at == first.created_at


class TestNextInvoiceNumber:
    async def test_starts_from_one(self, store):
        await transactions.get_or_create_user(store, USER_ID)
        display, seq = invoices.next_invoice_number(
            store, USER_ID, _dt(1403, 5, 1)
        )
        assert seq == 1
        # سال شمسی و شماره‌ی چهاررقمی با ارقام فارسی.
        assert display == money.to_persian_digits("1403-0001")

    async def test_uses_base_jalali_year(self, store):
        await transactions.get_or_create_user(store, USER_ID)
        display, seq = invoices.next_invoice_number(
            store, USER_ID, _dt(1402, 12, 20)
        )
        assert seq == 1
        assert display.startswith(money.to_persian_digits("1402"))

    async def test_increments_after_existing(self, store):
        await invoices.create_invoice(
            store,
            USER_ID,
            customer_name="مشتری اول",
            items=_sample_items(),
            issue_date=_date(1403, 5, 1),
            base=_dt(1403, 5, 1),
        )
        display, seq = invoices.next_invoice_number(
            store, USER_ID, _dt(1403, 5, 2)
        )
        assert seq == 2
        assert display == money.to_persian_digits("1403-0002")

    async def test_per_user_sequence(self, store):
        # فاکتور کاربر اول نباید بر شماره‌ی کاربر دوم اثر بگذارد.
        await invoices.create_invoice(
            store,
            USER_ID,
            customer_name="مشتری کاربر اول",
            items=_sample_items(),
            issue_date=_date(1403, 5, 1),
            base=_dt(1403, 5, 1),
        )
        _, seq = invoices.next_invoice_number(
            store, OTHER_USER_ID, _dt(1403, 5, 1)
        )
        assert seq == 1


class TestCreateInvoice:
    async def test_creates_user_and_persists(self, store):
        invoice = await invoices.create_invoice(
            store,
            USER_ID,
            customer_name="آقای کریمی",
            items=_sample_items(),
            issue_date=_date(1403, 5, 10),
            customer_phone="09120000000",
            customer_address="تهران، خیابان آزادی",
            note="تحویل فوری",
            base=_dt(1403, 5, 10),
        )
        assert isinstance(invoice, Invoice)
        assert invoice.id is not None
        assert invoice.seq == 1
        assert invoice.customer_name == "آقای کریمی"
        assert invoice.customer_phone == "09120000000"
        assert invoice.customer_address == "تهران، خیابان آزادی"
        assert invoice.note == "تحویل فوری"
        assert invoice.issue_date == _date(1403, 5, 10)
        # اقلام باید ذخیره شده باشند.
        assert len(invoice.items) == 2
        # کاربر باید به‌صورت خودکار ساخته شده باشد (کلید خارجی).
        assert store.get("users", USER_ID) is not None

    async def test_total_is_correct(self, store):
        invoice = await invoices.create_invoice(
            store,
            USER_ID,
            customer_name="مشتری",
            items=_sample_items(),
            issue_date=_date(1403, 5, 10),
            base=_dt(1403, 5, 10),
        )
        # 2*30000000 + 3*500000 = 61500000
        assert invoice.total == 2 * 30_000_000 + 3 * 500_000
        assert invoice.items[0].line_total == 60_000_000
        assert invoice.items[1].line_total == 1_500_000

    async def test_defaults_and_optional_fields(self, store):
        invoice = await invoices.create_invoice(
            store,
            USER_ID,
            customer_name="بدون جزئیات",
            items=[{"title": "کالا", "quantity": 1, "unit_price": 1000}],
            issue_date=_date(1403, 5, 10),
            base=_dt(1403, 5, 10),
        )
        assert invoice.customer_phone == ""
        assert invoice.customer_address == ""
        assert invoice.note == ""

    async def test_base_defaults_to_now(self, store):
        # بدون دادن base باید سال جاری شمسی استفاده شود و خطا ندهد.
        invoice = await invoices.create_invoice(
            store,
            USER_ID,
            customer_name="مشتری امروز",
            items=[{"title": "کالا", "quantity": 1, "unit_price": 2000}],
            issue_date=jalali.now().date(),
        )
        current_year = jalali.to_jalali(jalali.now()).year
        assert invoice.number.startswith(money.to_persian_digits(str(current_year)))

    async def test_two_invoices_increasing_and_unique(self, store):
        first = await invoices.create_invoice(
            store,
            USER_ID,
            customer_name="مشتری الف",
            items=_sample_items(),
            issue_date=_date(1403, 5, 1),
            base=_dt(1403, 5, 1),
        )
        second = await invoices.create_invoice(
            store,
            USER_ID,
            customer_name="مشتری ب",
            items=[{"title": "کالای دوم", "quantity": 1, "unit_price": 10_000}],
            issue_date=_date(1403, 5, 2),
            base=_dt(1403, 5, 2),
        )
        # seq افزایشی است.
        assert first.seq == 1
        assert second.seq == 2
        assert second.seq > first.seq
        # شماره‌های نمایشی یکتا هستند.
        assert first.number != second.number
        assert first.number == money.to_persian_digits("1403-0001")
        assert second.number == money.to_persian_digits("1403-0002")


class TestGetInvoice:
    async def test_returns_owned_invoice(self, store):
        invoice = await invoices.create_invoice(
            store,
            USER_ID,
            customer_name="مشتری",
            items=_sample_items(),
            issue_date=_date(1403, 5, 10),
            base=_dt(1403, 5, 10),
        )
        fetched = invoices.get_invoice(store, invoice.id, USER_ID)
        assert fetched is not None
        assert fetched.id == invoice.id

    async def test_wrong_user_returns_none(self, store):
        invoice = await invoices.create_invoice(
            store,
            USER_ID,
            customer_name="مشتری",
            items=_sample_items(),
            issue_date=_date(1403, 5, 10),
            base=_dt(1403, 5, 10),
        )
        await transactions.get_or_create_user(store, OTHER_USER_ID)
        assert invoices.get_invoice(store, invoice.id, OTHER_USER_ID) is None

    async def test_missing_invoice_returns_none(self, store):
        await transactions.get_or_create_user(store, USER_ID)
        assert invoices.get_invoice(store, 999_999, USER_ID) is None


class TestListInvoices:
    async def test_ordered_desc_by_seq(self, store):
        for day in range(1, 4):
            await invoices.create_invoice(
                store,
                USER_ID,
                customer_name=f"مشتری {day}",
                items=[{"title": "کالا", "quantity": 1, "unit_price": 1000}],
                issue_date=_date(1403, 5, day),
                base=_dt(1403, 5, day),
            )
        rows = invoices.list_invoices(store, USER_ID)
        seqs = [r.seq for r in rows]
        assert seqs == [3, 2, 1]

    async def test_respects_limit(self, store):
        for day in range(1, 5):
            await invoices.create_invoice(
                store,
                USER_ID,
                customer_name=f"مشتری {day}",
                items=[{"title": "کالا", "quantity": 1, "unit_price": 1000}],
                issue_date=_date(1403, 5, day),
                base=_dt(1403, 5, day),
            )
        rows = invoices.list_invoices(store, USER_ID, limit=2)
        assert len(rows) == 2
        # جدیدترین‌ها (بزرگ‌ترین seq) باید بیایند.
        assert [r.seq for r in rows] == [4, 3]

    async def test_only_own_invoices(self, store):
        await invoices.create_invoice(
            store,
            USER_ID,
            customer_name="کاربر اول",
            items=_sample_items(),
            issue_date=_date(1403, 5, 1),
            base=_dt(1403, 5, 1),
        )
        await invoices.create_invoice(
            store,
            OTHER_USER_ID,
            customer_name="کاربر دوم",
            items=_sample_items(),
            issue_date=_date(1403, 5, 1),
            base=_dt(1403, 5, 1),
        )
        rows = invoices.list_invoices(store, USER_ID)
        assert len(rows) == 1
        assert rows[0].user_id == USER_ID
