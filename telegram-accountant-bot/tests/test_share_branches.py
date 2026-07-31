"""تست‌های لینک فاکتور، امتیاز مشتری، یادآوری بدهی، و شعبه‌ها."""
import datetime as dt

from hesabyar.core import jalali
from hesabyar.db.models import Direction, Kind
from hesabyar.services import branches as br
from hesabyar.services import invoices as inv
from hesabyar.services import ledger as ledger_service
from hesabyar.services import transactions as tx

OWNER = 800
STAFF = 801
CUSTOMER = 802


async def _invoice(store, name="رضا محمدی"):
    await tx.get_or_create_user(store, OWNER)
    return await inv.create_invoice(
        store, OWNER, customer_name=name,
        items=[{"title": "کالا", "quantity": 1, "unit_price": 500_000}],
        issue_date=jalali.now().date(),
    )


# --- ۶ب: لینک فاکتور -----------------------------------------------------------


class TestShareLink:
    async def test_token_generated_and_unique(self, store):
        a = await _invoice(store)
        b = await _invoice(store)
        assert a.share_token and b.share_token
        assert a.share_token != b.share_token
        assert len(a.share_token) >= 12  # قابل حدس‌زدن نباشد

    async def test_lookup_by_token(self, store):
        invoice = await _invoice(store)
        found = inv.get_by_token(store, invoice.share_token)
        assert found is not None and found.id == invoice.id
        assert found.items  # اقلام هم پر شده‌اند

    async def test_unknown_token(self, store):
        await _invoice(store)
        assert inv.get_by_token(store, "deadbeef") is None
        assert inv.get_by_token(store, "") is None

    def test_share_link_format(self):
        from hesabyar.db.models import Invoice
        i = Invoice(id=1, share_token="abc123")
        assert inv.share_link("mybot", i) == "https://t.me/mybot?start=fac_abc123"
        assert inv.share_link("", i) == ""

    async def test_attach_customer(self, store):
        invoice = await _invoice(store)
        await inv.attach_customer(store, invoice, CUSTOMER)
        assert store.get("invoices", invoice.id).customer_tg_id == CUSTOMER


# --- ۱۳: امتیاز ----------------------------------------------------------------


class TestRating:
    async def test_set_and_clamp(self, store):
        invoice = await _invoice(store)
        await inv.set_rating(store, invoice, 4)
        assert store.get("invoices", invoice.id).rating == 4
        await inv.set_rating(store, invoice, 9)   # خارج از بازه
        assert store.get("invoices", invoice.id).rating == 5

    async def test_summary(self, store):
        assert inv.rating_summary(store, OWNER) is None
        i1 = await _invoice(store)
        i2 = await _invoice(store)
        await inv.set_rating(store, i1, 5)
        await inv.set_rating(store, i2, 3)
        s = inv.rating_summary(store, OWNER)
        assert s["count"] == 2 and s["average"] == 4.0


# --- ۱۰: یادآوری بدهی ----------------------------------------------------------


class TestDebtorReminder:
    async def test_overdue_only_receivables(self, store):
        now = jalali.now()
        await tx.get_or_create_user(store, OWNER)
        await ledger_service.add_entry(
            store, OWNER, direction=Direction.RECEIVABLE, party_name="علی",
            amount=500_000, due_date=now.date() - dt.timedelta(days=5),
        )
        await ledger_service.add_entry(  # بدهیِ خودم ⇒ نباید بیاید
            store, OWNER, direction=Direction.PAYABLE, party_name="پخش",
            amount=100_000, due_date=now.date() - dt.timedelta(days=5),
        )
        await ledger_service.add_entry(  # هنوز سررسید نشده
            store, OWNER, direction=Direction.RECEIVABLE, party_name="رضا",
            amount=200_000, due_date=now.date() + dt.timedelta(days=5),
        )
        rows = ledger_service.overdue_entries(store, OWNER, now)
        assert [e.party_name for e in rows] == ["علی"]

    async def test_settled_is_excluded(self, store):
        now = jalali.now()
        await tx.get_or_create_user(store, OWNER)
        e = await ledger_service.add_entry(
            store, OWNER, direction=Direction.RECEIVABLE, party_name="علی",
            amount=500_000, due_date=now.date() - dt.timedelta(days=3),
        )
        await ledger_service.settle(store, e.id, OWNER, now)
        assert ledger_service.overdue_entries(store, OWNER, now) == []

    async def test_finds_tg_id_from_past_invoice(self, store):
        invoice = await _invoice(store, name="رضا محمدی")
        await inv.attach_customer(store, invoice, CUSTOMER)
        # نام دفتر «رضا» است و فاکتور «رضا محمدی» ⇒ باید تطبیق دهد
        assert ledger_service.find_party_tg_id(store, OWNER, "رضا") == CUSTOMER
        assert ledger_service.find_party_tg_id(store, OWNER, "ناکس") is None

    async def test_notice_text_mentions_amount(self, store):
        now = jalali.now()
        await tx.get_or_create_user(store, OWNER)
        e = await ledger_service.add_entry(
            store, OWNER, direction=Direction.RECEIVABLE, party_name="علی",
            amount=500_000, due_date=now.date() - dt.timedelta(days=2),
        )
        owner = store.get("users", OWNER)
        owner.business_name = "بوتیک آرا"
        text = ledger_service.build_debtor_notice(e, owner)
        assert "۵۰۰٬۰۰۰" in text and "بوتیک آرا" in text


# --- ۱۱: شعبه‌ها ---------------------------------------------------------------


class TestBranches:
    async def test_create_and_list(self, store):
        await tx.get_or_create_user(store, OWNER)
        b = await br.create_branch(store, OWNER, "شعبه ولیعصر")
        assert len(b.code) == 6 and b.code.isupper()
        assert [x.name for x in br.list_branches(store, OWNER)] == ["شعبه ولیعصر"]

    async def test_codes_are_unique(self, store):
        await tx.get_or_create_user(store, OWNER)
        codes = {(await br.create_branch(store, OWNER, f"ش{i}")).code
                 for i in range(15)}
        assert len(codes) == 15

    async def test_join_routes_to_owner_book(self, store):
        await tx.get_or_create_user(store, OWNER)
        b = await br.create_branch(store, OWNER, "شعبه ۱")
        member = await br.join_with_code(store, STAFF, b.code, name="کارمند")
        assert member is not None
        # کارمند ⇒ دفترِ صاحب‌کار با برچسب شعبه
        assert br.routing_for(store, STAFF) == (OWNER, b.id)
        # صاحب‌کار ⇒ دفتر خودش، بدون شعبه
        assert br.routing_for(store, OWNER) == (OWNER, 0)

    async def test_code_is_case_insensitive(self, store):
        await tx.get_or_create_user(store, OWNER)
        b = await br.create_branch(store, OWNER, "شعبه")
        assert await br.join_with_code(store, STAFF, b.code.lower()) is not None

    async def test_bad_code_rejected(self, store):
        assert await br.join_with_code(store, STAFF, "ZZZZZZ") is None
        assert await br.join_with_code(store, STAFF, "short") is None

    async def test_owner_cannot_join_own_branch(self, store):
        await tx.get_or_create_user(store, OWNER)
        b = await br.create_branch(store, OWNER, "شعبه")
        assert await br.join_with_code(store, OWNER, b.code) is None

    async def test_joining_second_branch_moves_membership(self, store):
        await tx.get_or_create_user(store, OWNER)
        b1 = await br.create_branch(store, OWNER, "یک")
        b2 = await br.create_branch(store, OWNER, "دو")
        await br.join_with_code(store, STAFF, b1.code)
        await br.join_with_code(store, STAFF, b2.code)
        assert len(store.list("branch_members", lambda m: m.user_id == STAFF)) == 1
        assert br.routing_for(store, STAFF)[1] == b2.id

    async def test_leave(self, store):
        await tx.get_or_create_user(store, OWNER)
        b = await br.create_branch(store, OWNER, "شعبه")
        await br.join_with_code(store, STAFF, b.code)
        assert await br.leave(store, STAFF) is True
        assert br.routing_for(store, STAFF) == (STAFF, 0)
        assert await br.leave(store, STAFF) is False

    async def test_deactivated_branch_code_stops_working(self, store):
        await tx.get_or_create_user(store, OWNER)
        b = await br.create_branch(store, OWNER, "شعبه")
        await br.deactivate_branch(store, OWNER, b.id)
        assert await br.join_with_code(store, STAFF, b.code) is None
        assert br.list_branches(store, OWNER) == []

    async def test_totals_split_by_branch(self, store):
        now = jalali.now()
        await tx.get_or_create_user(store, OWNER)
        b1 = await br.create_branch(store, OWNER, "ولیعصر")
        b2 = await br.create_branch(store, OWNER, "انقلاب")
        await tx.add_transaction(store, OWNER, kind=Kind.INCOME, amount=1_000_000,
                                 category="x", description="", occurred_at=now,
                                 branch_id=b1.id, logged_by=STAFF)
        await tx.add_transaction(store, OWNER, kind=Kind.INCOME, amount=3_000_000,
                                 category="x", description="", occurred_at=now,
                                 branch_id=b2.id, logged_by=STAFF)
        await tx.add_transaction(store, OWNER, kind=Kind.EXPENSE, amount=500_000,
                                 category="x", description="", occurred_at=now)

        start, end = jalali.day_bounds(now)
        rows = {r["name"]: r for r in br.branch_totals(store, OWNER, start, end)}
        assert rows["انقلاب"]["income"] == 3_000_000
        assert rows["ولیعصر"]["income"] == 1_000_000
        assert rows["خودِ من"]["expense"] == 500_000

        report = br.build_branch_report(store, OWNER, start, end)
        assert "ولیعصر" in report and "انقلاب" in report
        # جمع کل درست است
        assert "۴٬۰۰۰٬۰۰۰" in report

    async def test_report_when_empty(self, store):
        now = jalali.now()
        start, end = jalali.day_bounds(now)
        assert "ثبتی نداشته" in br.build_branch_report(store, OWNER, start, end)
