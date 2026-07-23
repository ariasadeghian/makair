"""تست جست‌وجو و حذف تراکنش مشخص."""
from hesabyar.core import jalali
from hesabyar.db.models import Kind
from hesabyar.services import transactions as tx


UID = 42


async def _add(store, desc, category, amount=100000, kind=Kind.EXPENSE):
    return await tx.add_transaction(
        store, UID, kind=kind, amount=amount,
        category=category, description=desc, occurred_at=jalali.now(),
    )


class TestSearch:
    async def test_by_description(self, store):
        await tx.get_or_create_user(store, UID)
        await _add(store, "اجاره مغازه مرداد", "اجاره")
        await _add(store, "خرید مواد اولیه", "خرید کالا و مواد اولیه")
        res = tx.search_transactions(store, UID, "اجاره")
        assert len(res) == 1
        assert "اجاره" in res[0].description

    async def test_by_category(self, store):
        await tx.get_or_create_user(store, UID)
        await _add(store, "چیزی", "قبوض")
        assert len(tx.search_transactions(store, UID, "قبوض")) == 1

    async def test_empty_query(self, store):
        await tx.get_or_create_user(store, UID)
        await _add(store, "چیزی", "قبوض")
        assert tx.search_transactions(store, UID, "   ") == []

    async def test_no_match(self, store):
        await tx.get_or_create_user(store, UID)
        await _add(store, "چیزی", "قبوض")
        assert tx.search_transactions(store, UID, "پروازفضایی") == []

    async def test_limit(self, store):
        await tx.get_or_create_user(store, UID)
        for i in range(20):
            await _add(store, f"اجاره {i}", "اجاره")
        assert len(tx.search_transactions(store, UID, "اجاره", limit=5)) == 5


class TestDeleteTransaction:
    async def test_delete_own(self, store):
        await tx.get_or_create_user(store, UID)
        t = await _add(store, "قابل حذف", "متفرقه")
        deleted = await tx.delete_transaction(store, UID, t.id)
        assert deleted is not None
        assert await tx.delete_transaction(store, UID, t.id) is None  # دیگر نیست

    async def test_cannot_delete_other_users(self, store):
        await tx.get_or_create_user(store, UID)
        t = await _add(store, "مال من", "متفرقه")
        assert await tx.delete_transaction(store, 999, t.id) is None
        # هنوز سر جایش هست
        assert store.get("transactions", t.id) is not None
