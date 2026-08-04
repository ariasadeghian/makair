"""تست‌های جدول مشتریان و لینک‌شدنِ فاکتور و دفتر به آن (فاز ۲)."""
from hesabyar.core import jalali
from hesabyar.db.models import Direction, Instrument
from hesabyar.services import customers as cust
from hesabyar.services import invoices as inv
from hesabyar.services import ledger
from hesabyar.services import transactions as tx

UID = 4001


async def _invoice(store, name, amount=500_000):
    return await inv.create_invoice(
        store, UID, customer_name=name,
        items=[{"title": "کالا", "quantity": 1, "unit_price": amount}],
        issue_date=jalali.now().date(),
    )


class TestFindOrCreate:
    async def test_creates_once_and_reuses(self, store):
        await tx.get_or_create_user(store, UID)
        a = await cust.find_or_create_customer(store, UID, "رضا محمدی")
        b = await cust.find_or_create_customer(store, UID, "رضا محمدی")
        assert a.id == b.id
        assert len(cust.list_customers(store, UID)) == 1

    async def test_matching_ignores_spacing_and_case(self, store):
        await tx.get_or_create_user(store, UID)
        a = await cust.find_or_create_customer(store, UID, "رضا  محمدی")
        b = await cust.find_or_create_customer(store, UID, " رضا محمدی ")
        c = await cust.find_or_create_customer(store, UID, "Ali Reza")
        d = await cust.find_or_create_customer(store, UID, "ali reza")
        assert a.id == b.id and c.id == d.id
        assert len(cust.list_customers(store, UID)) == 2

    async def test_fills_missing_contact_without_duplicating(self, store):
        await tx.get_or_create_user(store, UID)
        a = await cust.find_or_create_customer(store, UID, "سارا")
        b = await cust.find_or_create_customer(
            store, UID, "سارا", phone="0912", address="تهران"
        )
        assert a.id == b.id
        assert b.phone == "0912" and b.address == "تهران"
        assert len(cust.list_customers(store, UID)) == 1

    async def test_empty_name_returns_none(self, store):
        await tx.get_or_create_user(store, UID)
        assert await cust.find_or_create_customer(store, UID, "   ") is None
        assert cust.list_customers(store, UID) == []

    async def test_scoped_per_user(self, store):
        await tx.get_or_create_user(store, UID)
        await tx.get_or_create_user(store, 9999)
        a = await cust.find_or_create_customer(store, UID, "رضا")
        b = await cust.find_or_create_customer(store, 9999, "رضا")
        assert a.id != b.id
        assert cust.get_customer(store, UID, b.id) is None  # مالِ کاربر دیگر


class TestInvoiceLinking:
    async def test_two_invoices_same_name_share_one_customer(self, store):
        """معیار تکمیل فاز: یک رکورد مشتری، نه دوتا."""
        await tx.get_or_create_user(store, UID)
        i1 = await _invoice(store, "دارا")
        i2 = await _invoice(store, "دارا")
        assert i1.customer_id is not None
        assert i1.customer_id == i2.customer_id
        assert len(cust.list_customers(store, UID)) == 1

    async def test_text_field_still_filled(self, store):
        await tx.get_or_create_user(store, UID)
        invoice = await _invoice(store, "  رضا   محمدی ")
        assert invoice.customer_name == "رضا محمدی"   # نرمال‌شده ولی موجود
        assert invoice.customer_id is not None

    async def test_explicit_customer_id_is_respected(self, store):
        await tx.get_or_create_user(store, UID)
        c = await cust.find_or_create_customer(store, UID, "مریم")
        invoice = await inv.create_invoice(
            store, UID, customer_name="مریم",
            items=[{"title": "x", "quantity": 1, "unit_price": 1}],
            issue_date=jalali.now().date(), customer_id=c.id,
        )
        assert invoice.customer_id == c.id
        assert len(cust.list_customers(store, UID)) == 1


class TestLedgerLinking:
    async def test_entry_links_to_same_customer_as_invoice(self, store):
        await tx.get_or_create_user(store, UID)
        invoice = await _invoice(store, "علی")
        entry = await ledger.add_entry(
            store, UID, direction=Direction.RECEIVABLE,
            party_name="علی", amount=300_000,
        )
        assert entry.customer_id == invoice.customer_id

    async def test_cheque_entry_still_works(self, store):
        await tx.get_or_create_user(store, UID)
        e = await ledger.add_entry(
            store, UID, direction=Direction.PAYABLE, party_name="رضایی",
            amount=1_000, instrument=Instrument.CHEQUE, cheque_no="123456",
        )
        assert e.is_cheque and e.customer_id is not None


class TestRecentCustomers:
    async def test_most_recently_used_first(self, store):
        await tx.get_or_create_user(store, UID)
        old = await cust.find_or_create_customer(store, UID, "قدیمی")
        new = await cust.find_or_create_customer(store, UID, "جدید")
        # استفاده‌ی تازه از «قدیمی» باید او را جلو بیندازد
        await _invoice(store, "قدیمی")
        names = [c.name for c in cust.recent_customers(store, UID, limit=5)]
        assert names[0] == "قدیمی"
        assert set(names) == {old.name, new.name}

    async def test_limit_respected(self, store):
        await tx.get_or_create_user(store, UID)
        for i in range(8):
            await cust.find_or_create_customer(store, UID, f"مشتری {i}")
        assert len(cust.recent_customers(store, UID, limit=3)) == 3

    async def test_empty(self, store):
        assert cust.recent_customers(store, UID) == []


class TestCustomerTotals:
    async def test_totals_across_invoices_and_ledger(self, store):
        await tx.get_or_create_user(store, UID)
        await _invoice(store, "بهنام", amount=1_000_000)
        await _invoice(store, "بهنام", amount=2_000_000)
        await ledger.add_entry(
            store, UID, direction=Direction.RECEIVABLE,
            party_name="بهنام", amount=500_000,
        )
        c = cust.find_customer(store, UID, "بهنام")
        totals = cust.customer_totals(store, UID, c.id)
        assert len(totals["invoices"]) == 2
        assert totals["invoiced"] == 3_000_000
        assert totals["receivable"] == 500_000
        assert totals["net"] == 500_000


class TestStatementUsesCustomer:
    async def test_statement_includes_invoices(self, store):
        user = await tx.get_or_create_user(store, UID)
        user.business_name = "بوتیک آرا"
        await _invoice(store, "رضا", amount=800_000)
        await ledger.add_entry(
            store, UID, direction=Direction.RECEIVABLE,
            party_name="رضا", amount=200_000,
        )
        text = ledger.build_party_statement(store, UID, "رضا", business=user)
        assert "فاکتورهای این مشتری" in text
        assert "۸۰۰٬۰۰۰" in text                 # جمع فاکتورها
        assert "مانده: ۲۰۰٬۰۰۰" in text          # فقط دفتر — فاکتور دوباره شمرده نشده
        assert "بدهکار" in text

    async def test_statement_with_only_invoices(self, store):
        user = await tx.get_or_create_user(store, UID)
        await _invoice(store, "سمیرا", amount=400_000)
        text = ledger.build_party_statement(store, UID, "سمیرا", business=user)
        assert text is not None and "سمیرا" in text
        assert "تسویه" in text  # دفتر خالی است ⇒ مانده صفر

    async def test_unknown_party_still_none(self, store):
        await tx.get_or_create_user(store, UID)
        assert ledger.build_party_statement(store, UID, "هیچ‌کس") is None
