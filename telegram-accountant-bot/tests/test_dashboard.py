from hesabyar.core import jalali
from hesabyar.db.models import Kind
from hesabyar.services import dashboard
from hesabyar.services import transactions as tx

UID = 88

_PNG = b"\x89PNG\r\n\x1a\n"


async def test_dashboard_with_data(store, tmp_path):
    user = await tx.get_or_create_user(store, UID)
    user.business_name = "کسب‌وکار تست"
    now = jalali.now()
    await tx.add_transaction(store, UID, kind=Kind.INCOME, amount=2_000_000,
                             category="فروش کالا", description="فروش", occurred_at=now)
    await tx.add_transaction(store, UID, kind=Kind.EXPENSE, amount=800_000,
                             category="اجاره", description="اجاره", occurred_at=now)
    await tx.add_transaction(store, UID, kind=Kind.EXPENSE, amount=300_000,
                             category="قبوض", description="برق", occurred_at=now)

    out = str(tmp_path / "dash.png")
    dashboard.render_dashboard_png(store, UID, out, now=now, business=user)
    with open(out, "rb") as fh:
        head = fh.read(8)
    assert head == _PNG
    import os
    assert os.path.getsize(out) > 5000


async def test_dashboard_no_data(store, tmp_path):
    await tx.get_or_create_user(store, UID)
    out = str(tmp_path / "empty.png")
    dashboard.render_dashboard_png(store, UID, out, now=jalali.now())
    with open(out, "rb") as fh:
        assert fh.read(8) == _PNG
