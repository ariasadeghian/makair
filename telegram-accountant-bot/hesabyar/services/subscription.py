"""مدیریت اشتراک و پرداخت کارت‌به‌کارت.

هر کاربر یک ردیف :class:`Subscription` دارد. کاربر جدید یک دوره‌ی آزمایشی
رایگان می‌گیرد. تمدید از راه ثبت :class:`Payment` و تأیید مدیر انجام می‌شود.

نکته‌ی زمان: SQLite منطقه‌ی زمانی را ذخیره نمی‌کند، پس مقادیر خوانده‌شده
«ساعت دیواری تهران» و بدون tzinfo هستند؛ برای مقایسه‌ی پایتونی دوباره
tzinfo تهران را می‌چسبانیم (:func:`_as_aware`).
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import jalali, money
from ..db.models import Payment, PaymentStatus, Subscription
from ..plans import PLANS, TRIAL_DAYS, get_plan


def _as_aware(value: Optional[dt.datetime]) -> Optional[dt.datetime]:
    """اگر مقدار بدون منطقه‌ی زمانی بود، منطقه‌ی تهران را به آن می‌چسباند."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=jalali.TEHRAN)
    return value


def _get(session: Session, user_id: int) -> Optional[Subscription]:
    return session.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    ).scalar_one_or_none()


def get_or_create_subscription(
    session: Session,
    user_id: int,
    now: Optional[dt.datetime] = None,
    trial_days: int = TRIAL_DAYS,
) -> Subscription:
    """اشتراک کاربر را برمی‌گرداند؛ اگر نبود یک دوره‌ی آزمایشی می‌سازد."""
    now = now or jalali.now()
    sub = _get(session, user_id)
    if sub is None:
        sub = Subscription(
            user_id=user_id,
            plan="trial",
            is_trial=True,
            expires_at=now + dt.timedelta(days=trial_days),
        )
        session.add(sub)
        session.flush()
    return sub


def is_active(session: Session, user_id: int, now: Optional[dt.datetime] = None) -> bool:
    """آیا اشتراک کاربر هنوز معتبر است؟"""
    now = now or jalali.now()
    sub = _get(session, user_id)
    if sub is None:
        return False
    return _as_aware(sub.expires_at) > now


def days_remaining(
    session: Session, user_id: int, now: Optional[dt.datetime] = None
) -> int:
    now = now or jalali.now()
    sub = _get(session, user_id)
    if sub is None:
        return 0
    delta = (_as_aware(sub.expires_at).date() - now.date()).days
    return max(0, delta)


def status(
    session: Session, user_id: int, now: Optional[dt.datetime] = None
) -> dict:
    """خلاصه‌ی وضعیت اشتراک به‌صورت دیکشنری."""
    now = now or jalali.now()
    sub = get_or_create_subscription(session, user_id, now)
    active = _as_aware(sub.expires_at) > now
    return {
        "active": active,
        "is_trial": sub.is_trial,
        "plan": sub.plan,
        "expires_at": sub.expires_at,
        "days_remaining": max(0, (_as_aware(sub.expires_at).date() - now.date()).days),
    }


def status_text(
    session: Session, user_id: int, now: Optional[dt.datetime] = None
) -> str:
    """متن فارسی وضعیت اشتراک."""
    st = status(session, user_id, now)
    expires = jalali.format_date(st["expires_at"])
    days = money.to_persian_digits(str(st["days_remaining"]))
    if st["active"]:
        if st["is_trial"]:
            kind = "آزمایشی رایگان 🎁"
        else:
            plan = get_plan(st["plan"])
            kind = plan["label"] if plan else st["plan"]
        return (
            "وضعیت اشتراک: <b>فعال</b> ✅\n"
            f"نوع: {kind}\n"
            f"اعتبار تا: {expires}\n"
            f"{days} روز باقی مانده."
        )
    return (
        "وضعیت اشتراک: <b>منقضی</b> ❌\n"
        f"اعتبار در {expires} به پایان رسید.\n"
        "برای ادامه‌ی استفاده، یکی از پلن‌ها را تهیه کنید."
    )


def extend(
    session: Session,
    user_id: int,
    days: int,
    plan: str,
    now: Optional[dt.datetime] = None,
) -> Subscription:
    """اشتراک را به اندازه‌ی ``days`` روز تمدید می‌کند.

    اگر هنوز اعتبار داشته باشد، روزها روی اعتبار فعلی افزوده می‌شوند؛ در غیر
    این صورت از اکنون محاسبه می‌شود.
    """
    now = now or jalali.now()
    sub = get_or_create_subscription(session, user_id, now)
    current = _as_aware(sub.expires_at)
    start = current if current > now else now
    sub.expires_at = start + dt.timedelta(days=days)
    sub.plan = plan
    sub.is_trial = False
    session.flush()
    return sub


# --- پرداخت -------------------------------------------------------------------


def create_payment(
    session: Session,
    user_id: int,
    plan: str,
    amount: int,
    reference: str = "",
    receipt_file_id: Optional[str] = None,
) -> Payment:
    payment = Payment(
        user_id=user_id,
        plan=plan,
        amount=amount,
        status=PaymentStatus.PENDING,
        reference=reference or "",
        receipt_file_id=receipt_file_id,
    )
    session.add(payment)
    session.flush()
    return payment


def get_payment(session: Session, payment_id: int) -> Optional[Payment]:
    return session.get(Payment, payment_id)


def pending_payments(session: Session) -> list[Payment]:
    return list(
        session.execute(
            select(Payment)
            .where(Payment.status == PaymentStatus.PENDING)
            .order_by(Payment.created_at)
        ).scalars()
    )


def approve_payment(
    session: Session,
    payment_id: int,
    admin_id: int,
    now: Optional[dt.datetime] = None,
) -> Optional[Payment]:
    """پرداخت را تأیید و اشتراک را بر اساس پلن تمدید می‌کند.

    فقط روی پرداخت‌های «در انتظار» اثر می‌گذارد (جلوگیری از تأیید دوباره).
    """
    now = now or jalali.now()
    payment = session.get(Payment, payment_id)
    if payment is None or payment.status != PaymentStatus.PENDING:
        return None
    plan = get_plan(payment.plan)
    days = plan["days"] if plan else 30
    extend(session, payment.user_id, days, payment.plan, now)
    payment.status = PaymentStatus.APPROVED
    payment.reviewed_at = now
    payment.reviewed_by = admin_id
    session.flush()
    return payment


def reject_payment(
    session: Session,
    payment_id: int,
    admin_id: int,
    now: Optional[dt.datetime] = None,
) -> Optional[Payment]:
    now = now or jalali.now()
    payment = session.get(Payment, payment_id)
    if payment is None or payment.status != PaymentStatus.PENDING:
        return None
    payment.status = PaymentStatus.REJECTED
    payment.reviewed_at = now
    payment.reviewed_by = admin_id
    session.flush()
    return payment
