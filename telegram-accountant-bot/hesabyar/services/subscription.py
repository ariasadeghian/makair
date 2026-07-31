"""مدیریت اشتراک و پرداخت (روی :class:`Store`).

خواندن‌ها (is_active/status/…) sync و read-only‌اند؛ تغییردهنده‌ها (ساخت
اشتراک/تمدید/پرداخت) async. زمان‌ها با jalali.now() (aware، تهران).
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from ..core import jalali, money
from ..db.models import Payment, PaymentStatus, Subscription
from ..db.store import Store
from ..plans import TRIAL_DAYS, get_plan, plan_has_feature, tier_label, tier_of


def _as_aware(value: Optional[dt.datetime]) -> Optional[dt.datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=jalali.TEHRAN)
    return value


def _get(store: Store, user_id: int) -> Optional[Subscription]:
    subs = store.list("subscriptions", lambda s: s.user_id == user_id)
    return subs[0] if subs else None


async def get_or_create_subscription(
    store: Store,
    user_id: int,
    now: Optional[dt.datetime] = None,
    trial_days: int = TRIAL_DAYS,
) -> Subscription:
    now = now or jalali.now()
    sub = _get(store, user_id)
    if sub is None:
        sub = Subscription(
            user_id=user_id, plan="trial", is_trial=True,
            expires_at=now + dt.timedelta(days=trial_days),
        )
        await store.add("subscriptions", sub)
    return sub


def is_active(store: Store, user_id: int, now: Optional[dt.datetime] = None) -> bool:
    now = now or jalali.now()
    sub = _get(store, user_id)
    if sub is None or sub.expires_at is None:
        return False
    return _as_aware(sub.expires_at) > now


def days_remaining(store: Store, user_id: int, now: Optional[dt.datetime] = None) -> int:
    now = now or jalali.now()
    sub = _get(store, user_id)
    if sub is None or sub.expires_at is None:
        return 0
    return max(0, (_as_aware(sub.expires_at).date() - now.date()).days)


def status(store: Store, user_id: int, now: Optional[dt.datetime] = None) -> dict:
    """وضعیت اشتراک (read-only). اگر اشتراکی نبود، «منقضی» فرض می‌شود."""
    now = now or jalali.now()
    sub = _get(store, user_id)
    if sub is None or sub.expires_at is None:
        return {
            "active": False, "is_trial": False, "plan": "—",
            "expires_at": now, "days_remaining": 0,
        }
    active = _as_aware(sub.expires_at) > now
    return {
        "active": active, "is_trial": sub.is_trial, "plan": sub.plan,
        "expires_at": sub.expires_at,
        "days_remaining": max(0, (_as_aware(sub.expires_at).date() - now.date()).days),
    }


def status_text(store: Store, user_id: int, now: Optional[dt.datetime] = None) -> str:
    st = status(store, user_id, now)
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


async def extend(
    store: Store,
    user_id: int,
    days: int,
    plan: str,
    now: Optional[dt.datetime] = None,
) -> Subscription:
    now = now or jalali.now()
    sub = await get_or_create_subscription(store, user_id, now)
    current = _as_aware(sub.expires_at)
    start = current if current and current > now else now
    sub.expires_at = start + dt.timedelta(days=days)
    sub.plan = plan
    sub.is_trial = False
    await store.update("subscriptions", sub)
    return sub


def current_tier(store: Store, user_id: int, now: Optional[dt.datetime] = None) -> str:
    """سطحِ فعلیِ کاربر؛ اگر اشتراک فعال نباشد پایین‌ترین سطح."""
    now = now or jalali.now()
    sub = _get(store, user_id)
    if sub is None or not is_active(store, user_id, now):
        return "bronze"
    return tier_of(sub.plan)


def has_feature(
    store: Store, user_id: int, feature: str, now: Optional[dt.datetime] = None
) -> bool:
    """آیا کاربر با اشتراکِ فعلی‌اش به این قابلیت دسترسی دارد؟

    اشتراکِ منقضی مثل سطحِ برنزی رفتار می‌کند (نه قطعِ کامل) تا کاربر همچنان
    بتواند داده‌اش را ببیند.
    """
    now = now or jalali.now()
    sub = _get(store, user_id)
    if sub is None or not is_active(store, user_id, now):
        return plan_has_feature("", feature)  # سطح برنزی
    return plan_has_feature(sub.plan, feature)


def tier_label_for(store: Store, user_id: int) -> str:
    return tier_label(current_tier(store, user_id))


def build_value_recap(store: Store, user_id: int) -> str:
    """خلاصه‌ی ارزشی که کاربر تا امروز از بات گرفته (برای پیام تمدید).

    اگر هنوز چیزی ثبت نکرده باشد رشته‌ی خالی برمی‌گرداند تا پیامِ خالی نفرستیم.
    """
    fa = money.to_persian_digits
    tx_count = len(store.list("transactions", lambda t: t.user_id == user_id))
    inv_count = len(store.list("invoices", lambda i: i.user_id == user_id))
    ledger_count = len(store.list("ledger_entries", lambda e: e.user_id == user_id))
    if not (tx_count or inv_count or ledger_count):
        return ""
    parts = []
    if tx_count:
        parts.append(f"{fa(str(tx_count))} تراکنش")
    if inv_count:
        parts.append(f"{fa(str(inv_count))} فاکتور")
    if ledger_count:
        parts.append(f"{fa(str(ledger_count))} طلب/بدهی")
    return "تا امروز " + "، ".join(parts) + " اینجا ثبت کرده‌ای. 📚"


#: روزهای مانده‌ای که در آن‌ها هشدارِ اتمام می‌فرستیم.
WARN_DAYS = (3, 1)


def subs_needing_notice(
    store: Store, now: Optional[dt.datetime] = None
) -> list[tuple[int, str]]:
    """کاربرانی که امروز باید پیامِ اشتراک بگیرند: ``[(user_id, kind), ...]``.

    ``kind`` یکی از ``"warn3"``، ``"warn1"`` یا ``"expired"`` است. چون job
    روزی یک‌بار اجرا می‌شود، هر حالت برای هر کاربر عملاً یک‌بار رخ می‌دهد
    (منقضی‌شدن فقط در ۲۴ ساعتِ اولِ پس از انقضا گزارش می‌شود).
    """
    now = now or jalali.now()
    notices: list[tuple[int, str]] = []
    for sub in store.list("subscriptions", lambda s: True):
        expires = _as_aware(sub.expires_at)
        if expires is None:
            continue
        if expires > now:
            days = (expires.date() - now.date()).days
            if days in WARN_DAYS:
                notices.append((sub.user_id, f"warn{days}"))
        elif now - expires <= dt.timedelta(hours=24):
            notices.append((sub.user_id, "expired"))
    return notices


# --- پرداخت -------------------------------------------------------------------


async def create_payment(
    store: Store,
    user_id: int,
    plan: str,
    amount: int,
    reference: str = "",
    receipt_file_id: Optional[str] = None,
) -> Payment:
    payment = Payment(
        user_id=user_id, plan=plan, amount=amount, status=PaymentStatus.PENDING,
        reference=reference or "", receipt_file_id=receipt_file_id,
    )
    await store.add("payments", payment)
    return payment


def get_payment(store: Store, payment_id: int) -> Optional[Payment]:
    return store.get("payments", payment_id)


def pending_payments(store: Store) -> list[Payment]:
    rows = store.list("payments", lambda p: p.status == PaymentStatus.PENDING)
    return sorted(rows, key=lambda p: p.id)


async def approve_payment(
    store: Store, payment_id: int, admin_id: int, now: Optional[dt.datetime] = None
) -> Optional[Payment]:
    now = now or jalali.now()
    payment = store.get("payments", payment_id)
    if payment is None or payment.status != PaymentStatus.PENDING:
        return None
    plan = get_plan(payment.plan)
    days = plan["days"] if plan else 30
    await extend(store, payment.user_id, days, payment.plan, now)
    payment.status = PaymentStatus.APPROVED
    payment.reviewed_at = now
    payment.reviewed_by = admin_id
    await store.update("payments", payment)
    return payment


async def reject_payment(
    store: Store, payment_id: int, admin_id: int, now: Optional[dt.datetime] = None
) -> Optional[Payment]:
    now = now or jalali.now()
    payment = store.get("payments", payment_id)
    if payment is None or payment.status != PaymentStatus.PENDING:
        return None
    payment.status = PaymentStatus.REJECTED
    payment.reviewed_at = now
    payment.reviewed_by = admin_id
    await store.update("payments", payment)
    return payment
