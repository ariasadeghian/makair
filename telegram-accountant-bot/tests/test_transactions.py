"""تست سرویس تراکنش‌ها."""
import datetime as dt

import jdatetime

from hesabyar.core import jalali
from hesabyar.db.models import Kind, User
from hesabyar.services import transactions

USER_ID = 555_111


def _dt(year: int, month: int, day: int, hh: int = 12, mm: int = 0) -> dt.datetime:
    """ساخت datetime aware تهران از تاریخ شمسی."""
    g = jdatetime.date(year, month, day).togregorian()
    return dt.datetime(g.year, g.month, g.day, hh, mm, tzinfo=jalali.TEHRAN)


class TestGetOrCreateUser:
    async def test_creates_when_missing(self, store):
        user = await transactions.get_or_create_user(store, USER_ID, business_name="کافه‌ی من")
        assert isinstance(user, User)
        assert user.id == USER_ID
        assert user.business_name == "کافه‌ی من"

    async def test_returns_existing(self, store):
        first = await transactions.get_or_create_user(store, USER_ID)
        second = await transactions.get_or_create_user(store, USER_ID)
        assert first.id == second.id
        # نباید کاربر دوم ساخته شود.
        assert len(store.list("users")) == 1


class TestFirstTransactionMilestone:
    async def test_stamps_first_transaction_once(self, store):
        await transactions.get_or_create_user(store, USER_ID)
        assert (store.get("users", USER_ID)).first_transaction_at is None

        first = await transactions.add_transaction(
            store, USER_ID, kind=Kind.EXPENSE, amount=1_000,
            category="متفرقه", description="", occurred_at=_dt(1403, 5, 3),
        )
        assert (store.get("users", USER_ID)).first_transaction_at == first.created_at

        await transactions.add_transaction(
            store, USER_ID, kind=Kind.EXPENSE, amount=2_000,
            category="متفرقه", description="", occurred_at=_dt(1403, 5, 4),
        )
        # دومین تراکنش مهرِ اول را جابه‌جا نمی‌کند.
        assert (store.get("users", USER_ID)).first_transaction_at == first.created_at


class TestAddAndList:
    async def test_add_transaction_persists(self, store):
        await transactions.get_or_create_user(store, USER_ID)
        tx = await transactions.add_transaction(
            store,
            USER_ID,
            kind=Kind.EXPENSE,
            amount=250_000,
            category="قبوض",
            description="قبض برق",
            occurred_at=_dt(1403, 5, 3),
        )
        assert tx.id is not None
        assert tx.amount == 250_000
        assert tx.kind == Kind.EXPENSE

    async def test_list_orders_by_occurred_at(self, store):
        await transactions.get_or_create_user(store, USER_ID)
        await transactions.add_transaction(
            store, USER_ID, kind=Kind.EXPENSE, amount=100,
            category="حمل و نقل", description="", occurred_at=_dt(1403, 5, 10),
        )
        await transactions.add_transaction(
            store, USER_ID, kind=Kind.INCOME, amount=200,
            category="فروش کالا", description="", occurred_at=_dt(1403, 5, 2),
        )
        start, end = _dt(1403, 5, 1, 0, 0), _dt(1403, 5, 31, 23, 59)
        rows = transactions.list_transactions(store, USER_ID, start, end)
        assert [r.amount for r in rows] == [200, 100]  # صعودی بر occurred_at

    async def test_list_filters_by_range(self, store):
        await transactions.get_or_create_user(store, USER_ID)
        await transactions.add_transaction(
            store, USER_ID, kind=Kind.EXPENSE, amount=50,
            category="قبوض", description="", occurred_at=_dt(1403, 4, 20),
        )
        await transactions.add_transaction(
            store, USER_ID, kind=Kind.EXPENSE, amount=70,
            category="قبوض", description="", occurred_at=_dt(1403, 5, 5),
        )
        start, end = _dt(1403, 5, 1, 0, 0), _dt(1403, 5, 31, 23, 59)
        rows = transactions.list_transactions(store, USER_ID, start, end)
        assert len(rows) == 1
        assert rows[0].amount == 70

    async def test_list_filters_by_kind(self, store):
        await transactions.get_or_create_user(store, USER_ID)
        await transactions.add_transaction(
            store, USER_ID, kind=Kind.EXPENSE, amount=50,
            category="قبوض", description="", occurred_at=_dt(1403, 5, 5),
        )
        await transactions.add_transaction(
            store, USER_ID, kind=Kind.INCOME, amount=900,
            category="فروش کالا", description="", occurred_at=_dt(1403, 5, 6),
        )
        start, end = _dt(1403, 5, 1, 0, 0), _dt(1403, 5, 31, 23, 59)
        incomes = transactions.list_transactions(
            store, USER_ID, start, end, kind=Kind.INCOME
        )
        assert len(incomes) == 1
        assert incomes[0].kind == Kind.INCOME


class TestSummary:
    async def _seed(self, store):
        await transactions.get_or_create_user(store, USER_ID)
        await transactions.add_transaction(
            store, USER_ID, kind=Kind.INCOME, amount=1_000_000,
            category="فروش کالا", description="", occurred_at=_dt(1403, 5, 2),
        )
        await transactions.add_transaction(
            store, USER_ID, kind=Kind.INCOME, amount=500_000,
            category="درآمد خدمات", description="", occurred_at=_dt(1403, 5, 3),
        )
        await transactions.add_transaction(
            store, USER_ID, kind=Kind.EXPENSE, amount=300_000,
            category="قبوض", description="", occurred_at=_dt(1403, 5, 4),
        )
        await transactions.add_transaction(
            store, USER_ID, kind=Kind.EXPENSE, amount=200_000,
            category="قبوض", description="", occurred_at=_dt(1403, 5, 5),
        )
        await transactions.add_transaction(
            store, USER_ID, kind=Kind.EXPENSE, amount=150_000,
            category="حمل و نقل", description="", occurred_at=_dt(1403, 5, 6),
        )

    async def test_totals(self, store):
        await self._seed(store)
        start, end = _dt(1403, 5, 1, 0, 0), _dt(1403, 5, 31, 23, 59)
        s = transactions.summary(store, USER_ID, start, end)
        assert s["income"] == 1_500_000
        assert s["expense"] == 650_000
        assert s["balance"] == 850_000
        assert s["count"] == 5

    async def test_category_grouping(self, store):
        await self._seed(store)
        start, end = _dt(1403, 5, 1, 0, 0), _dt(1403, 5, 31, 23, 59)
        s = transactions.summary(store, USER_ID, start, end)
        assert s["expense_by_category"]["قبوض"] == 500_000
        assert s["expense_by_category"]["حمل و نقل"] == 150_000
        assert s["income_by_category"]["فروش کالا"] == 1_000_000
        assert s["income_by_category"]["درآمد خدمات"] == 500_000

    async def test_empty_summary(self, store):
        await transactions.get_or_create_user(store, USER_ID)
        start, end = _dt(1403, 5, 1, 0, 0), _dt(1403, 5, 31, 23, 59)
        s = transactions.summary(store, USER_ID, start, end)
        assert s["income"] == 0
        assert s["expense"] == 0
        assert s["balance"] == 0
        assert s["count"] == 0
        assert s["expense_by_category"] == {}
        assert s["income_by_category"] == {}


class TestDeleteLast:
    async def test_delete_last_removes_newest(self, store):
        await transactions.get_or_create_user(store, USER_ID)
        await transactions.add_transaction(
            store, USER_ID, kind=Kind.EXPENSE, amount=100,
            category="قبوض", description="اولی", occurred_at=_dt(1403, 5, 1),
        )
        last = await transactions.add_transaction(
            store, USER_ID, kind=Kind.EXPENSE, amount=200,
            category="قبوض", description="دومی", occurred_at=_dt(1403, 5, 2),
        )
        removed = await transactions.delete_last(store, USER_ID)
        assert removed is not None
        assert removed.id == last.id
        assert removed.amount == 200
        start, end = _dt(1403, 5, 1, 0, 0), _dt(1403, 5, 31, 23, 59)
        remaining = transactions.list_transactions(store, USER_ID, start, end)
        assert len(remaining) == 1
        assert remaining[0].description == "اولی"

    async def test_delete_last_returns_none_when_empty(self, store):
        await transactions.get_or_create_user(store, USER_ID)
        assert await transactions.delete_last(store, USER_ID) is None
