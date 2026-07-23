import datetime as dt

from hesabyar.core import jalali
from hesabyar.core.categories import category_options
from hesabyar.db.models import Kind
from hesabyar.services import transactions as tx

UID = 33


def _add(session, amount, category="متفرقه", kind=Kind.EXPENSE, when=None):
    return tx.add_transaction(
        session, UID, kind=kind, amount=amount, category=category,
        description="x", occurred_at=when or jalali.now(),
    )


class TestRecent:
    def test_newest_first_and_limit(self, session):
        tx.get_or_create_user(session, UID)
        now = jalali.now()
        for i in range(5):
            _add(session, (i + 1) * 1000, when=now - dt.timedelta(days=i))
        session.commit()
        rows = tx.recent(session, UID, limit=3)
        assert len(rows) == 3
        # جدیدترین (امروز، مبلغ ۱۰۰۰) اول است
        assert rows[0].amount == 1000


class TestGetUpdate:
    def test_get_own_only(self, session):
        tx.get_or_create_user(session, UID)
        t = _add(session, 5000)
        session.commit()
        assert tx.get_transaction(session, UID, t.id) is not None
        assert tx.get_transaction(session, 999, t.id) is None

    def test_update_amount(self, session):
        tx.get_or_create_user(session, UID)
        t = _add(session, 5000)
        session.commit()
        updated = tx.update_transaction(session, UID, t.id, amount=8000)
        assert updated is not None and updated.amount == 8000

    def test_update_category(self, session):
        tx.get_or_create_user(session, UID)
        t = _add(session, 5000, category="متفرقه")
        session.commit()
        updated = tx.update_transaction(session, UID, t.id, category="اجاره")
        assert updated.category == "اجاره"

    def test_update_other_user_denied(self, session):
        tx.get_or_create_user(session, UID)
        t = _add(session, 5000)
        session.commit()
        assert tx.update_transaction(session, 999, t.id, amount=1) is None
        # مقدار اصلی دست‌نخورده
        assert tx.get_transaction(session, UID, t.id).amount == 5000


class TestCategoryOptions:
    def test_expense_has_default(self):
        opts = category_options(Kind.EXPENSE)
        assert "متفرقه" in opts
        assert "اجاره" in opts

    def test_income_options(self):
        opts = category_options(Kind.INCOME)
        assert "فروش کالا" in opts
        assert len(opts) >= 2
