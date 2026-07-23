import datetime as dt

from hesabyar.core import jalali
from hesabyar.db.models import PaymentStatus
from hesabyar.services import subscription as sub
from hesabyar.services import transactions as tx

UID = 777


def _now():
    return jalali.now()


def _mk_user(session, uid=UID):
    tx.get_or_create_user(session, uid)
    session.commit()


class TestTrial:
    def test_new_user_gets_trial(self, session):
        _mk_user(session)
        s = sub.get_or_create_subscription(session, UID, now=_now())
        assert s.is_trial is True
        assert sub.is_active(session, UID) is True

    def test_trial_days_remaining(self, session):
        _mk_user(session)
        now = _now()
        sub.get_or_create_subscription(session, UID, now=now, trial_days=14)
        assert sub.days_remaining(session, UID, now=now) == 14

    def test_idempotent(self, session):
        _mk_user(session)
        a = sub.get_or_create_subscription(session, UID)
        b = sub.get_or_create_subscription(session, UID)
        assert a.id == b.id


class TestExpiry:
    def test_expired_is_inactive(self, session):
        _mk_user(session)
        now = _now()
        s = sub.get_or_create_subscription(session, UID, now=now)
        s.expires_at = now - dt.timedelta(days=1)
        session.commit()
        assert sub.is_active(session, UID, now=now) is False
        assert sub.days_remaining(session, UID, now=now) == 0

    def test_no_subscription_is_inactive(self, session):
        _mk_user(session)
        assert sub.is_active(session, 999) is False


class TestExtend:
    def test_extend_from_now_when_expired(self, session):
        _mk_user(session)
        now = _now()
        s = sub.get_or_create_subscription(session, UID, now=now)
        s.expires_at = now - dt.timedelta(days=5)
        session.commit()
        sub.extend(session, UID, days=30, plan="monthly", now=now)
        assert sub.is_active(session, UID, now=now) is True
        assert 29 <= sub.days_remaining(session, UID, now=now) <= 30
        s2 = sub.get_or_create_subscription(session, UID, now=now)
        assert s2.is_trial is False and s2.plan == "monthly"

    def test_extend_stacks_when_active(self, session):
        _mk_user(session)
        now = _now()
        sub.get_or_create_subscription(session, UID, now=now, trial_days=10)
        sub.extend(session, UID, days=30, plan="monthly", now=now)
        # ۱۰ روز باقی‌مانده + ۳۰ روز ≈ ۴۰
        assert sub.days_remaining(session, UID, now=now) >= 39


class TestPayments:
    def test_payment_approval_flow(self, session):
        _mk_user(session)
        now = _now()
        sub.get_or_create_subscription(session, UID, now=now)
        p = sub.create_payment(session, UID, plan="monthly", amount=200_000, reference="12345")
        session.commit()
        assert p.status == PaymentStatus.PENDING
        assert [x.id for x in sub.pending_payments(session)] == [p.id]

        approved = sub.approve_payment(session, p.id, admin_id=1, now=now)
        session.commit()
        assert approved is not None and approved.status == PaymentStatus.APPROVED
        assert approved.reviewed_by == 1
        assert sub.get_or_create_subscription(session, UID).is_trial is False
        assert sub.pending_payments(session) == []

    def test_double_approve_is_noop(self, session):
        _mk_user(session)
        p = sub.create_payment(session, UID, plan="monthly", amount=200_000)
        session.commit()
        assert sub.approve_payment(session, p.id, admin_id=1) is not None
        assert sub.approve_payment(session, p.id, admin_id=1) is None

    def test_reject(self, session):
        _mk_user(session)
        now = _now()
        sub.get_or_create_subscription(session, UID, now=now)
        p = sub.create_payment(session, UID, plan="monthly", amount=200_000)
        session.commit()
        rejected = sub.reject_payment(session, p.id, admin_id=2, now=now)
        session.commit()
        assert rejected.status == PaymentStatus.REJECTED
        assert sub.pending_payments(session) == []


class TestStatusText:
    def test_active_text(self, session):
        _mk_user(session)
        text = sub.status_text(session, UID)
        assert "فعال" in text

    def test_expired_text(self, session):
        _mk_user(session)
        now = _now()
        s = sub.get_or_create_subscription(session, UID, now=now)
        s.expires_at = now - dt.timedelta(days=1)
        session.commit()
        assert "منقضی" in sub.status_text(session, UID, now=now)
