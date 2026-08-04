"""تست ایزوله‌بودنِ داده‌ی کاربران در معماری چند-اسپردشیتی (فاز ۱).

سناریو از مسیر واقعیِ سرویس‌ها (نه مستقیم روی Store) دیده می‌شود.
"""
from fakes import FakeClient, FakeSpreadsheet

from hesabyar.core import jalali
from hesabyar.db.models import CENTRAL_TABLES, Direction, Kind, USER_TABLES
from hesabyar.db.store import Store
from hesabyar.services import invoices as inv
from hesabyar.services import ledger
from hesabyar.services import subscription as sub
from hesabyar.services import transactions as tx

A, B = 1001, 1002


async def _fresh():
    central, client = FakeSpreadsheet(), FakeClient()
    s = Store(central, client=client, folder_id="folder-x")
    await s.load()
    return s, central, client


class TestPerUserSpreadsheet:
    async def test_start_flow_creates_own_sheet(self):
        s, _central, client = await _fresh()
        user = await tx.get_or_create_user(s, A, "بوتیک آرا")
        assert user.sheet_id, "کاربر باید اسپردشیت اختصاصی بگیرد"
        own = client.sheets[user.sheet_id]
        assert {w.title for w in own.worksheets()} == set(USER_TABLES)
        # عنوانِ فایل شاملِ نام کسب‌وکار است و داخل پوشه‌ی درست ساخته شده
        title, folder = client.created[0]
        assert "بوتیک آرا" in title and folder == "folder-x"

    async def test_two_users_have_different_sheets(self):
        s, _c, _cl = await _fresh()
        ua = await tx.get_or_create_user(s, A, "الف")
        ub = await tx.get_or_create_user(s, B, "ب")
        assert ua.sheet_id != ub.sheet_id

    async def test_returning_user_reuses_sheet(self):
        s, _c, client = await _fresh()
        first = (await tx.get_or_create_user(s, A, "الف")).sheet_id
        again = (await tx.get_or_create_user(s, A)).sheet_id
        assert first == again
        assert len(client.created) == 1


class TestIsolation:
    async def test_transactions_land_in_own_sheet_only(self):
        s, _c, client = await _fresh()
        now = jalali.now()
        ua = await tx.get_or_create_user(s, A, "الف")
        ub = await tx.get_or_create_user(s, B, "ب")
        await tx.add_transaction(s, A, kind=Kind.INCOME, amount=111,
                                 category="x", description="", occurred_at=now)
        await tx.add_transaction(s, B, kind=Kind.INCOME, amount=222,
                                 category="x", description="", occurred_at=now)
        await s.flush()

        rows_a = client.sheets[ua.sheet_id].worksheet("transactions").get_all_records()
        rows_b = client.sheets[ub.sheet_id].worksheet("transactions").get_all_records()
        assert [int(r["amount"]) for r in rows_a] == [111]
        assert [int(r["amount"]) for r in rows_b] == [222]

    async def test_summary_never_mixes_users(self):
        s, _c, _cl = await _fresh()
        now = jalali.now()
        await tx.get_or_create_user(s, A)
        await tx.get_or_create_user(s, B)
        await tx.add_transaction(s, A, kind=Kind.INCOME, amount=1_000,
                                 category="x", description="", occurred_at=now)
        await tx.add_transaction(s, B, kind=Kind.INCOME, amount=9_000,
                                 category="x", description="", occurred_at=now)
        start, end = jalali.month_bounds(now)
        assert tx.summary(s, A, start, end)["income"] == 1_000
        assert tx.summary(s, B, start, end)["income"] == 9_000

    async def test_invoice_and_ledger_go_to_own_sheet(self):
        s, _c, client = await _fresh()
        ua = await tx.get_or_create_user(s, A, "الف")
        await tx.get_or_create_user(s, B, "ب")
        await inv.create_invoice(
            s, A, customer_name="رضا",
            items=[{"title": "کالا", "quantity": 2, "unit_price": 500}],
            issue_date=jalali.now().date(),
        )
        await ledger.add_entry(s, A, direction=Direction.RECEIVABLE,
                               party_name="علی", amount=700)
        await s.flush()
        own = client.sheets[ua.sheet_id]
        assert len(own.worksheet("invoices").get_all_records()) == 1
        assert len(own.worksheet("invoice_items").get_all_records()) == 1
        assert len(own.worksheet("ledger_entries").get_all_records()) == 1

    async def test_reload_sees_only_the_loaded_user(self):
        s, central, client = await _fresh()
        now = jalali.now()
        await tx.get_or_create_user(s, A)
        await tx.get_or_create_user(s, B)
        await tx.add_transaction(s, A, kind=Kind.INCOME, amount=111,
                                 category="x", description="", occurred_at=now)
        await tx.add_transaction(s, B, kind=Kind.INCOME, amount=222,
                                 category="x", description="", occurred_at=now)
        await s.flush()

        s2 = Store(central, client=client, folder_id="folder-x")
        await s2.load()
        assert s2.list("transactions") == []       # تنبل: هنوز هیچ دفتری باز نشده
        await s2.load_user(A)
        assert [t.amount for t in s2.list("transactions")] == [111]
        await s2.load_user(B)
        assert sorted(t.amount for t in s2.list("transactions")) == [111, 222]


class TestCentralRegistry:
    async def test_registry_tabs_stay_central(self):
        s, central, client = await _fresh()
        user = await tx.get_or_create_user(s, A, "الف")
        await sub.get_or_create_subscription(s, A)
        await s.flush()
        central_titles = {w.title for w in central.worksheets()}
        assert central_titles == set(CENTRAL_TABLES)
        # اشتراک در مرکزی است، نه در دفترِ کاربر
        assert len(central.worksheet("subscriptions").get_all_records()) == 1
        assert "subscriptions" not in {
            w.title for w in client.sheets[user.sheet_id].worksheets()
        }

    async def test_sheet_id_persisted_in_registry(self):
        s, central, client = await _fresh()
        user = await tx.get_or_create_user(s, A, "الف")
        await s.flush()
        row = central.worksheet("users").get_all_records()[0]
        assert row["sheet_id"] == user.sheet_id

        # پس از reload، همان شیت دوباره استفاده می‌شود (نه ساختِ دوباره)
        s2 = Store(central, client=client, folder_id="folder-x")
        await s2.load()
        again = await tx.get_or_create_user(s2, A)
        assert again.sheet_id == user.sheet_id
        assert len(client.created) == 1

    async def test_load_all_users_loads_every_book(self):
        s, central, client = await _fresh()
        now = jalali.now()
        for uid in (A, B):
            await tx.get_or_create_user(s, uid)
            await tx.add_transaction(s, uid, kind=Kind.INCOME, amount=uid,
                                     category="x", description="", occurred_at=now)
        await s.flush()

        s2 = Store(central, client=client, folder_id="folder-x")
        await s2.load()
        loaded = await s2.load_all_users()
        assert loaded == 2
        assert sorted(t.amount for t in s2.list("transactions")) == [A, B]
