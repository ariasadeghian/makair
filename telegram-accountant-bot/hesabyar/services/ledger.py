"""دفتر طلب و بدهی (روی :class:`Store`)."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from ..core import jalali, money
from ..db.models import Direction, Instrument, LedgerEntry
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
    instrument: str = Instrument.CASH,
    cheque_no: str = "",
) -> LedgerEntry:
    await get_or_create_user(store, user_id)
    entry = LedgerEntry(
        user_id=user_id, direction=direction, party_name=party_name,
        amount=int(amount), due_date=due_date, description=description,
        instrument=instrument, cheque_no=cheque_no,
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


def entries_due_for_reminder(
    store: Store, base: dt.datetime, lead_days: int = 0
) -> list[LedgerEntry]:
    """ردیف‌های بازِ سررسیدشده و نزدیک‌به‌سررسید (تا ``lead_days`` روز آینده).

    با ``lead_days=0`` فقط معوق‌ها و سررسیدِ امروز برمی‌گردند (رفتار پیشین).
    خروجی بر اساس تاریخ سررسید مرتب است (نزدیک‌تر اول).
    """
    horizon = base.date() + dt.timedelta(days=max(0, lead_days))
    rows = store.list(
        "ledger_entries",
        lambda e: not e.is_settled
        and e.due_date is not None
        and e.due_date <= horizon,
    )
    return sorted(rows, key=_due_key)


def due_bucket(entry: LedgerEntry, base: dt.datetime) -> str:
    """دسته‌ی یادآوری یک ردیف: ``overdue`` | ``today`` | ``upcoming``."""
    today = base.date()
    if entry.due_date is None or entry.due_date > today:
        return "upcoming"
    if entry.due_date < today:
        return "overdue"
    return "today"


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
        tag = "🧾 چک " if e.is_cheque else ""
        lines.append(
            f"• {tag}{label} {e.party_name}: {money.format_amount(e.amount)}{due}"
        )
    return "\n".join(lines)


def _norm_party(name: str) -> str:
    """نرمال‌سازی نام برای تطبیق (حذف فاصله‌های اضافه و ZWNJ)."""
    return " ".join((name or "").replace("‌", " ").split()).casefold()


def entries_for_party(store: Store, user_id: int, party_name: str) -> list[LedgerEntry]:
    """ردیف‌های بازِ یک طرف‌حساب (تطبیق نامِ نرمال‌شده و شاملِ زیررشته)."""
    target = _norm_party(party_name)
    if not target:
        return []

    def _match(e: LedgerEntry) -> bool:
        if e.user_id != user_id or e.is_settled:
            return False
        name = _norm_party(e.party_name)
        return target in name or name in target

    return sorted(store.list("ledger_entries", _match), key=_due_key)


def find_party_tg_id(store: Store, user_id: int, party_name: str) -> Optional[int]:
    """آیدی تلگرامِ یک طرف‌حساب را از فاکتورهای قبلیِ همان نام پیدا می‌کند.

    وقتی مشتری لینکِ فاکتورش را باز می‌کند آیدی‌اش روی آن فاکتور ثبت می‌شود؛
    این تابع همان را برای «یادآوری بدهی به خودِ مشتری» بازیابی می‌کند.
    """
    target = _norm_party(party_name)
    if not target:
        return None
    for inv in store.list(
        "invoices", lambda i: i.user_id == user_id and i.customer_tg_id
    ):
        name = _norm_party(inv.customer_name)
        if target in name or name in target:
            return int(inv.customer_tg_id)
    return None


def overdue_entries(
    store: Store, user_id: int, base: dt.datetime, min_days: int = 1
) -> list[LedgerEntry]:
    """طلب‌هایی که دست‌کم ``min_days`` روز از سررسیدشان گذشته و تسویه نشده‌اند."""
    cutoff = base.date() - dt.timedelta(days=max(0, min_days))
    rows = store.list(
        "ledger_entries",
        lambda e: e.user_id == user_id
        and not e.is_settled
        and e.direction == Direction.RECEIVABLE
        and e.due_date is not None
        and e.due_date <= cutoff,
    )
    return sorted(rows, key=_due_key)


def build_debtor_notice(entry: LedgerEntry, business=None) -> str:
    """متنِ مؤدبانه‌ی یادآوری بدهی که برای خودِ بدهکار فرستاده می‌شود."""
    who = ""
    if business is not None and getattr(business, "business_name", None):
        who = f" از طرف <b>{business.business_name}</b>"
    due = (
        f"\nسررسید: {jalali.format_date(entry.due_date)}"
        if entry.due_date else ""
    )
    return (
        f"🔔 یادآوری دوستانه{who}\n\n"
        f"مبلغ <b>{money.format_amount(entry.amount)}</b> از حساب شما "
        f"تسویه نشده است.{due}\n\n"
        "اگر پرداخت کرده‌اید این پیام را نادیده بگیرید. 🙏"
    )


def party_statement_data(
    store: Store, user_id: int, party_name: str, business=None
) -> Optional[dict]:
    """داده‌ی ساخت‌یافته‌ی صورتحسابِ یک طرف‌حساب؛ ``None`` اگر ردیفی نباشد.

    منبعِ مشترکِ هم متنِ صورتحساب و هم کارتِ تصویری آن است.
    """
    entries = entries_for_party(store, user_id, party_name)
    if not entries:
        return None

    receivable = sum(
        int(e.amount) for e in entries if e.direction == Direction.RECEIVABLE
    )
    payable = sum(int(e.amount) for e in entries if e.direction == Direction.PAYABLE)
    rows = [
        {
            "label": "طلب از" if e.direction == Direction.RECEIVABLE else "بدهی به",
            "amount": int(e.amount),
            "due_date": e.due_date,
            "is_cheque": e.is_cheque,
        }
        for e in entries
    ]
    return {
        "party": party_name,
        "business_name": getattr(business, "business_name", None) if business else None,
        "date": jalali.now(),
        "entries": rows,
        "receivable": receivable,
        "payable": payable,
        "net": receivable - payable,  # مثبت = او به ما بدهکار است
    }


def build_party_statement(
    store: Store, user_id: int, party_name: str, business=None
) -> Optional[str]:
    """صورتحسابِ متنیِ یک طرف‌حساب برای فوروارد کردن؛ ``None`` اگر ردیفی نباشد."""
    data = party_statement_data(store, user_id, party_name, business)
    if data is None:
        return None

    header = "📄 <b>صورتحساب</b>"
    if data["business_name"]:
        header += f" — {data['business_name']}"
    lines = [header, f"طرف‌حساب: <b>{data['party']}</b>", ""]
    for row in data["entries"]:
        due = (
            f" (سررسید {jalali.format_date(row['due_date'])})"
            if row["due_date"] else ""
        )
        tag = "🧾 چک " if row["is_cheque"] else ""
        lines.append(
            f"• {tag}{row['label']} شما: {money.format_amount(row['amount'])}{due}"
        )
    lines.append("")
    net = data["net"]
    if net > 0:
        lines.append(f"💰 <b>مانده: {money.format_amount(net)} بدهکار</b>")
    elif net < 0:
        lines.append(f"💰 <b>مانده: {money.format_amount(-net)} بستانکار</b>")
    else:
        lines.append("💰 <b>مانده: تسویه</b>")
    lines.append(f"\n🗓 {jalali.format_date(data['date'])}")
    return "\n".join(lines)
