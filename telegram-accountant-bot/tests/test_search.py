"""تست جست‌وجو و حذف تراکنش مشخص."""
from hesabyar.core import jalali
from hesabyar.db.models import Kind
from hesabyar.services import transactions as tx


UID = 42


def _add(session, desc, category, amount=100000, kind=Kind.EXPENSE):
    return tx.add_transaction(
        session, UID, kind=kind, amount=amount,
        category=category, description=desc, occurred_at=jalali.now(),
    )


class TestSearch:
    def test_by_description(self, session):
        tx.get_or_create_user(session, UID)
        _add(session, "اجاره مغازه مرداد", "اجاره")
        _add(session, "خرید مواد اولیه", "خرید کالا و مواد اولیه")
        session.commit()
        res = tx.search_transactions(session, UID, "اجاره")
        assert len(res) == 1
        assert "اجاره" in res[0].description

    def test_by_category(self, session):
        tx.get_or_create_user(session, UID)
        _add(session, "چیزی", "قبوض")
        session.commit()
        assert len(tx.search_transactions(session, UID, "قبوض")) == 1

    def test_empty_query(self, session):
        tx.get_or_create_user(session, UID)
        _add(session, "چیزی", "قبوض")
        session.commit()
        assert tx.search_transactions(session, UID, "   ") == []

    def test_no_match(self, session):
        tx.get_or_create_user(session, UID)
        _add(session, "چیزی", "قبوض")
        session.commit()
        assert tx.search_transactions(session, UID, "پروازفضایی") == []

    def test_limit(self, session):
        tx.get_or_create_user(session, UID)
        for i in range(20):
            _add(session, f"اجاره {i}", "اجاره")
        session.commit()
        assert len(tx.search_transactions(session, UID, "اجاره", limit=5)) == 5


class TestDeleteTransaction:
    def test_delete_own(self, session):
        tx.get_or_create_user(session, UID)
        t = _add(session, "قابل حذف", "متفرقه")
        session.commit()
        deleted = tx.delete_transaction(session, UID, t.id)
        session.commit()
        assert deleted is not None
        assert tx.delete_transaction(session, UID, t.id) is None  # دیگر نیست

    def test_cannot_delete_other_users(self, session):
        tx.get_or_create_user(session, UID)
        t = _add(session, "مال من", "متفرقه")
        session.commit()
        assert tx.delete_transaction(session, 999, t.id) is None
        # هنوز سر جایش هست
        assert session.get(type(t), t.id) is not None
