import datetime as dt

from hesabyar.core import jalali
from hesabyar.core.categories import category_options
from hesabyar.db.models import Kind
from hesabyar.services import transactions as tx

UID = 33


async def _add(store, amount, category="متفرقه", kind=Kind.EXPENSE, when=None):
    return await tx.add_transaction(
        store, UID, kind=kind, amount=amount, category=category,
        description="x", occurred_at=when or jalali.now(),
    )


class TestRecent:
    async def test_newest_first_and_limit(self, store):
        await tx.get_or_create_user(store, UID)
        now = jalali.now()
        for i in range(5):
            await _add(store, (i + 1) * 1000, when=now - dt.timedelta(days=i))
        rows = tx.recent(store, UID, limit=3)
        assert len(rows) == 3
        # جدیدترین (امروز، مبلغ ۱۰۰۰) اول است
        assert rows[0].amount == 1000


class TestGetUpdate:
    async def test_get_own_only(self, store):
        await tx.get_or_create_user(store, UID)
        t = await _add(store, 5000)
        assert tx.get_transaction(store, UID, t.id) is not None
        assert tx.get_transaction(store, 999, t.id) is None

    async def test_update_amount(self, store):
        await tx.get_or_create_user(store, UID)
        t = await _add(store, 5000)
        updated = await tx.update_transaction(store, UID, t.id, amount=8000)
        assert updated is not None and updated.amount == 8000

    async def test_update_category(self, store):
        await tx.get_or_create_user(store, UID)
        t = await _add(store, 5000, category="متفرقه")
        updated = await tx.update_transaction(store, UID, t.id, category="اجاره")
        assert updated.category == "اجاره"

    async def test_update_other_user_denied(self, store):
        await tx.get_or_create_user(store, UID)
        t = await _add(store, 5000)
        assert await tx.update_transaction(store, 999, t.id, amount=1) is None
        # مقدار اصلی دست‌نخورده
        assert tx.get_transaction(store, UID, t.id).amount == 5000


class TestCategoryOptions:
    def test_expense_has_default(self):
        opts = category_options(Kind.EXPENSE)
        assert "متفرقه" in opts
        assert "اجاره" in opts

    def test_income_options(self):
        opts = category_options(Kind.INCOME)
        assert "فروش کالا" in opts
        assert len(opts) >= 2
