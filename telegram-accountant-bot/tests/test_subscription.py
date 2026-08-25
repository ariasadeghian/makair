import datetime as dt

from hesabyar.core import jalali
from hesabyar.db.models import PaymentStatus
from hesabyar.services import subscription as sub
from hesabyar.services import transactions as tx

UID = 777


def _now():
    return jalali.now()


async def _mk_user(store, uid=UID):
    await tx.get_or_create_user(store, uid)


class TestTrial:
    async def test_new_user_gets_trial(self, store):
        await _mk_user(store)
        s = await sub.get_or_create_subscription(store, UID, now=_now())
        assert s.is_trial is True
        assert sub.is_active(store, UID) is True

    async def test_trial_days_remaining(self, store):
        await _mk_user(store)
        now = _now()
        await sub.get_or_create_subscription(store, UID, now=now, trial_days=14)
        assert sub.days_remaining(store, UID, now=now) == 14

    async def test_idempotent(self, store):
        await _mk_user(store)
        a = await sub.get_or_create_subscription(store, UID)
        b = await sub.get_or_create_subscription(store, UID)
        assert a.id == b.id


class TestExpiry:
    async def test_expired_is_inactive(self, store):
        await _mk_user(store)
        now = _now()
        s = await sub.get_or_create_subscription(store, UID, now=now)
        s.expires_at = now - dt.timedelta(days=1)
        assert sub.is_active(store, UID, now=now) is False
        assert sub.days_remaining(store, UID, now=now) == 0

    async def test_no_subscription_is_inactive(self, store):
        await _mk_user(store)
        assert sub.is_active(store, 999) is False


class TestExtend:
    async def test_extend_from_now_when_expired(self, store):
        await _mk_user(store)
        now = _now()
        s = await sub.get_or_create_subscription(store, UID, now=now)
        s.expires_at = now - dt.timedelta(days=5)
        await sub.extend(store, UID, days=30, plan="monthly", now=now)
        assert sub.is_active(store, UID, now=now) is True
        assert 29 <= sub.days_remaining(store, UID, now=now) <= 30
        s2 = await sub.get_or_create_subscription(store, UID, now=now)
        assert s2.is_trial is False and s2.plan == "monthly"

    async def test_extend_stacks_when_active(self, store):
        await _mk_user(store)
        now = _now()
        await sub.get_or_create_subscription(store, UID, now=now, trial_days=10)
        await sub.extend(store, UID, days=30, plan="monthly", now=now)
        # ۱۰ روز باقی‌مانده + ۳۰ روز ≈ ۴۰
        assert sub.days_remaining(store, UID, now=now) >= 39


class TestPayments:
    async def test_payment_approval_flow(self, store):
        await _mk_user(store)
        now = _now()
        await sub.get_or_create_subscription(store, UID, now=now)
        p = await sub.create_payment(store, UID, plan="monthly", amount=200_000, reference="12345")
        assert p.status == PaymentStatus.PENDING
        assert [x.id for x in sub.pending_payments(store)] == [p.id]

        approved = await sub.approve_payment(store, p.id, admin_id=1, now=now)
        assert approved is not None and approved.status == PaymentStatus.APPROVED
        assert approved.reviewed_by == 1
        assert (await sub.get_or_create_subscription(store, UID)).is_trial is False
        assert sub.pending_payments(store) == []

    async def test_double_approve_is_noop(self, store):
        await _mk_user(store)
        p = await sub.create_payment(store, UID, plan="monthly", amount=200_000)
        assert await sub.approve_payment(store, p.id, admin_id=1) is not None
        assert await sub.approve_payment(store, p.id, admin_id=1) is None

    async def test_reject(self, store):
        await _mk_user(store)
        now = _now()
        await sub.get_or_create_subscription(store, UID, now=now)
        p = await sub.create_payment(store, UID, plan="monthly", amount=200_000)
        rejected = await sub.reject_payment(store, p.id, admin_id=2, now=now)
        assert rejected.status == PaymentStatus.REJECTED
        assert sub.pending_payments(store) == []


class TestStatusText:
    async def test_active_text(self, store):
        await _mk_user(store)
        await sub.get_or_create_subscription(store, UID)
        text = sub.status_text(store, UID)
        assert "فعال" in text

    async def test_expired_text(self, store):
        await _mk_user(store)
        now = _now()
        s = await sub.get_or_create_subscription(store, UID, now=now)
        s.expires_at = now - dt.timedelta(days=1)
        assert "منقضی" in sub.status_text(store, UID, now=now)


class TestFreeLimitArchitecture:
    """معماریِ سقفِ رایگان: فقط محاسبه — هیچ‌جا اجرا/بلاک نمی‌شود (فاز ۱۸)."""

    async def test_usage_this_month_counts_transactions_and_invoices(self, store):
        from hesabyar.db.models import Kind
        from hesabyar.services import invoices as invoice_service
        from hesabyar.services import transactions as tx_service

        await _mk_user(store)
        now = _now()
        await tx_service.add_transaction(
            store, UID, kind=Kind.EXPENSE, amount=1_000,
            category="متفرقه", description="", occurred_at=now,
        )
        await tx_service.add_transaction(
            store, UID, kind=Kind.INCOME, amount=2_000,
            category="فروش", description="", occurred_at=now,
        )
        await invoice_service.create_invoice(
            store, UID, customer_name="علی",
            items=[{"title": "کالا", "quantity": 1, "unit_price": 10_000}],
            issue_date=now.date(),
        )
        # ``now`` را عمداً پاس نمی‌دهیم — created_at با jalali.now()ِ لحظه‌ی
        # ثبت مهر خورده که کمی بعد از ``now``ی بالاست؛ محاسبه هم باید تازه باشد.
        usage = sub.usage_this_month(store, UID)
        assert usage == {"transactions": 2, "invoices": 1}

    async def test_usage_is_zero_for_a_fresh_user(self, store):
        await _mk_user(store)
        assert sub.usage_this_month(store, UID) == {"transactions": 0, "invoices": 0}

    async def test_free_limit_status_flags_when_at_or_over_the_cap(self, store):
        from hesabyar import plans
        from hesabyar.db.models import Kind
        from hesabyar.services import transactions as tx_service

        await _mk_user(store)
        now = _now()
        cap = plans.FREE_LIMITS["max_transactions_per_month"]
        for _ in range(cap):
            await tx_service.add_transaction(
                store, UID, kind=Kind.EXPENSE, amount=1_000,
                category="متفرقه", description="", occurred_at=now,
            )
        status = sub.free_limit_status(store, UID)  # تازه، نه ``now``ی از قبل
        assert status["transactions"]["used"] == cap
        assert status["transactions"]["limit"] == cap
        assert status["transactions"]["exceeded"] is True
        assert status["invoices"]["exceeded"] is False

    async def test_free_limits_are_not_enforced_anywhere(self, store):
        """اسپیریتِ فاز ۱۸: عبور از سقفِ رایگان نباید ثبتِ تراکنش را ببندد."""
        from hesabyar import plans
        from hesabyar.db.models import Kind
        from hesabyar.services import transactions as tx_service

        await _mk_user(store)
        now = _now()
        cap = plans.FREE_LIMITS["max_transactions_per_month"]
        for _ in range(cap + 5):  # از سقف هم رد شد
            await tx_service.add_transaction(
                store, UID, kind=Kind.EXPENSE, amount=1_000,
                category="متفرقه", description="", occurred_at=now,
            )
        assert len(store.list("transactions", lambda t: t.user_id == UID)) == cap + 5
