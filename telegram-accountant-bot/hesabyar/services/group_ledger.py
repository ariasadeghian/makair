"""دفتر مالی گروه: درخواست‌های پرداخت و پرداخت‌ها بین اعضای یک گروه.

روی همان لایه‌ی :class:`Store` سوار است؛ هر رویداد یک ردیف در تب
``group_events`` است و به یک ``chat_id`` (گروه) تعلق دارد.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from ..core import jalali, money
from ..db.models import GroupEvent, GroupEventKind, GroupEventStatus
from ..db.store import Store

#: مبنای مرتب‌سازی برای رویدادهای بدون created_at (نباید رخ دهد ولی محض احتیاط).
_EPOCH = dt.datetime(1970, 1, 1, tzinfo=jalali.TEHRAN)


def _created(e: GroupEvent) -> dt.datetime:
    return e.created_at or _EPOCH


async def add_request(
    store: Store,
    chat_id: int,
    *,
    requester_id: int,
    requester_name: str,
    payer_id: Optional[int],
    payer_name: str,
    amount: int,
    reason: str = "",
) -> GroupEvent:
    """ثبت یک «درخواست پرداخت» باز (الف از ب می‌خواهد بپردازد)."""
    event = GroupEvent(
        chat_id=chat_id,
        kind=GroupEventKind.REQUEST,
        actor_id=requester_id,
        actor_name=requester_name,
        counterparty_id=payer_id,
        counterparty_name=payer_name,
        amount=int(amount or 0),
        reason=reason,
        status=GroupEventStatus.OPEN,
    )
    await store.add("group_events", event)
    return event


async def add_payment(
    store: Store,
    chat_id: int,
    *,
    payer_id: int,
    payer_name: str,
    payee_id: Optional[int] = None,
    payee_name: str = "",
    amount: int,
    reason: str = "",
    request_id: Optional[int] = None,
    when: Optional[dt.datetime] = None,
) -> GroupEvent:
    """ثبت یک «پرداخت». اگر ``request_id`` بدهیم، آن درخواست تسویه می‌شود."""
    event = GroupEvent(
        chat_id=chat_id,
        kind=GroupEventKind.PAYMENT,
        actor_id=payer_id,
        actor_name=payer_name,
        counterparty_id=payee_id,
        counterparty_name=payee_name,
        amount=int(amount or 0),
        reason=reason,
        status=GroupEventStatus.SETTLED if request_id else GroupEventStatus.LOGGED,
        request_id=request_id,
    )
    await store.add("group_events", event)
    if request_id:
        await settle_request(store, request_id, chat_id, when or jalali.now())
    return event


async def settle_request(
    store: Store, request_id: int, chat_id: int, when: dt.datetime
) -> Optional[GroupEvent]:
    """یک درخواست را تسویه‌شده علامت می‌زند (اگر متعلق به همین گروه باشد)."""
    req = store.get("group_events", request_id)
    if req is None or req.chat_id != chat_id or req.kind != GroupEventKind.REQUEST:
        return None
    req.status = GroupEventStatus.SETTLED
    req.settled_at = when
    await store.update("group_events", req)
    return req


def open_requests(store: Store, chat_id: int) -> list[GroupEvent]:
    """درخواست‌های پرداختِ بازِ گروه (قدیمی‌تر اول)."""
    rows = store.list(
        "group_events",
        lambda e: e.chat_id == chat_id
        and e.kind == GroupEventKind.REQUEST
        and e.status == GroupEventStatus.OPEN,
    )
    return sorted(rows, key=_created)


def recent_payments(store: Store, chat_id: int, limit: int = 10) -> list[GroupEvent]:
    """پرداخت‌های اخیر گروه (جدیدترین اول)."""
    rows = store.list(
        "group_events",
        lambda e: e.chat_id == chat_id and e.kind == GroupEventKind.PAYMENT,
    )
    return sorted(rows, key=_created, reverse=True)[:limit]


def find_open_request_for(
    store: Store, chat_id: int, payer_id: int, amount: Optional[int] = None
) -> Optional[GroupEvent]:
    """جدیدترین درخواستِ بازی که این شخص باید بپردازد (اختیاراً با همان مبلغ)."""
    def _match(e: GroupEvent) -> bool:
        return (
            e.chat_id == chat_id
            and e.kind == GroupEventKind.REQUEST
            and e.status == GroupEventStatus.OPEN
            and e.counterparty_id == payer_id
            and (amount is None or int(e.amount) == int(amount))
        )

    rows = sorted(store.list("group_events", _match), key=_created, reverse=True)
    return rows[0] if rows else None


def totals(store: Store, chat_id: int) -> dict:
    """جمع مبلغِ درخواست‌های باز و پرداخت‌های ثبت‌شده‌ی گروه."""
    open_sum = sum(int(e.amount) for e in open_requests(store, chat_id))
    paid_sum = sum(
        int(e.amount)
        for e in store.list(
            "group_events",
            lambda e: e.chat_id == chat_id and e.kind == GroupEventKind.PAYMENT,
        )
    )
    return {"open": open_sum, "paid": paid_sum}


def build_group_report(store: Store, chat_id: int) -> str:
    """گزارش وضعیت مالی گروه: درخواست‌های باز + پرداخت‌های اخیر."""
    reqs = open_requests(store, chat_id)
    pays = recent_payments(store, chat_id, limit=8)
    if not reqs and not pays:
        return "فعلاً رویداد مالی‌ای در این گروه ثبت نشده است. 📭"

    lines = ["🧾 <b>وضعیت مالی گروه</b>"]
    if reqs:
        total = sum(int(e.amount) for e in reqs)
        lines.append("")
        lines.append(f"⏳ <b>درخواست‌های باز</b> (جمع: {money.format_amount(total)}):")
        for e in reqs:
            reason = f" بابت {e.reason}" if e.reason else ""
            payer = e.counterparty_name or "—"
            lines.append(
                f"• {e.actor_name} از {payer}: "
                f"{money.format_amount(e.amount)}{reason}"
            )
    if pays:
        lines.append("")
        lines.append("✅ <b>پرداخت‌های اخیر</b>:")
        for e in pays:
            to = f" به {e.counterparty_name}" if e.counterparty_name else ""
            reason = f" بابت {e.reason}" if e.reason else ""
            lines.append(
                f"• {e.actor_name}{to}: {money.format_amount(e.amount)}{reason}"
            )
    return "\n".join(lines)
