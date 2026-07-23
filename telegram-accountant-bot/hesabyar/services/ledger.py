"""دفتر طلب و بدهی (روی :class:`Store`)."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from ..core import jalali, money
from ..db.models import Direction, LedgerEntry
from ..db.store import Store
from .transactions import get_or_create_user


def _due_key(entry: LedgerEntry):
    return (entry.due_date is None, entry.due_date or dt.date.max)


async def add_entry(
    store: Store,
    user_id: int,
    *,
    direction: str,
    party_name: str,
    amount: int,
    due_date: Optional[dt.date] = None,
    description: str = "",
) -> LedgerEntry:
    await get_or_create_user(store, user_id)
    entry = LedgerEntry(
        user_id=user_id, direction=direction, party_name=party_name,
        amount=int(amount), due_date=due_date, description=description,
    )
    await store.add("ledger_entries", entry)
    return entry


def list_open(
    store: Store, user_id: int, direction: Optional[str] = None
) -> list[LedgerEntry]:
    def _match(e: LedgerEntry) -> bool:
        if e.user_id != user_id or e.is_settled:
            return False
        return direction is None or e.direction == direction

    return sorted(store.list("ledger_entries", _match), key=_due_key)


async def settle(
    store: Store, entry_id: int, user_id: int, when: dt.datetime
) -> Optional[LedgerEntry]:
    entry = store.get("ledger_entries", entry_id)
    if entry is None or entry.user_id != user_id:
        return None
    entry.is_settled = True
    entry.settled_at = when
    await store.update("ledger_entries", entry)
    return entry


def totals(store: Store, user_id: int) -> dict:
    receivable = payable = 0
    for e in store.list(
        "ledger_entries", lambda e: e.user_id == user_id and not e.is_settled
    ):
        if e.direction == Direction.RECEIVABLE:
            receivable += int(e.amount)
        else:
            payable += int(e.amount)
    return {"receivable": receivable, "payable": payable, "net": receivable - payable}


def due_within(
    store: Store, user_id: int, days: int, base: dt.datetime
) -> list[LedgerEntry]:
    limit = base.date() + dt.timedelta(days=days)
    rows = store.list(
        "ledger_entries",
        lambda e: e.user_id == user_id and not e.is_settled
        and e.due_date is not None and e.due_date <= limit,
    )
    return sorted(rows, key=_due_key)


def entries_due_for_reminder(store: Store, base: dt.datetime) -> list[LedgerEntry]:
    today = base.date()
    return store.list(
        "ledger_entries",
        lambda e: not e.is_settled and e.due_date is not None and e.due_date <= today,
    )


def build_ledger_report(store: Store, user_id: int) -> str:
    t = totals(store, user_id)
    if t["receivable"] == 0 and t["payable"] == 0:
        return "فعلاً طلب یا بدهی بازی ثبت نشده است."
    lines = [
        "📒 <b>خلاصه‌ی طلب و بدهی</b>",
        f"🟢 مجموع طلب: {money.format_amount(t['receivable'])}",
        f"🔴 مجموع بدهی: {money.format_amount(t['payable'])}",
        f"💰 خالص: {money.format_amount(t['net'])}",
        "",
    ]
    for e in list_open(store, user_id)[:10]:
        label = "طلب از" if e.direction == Direction.RECEIVABLE else "بدهی به"
        due = f" (سررسید {jalali.format_date(e.due_date)})" if e.due_date else ""
        lines.append(f"• {label} {e.party_name}: {money.format_amount(e.amount)}{due}")
    return "\n".join(lines)
