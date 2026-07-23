from hesabyar.core import jalali
from hesabyar.db.models import Kind
from hesabyar.services import dashboard
from hesabyar.services import transactions as tx

UID = 88

_PNG = b"\x89PNG\r\n\x1a\n"


def test_dashboard_with_data(session, tmp_path):
    user = tx.get_or_create_user(session, UID)
    user.business_name = "کسب‌وکار تست"
    now = jalali.now()
    tx.add_transaction(session, UID, kind=Kind.INCOME, amount=2_000_000,
                       category="فروش کالا", description="فروش", occurred_at=now)
    tx.add_transaction(session, UID, kind=Kind.EXPENSE, amount=800_000,
                       category="اجاره", description="اجاره", occurred_at=now)
    tx.add_transaction(session, UID, kind=Kind.EXPENSE, amount=300_000,
                       category="قبوض", description="برق", occurred_at=now)
    session.commit()

    out = str(tmp_path / "dash.png")
    dashboard.render_dashboard_png(session, UID, out, now=now, business=user)
    with open(out, "rb") as fh:
        head = fh.read(8)
    assert head == _PNG
    import os
    assert os.path.getsize(out) > 5000


def test_dashboard_no_data(session, tmp_path):
    tx.get_or_create_user(session, UID)
    session.commit()
    out = str(tmp_path / "empty.png")
    dashboard.render_dashboard_png(session, UID, out, now=jalali.now())
    with open(out, "rb") as fh:
        assert fh.read(8) == _PNG
