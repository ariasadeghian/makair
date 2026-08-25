"""دفتر طلب و بدهی (روی :class:`Store`)."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from ..core import jalali, money
from ..db.models import Direction, Instrument, LedgerEntry, RetentionEventKind
from ..db.store import Store
from . import customers, retention
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
    customer_id: Optional[int] = None,
) -> LedgerEntry:
    await get_or_create_user(store, user_id)

    # به رکورد مشتری لینک شود تا صورتحسابِ یک نفر کامل درآید.
    if customer_id is None:
        customer = await customers.find_or_create_customer(
            store, user_id, party_name
        )
        if customer is not None:
            customer_id = customer.id
            party_name = customer.name

    entry = LedgerEntry(
        user_id=user_id, direction=direction, party_name=party_name,
        amount=int(amount), due_date=due_date, description=description,
        instrument=instrument, cheque_no=cheque_no, customer_id=customer_id,
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
    await retention.log_event(
        store, user_id, RetentionEventKind.LEDGER_SETTLED, meta=str(entry_id)
    )
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


def _not_snoozed(entry: LedgerEntry, today: dt.date) -> bool:
    """آیا این ردیف الان اسنوز نیست (یا اسنوزش تمام شده)؟"""
    return entry.snooze_until is None or entry.snooze_until <= today


def due_within(
    store: Store, user_id: int, days: int, base: dt.datetime
) -> list[LedgerEntry]:
    limit = base.date() + dt.timedelta(days=days)
    today = base.date()
    rows = store.list(
        "ledger_entries",
        lambda e: e.user_id == user_id and not e.is_settled
        and e.due_date is not None and e.due_date <= limit
        and _not_snoozed(e, today),
    )
    return sorted(rows, key=_due_key)


def entries_due_for_reminder(
    store: Store, base: dt.datetime, lead_days: int = 0
) -> list[LedgerEntry]:
    """ردیف‌های بازِ سررسیدشده و نزدیک‌به‌سررسید (تا ``lead_days`` روز آینده).

    با ``lead_days=0`` فقط معوق‌ها و سررسیدِ امروز برمی‌گردند (رفتار پیشین).
    ردیفِ اسنوزشده تا وقتی ``snooze_until``ش نرسیده برنمی‌گردد. خروجی بر
    اساس تاریخ سررسید مرتب است (نزدیک‌تر اول).
    """
    horizon = base.date() + dt.timedelta(days=max(0, lead_days))
    today = base.date()
    rows = store.list(
        "ledger_entries",
        lambda e: not e.is_settled
        and e.due_date is not None
        and e.due_date <= horizon
        and _not_snoozed(e, today),
    )
    return sorted(rows, key=_due_key)


def snooze_options(base: dt.datetime) -> dict:
    """سه گزینه‌ی آماده‌ی اسنوز: فردا / ۳ روز دیگر / هفته‌ی بعد."""
    today = base.date()
    return {
        "tomorrow": today + dt.timedelta(days=1),
        "3days": today + dt.timedelta(days=3),
        "week": today + dt.timedelta(days=7),
    }


async def snooze_entry(
    store: Store, user_id: int, entry_id: int, until: dt.date
) -> Optional[LedgerEntry]:
    """این ردیف را تا ``until`` از یادآوریِ خودکار کنار می‌گذارد.

    مبلغ/جهت/سررسید را عوض نمی‌کند — فقط اینکه در یادآوری نشان داده شود یا
    نه. مالکیت چک می‌شود؛ ردیفِ تسویه‌شده یا متعلق‌به‌کسِ‌دیگر ``None`` می‌دهد.
    """
    entry = store.get("ledger_entries", entry_id)
    if entry is None or entry.user_id != user_id or entry.is_settled:
        return None
    entry.snooze_until = until
    await store.update("ledger_entries", entry)
    return entry


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
    """ردیف‌های بازِ یک طرف‌حساب.

    اگر رکورد مشتری وجود داشته باشد، بر اساس ``customer_id`` (دقیق) جمع می‌شود؛
    وگرنه به تطبیقِ نامِ نرمال‌شده برمی‌گردد تا داده‌های قدیمی هم دیده شوند.
    """
    customer = customers.find_customer(store, user_id, party_name)
    if customer is not None:
        by_id = store.list(
            "ledger_entries",
            lambda e: e.user_id == user_id
            and not e.is_settled
            and e.customer_id == customer.id,
        )
        if by_id:
            return sorted(by_id, key=_due_key)

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


def receivable_reminder_buckets(
    store: Store, user_id: int, base: dt.datetime, lead_days: int = 7
) -> dict:
    """طلب‌های بازِ دارایِ سررسید، دسته‌بندی برای «یادآوری به بدهکار».

    خروجی: ``{"overdue": [...], "today": [...], "upcoming": [...]}`` — فقط
    طلب (نه بدهی، چون این برای یادآوری به کسی است که به ما بدهکار است) و
    ``upcoming`` تا ``lead_days`` روز آینده. این جدا از
    :func:`entries_due_for_reminder` است (که خلاصه‌ی داخلیِ صاحب‌کار در
    ``bot.reminders`` را می‌سازد و هر دو جهت را شامل می‌شود).
    """
    rows = due_within(store, user_id, lead_days, base)
    buckets: dict[str, list[LedgerEntry]] = {"overdue": [], "today": [], "upcoming": []}
    for e in rows:
        if e.direction == Direction.RECEIVABLE:
            buckets[due_bucket(e, base)].append(e)
    return buckets


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
    """متنِ مؤدبانه‌ی یادآوری بدهی که برای خودِ بدهکار فرستاده می‌شود.

    خطابِ مستقیم به اسمِ بدهکار — آماده‌ی ارسال، بدون نیاز به ویرایش.
    """
    due = (
        f"\nسررسید: {jalali.format_date(entry.due_date)}"
        if entry.due_date else ""
    )
    who = ""
    if business is not None and getattr(business, "business_name", None):
        who = f"\n\n🏪 از طرف <b>{business.business_name}</b>"
    return (
        f"سلام <b>{entry.party_name}</b> عزیز 👋\n"
        f"یادآوری می‌کنم مبلغ <b>{money.format_amount(entry.amount)}</b> "
        f"بابت حساب شما سررسید شده.{due}{who}\n\n"
        "اگر پرداخت کرده‌اید این پیام را نادیده بگیرید. 🙏"
    )


def party_statement_data(
    store: Store, user_id: int, party_name: str, business=None
) -> Optional[dict]:
    """داده‌ی ساخت‌یافته‌ی صورتحسابِ یک طرف‌حساب؛ ``None`` اگر ردیفی نباشد.

    منبعِ مشترکِ هم متنِ صورتحساب و هم کارتِ تصویری آن است.
    """
    entries = entries_for_party(store, user_id, party_name)
    customer = customers.find_customer(store, user_id, party_name)
    # فاکتورهای همین مشتری (فقط وقتی رکورد مشتری داریم — تطبیق دقیق)
    invoices = []
    if customer is not None:
        invoices = customers.customer_totals(store, user_id, customer.id)["invoices"]
    if not entries and not invoices:
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
        "party": customer.name if customer is not None else party_name,
        "business_name": getattr(business, "business_name", None) if business else None,
        "date": jalali.now(),
        "entries": rows,
        "receivable": receivable,
        "payable": payable,
        "net": receivable - payable,  # مثبت = او به ما بدهکار است
        # فاکتورها جداگانه گزارش می‌شوند و در «مانده» جمع نمی‌شوند تا اگر
        # صاحب‌کار بابت همان فاکتور یک طلب هم ثبت کرده باشد، دوبار حساب نشود.
        "invoices": [
            {"number": i.number, "date": i.issue_date, "total": int(i.total)}
            for i in invoices
        ],
        "invoiced": sum(int(i.total) for i in invoices),
        "paid": sum(int(getattr(i, "paid_amount", 0) or 0) for i in invoices),
    }


def build_customer_quick_card(data: dict) -> str:
    """کارتِ کوتاهِ یک مشتری: نام + خرید کل/پرداخت‌شده/مانده (اگر فاکتور دارد)،
    وگرنه بر پایه‌ی مانده‌ی دفترِ طلب و بدهی.

    ورودی همان چیزی است که :func:`party_statement_data` برمی‌گرداند.
    """
    name = data["party"]
    invoiced = int(data.get("invoiced", 0) or 0)
    if invoiced > 0:
        paid = int(data.get("paid", 0) or 0)
        balance = invoiced - paid
        return (
            f"{name}:\n"
            f"خرید کل: {money.format_amount(invoiced)}\n"
            f"پرداخت شده: {money.format_amount(paid)}\n"
            f"مانده: {money.format_amount(balance)}"
        )
    net = int(data.get("net", 0) or 0)
    if net > 0:
        line = f"بدهکار به شما: {money.format_amount(net)}"
    elif net < 0:
        line = f"بستانکار از شما: {money.format_amount(-net)}"
    else:
        line = "مانده: تسویه"
    return f"{name}:\n{line}"


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

    invoices = data.get("invoices") or []
    if invoices:
        if data["entries"]:
            lines.append("")
        lines.append("🧾 <b>فاکتورهای این مشتری:</b>")
        for inv in invoices[-5:]:
            when = f" — {jalali.format_date(inv['date'])}" if inv["date"] else ""
            lines.append(
                f"• شماره {inv['number']}{when}: {money.format_amount(inv['total'])}"
            )
        lines.append(
            f"جمع فاکتورها: {money.format_amount(data['invoiced'])}"
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
