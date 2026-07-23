"""سرویس دفتر بدهکار/بستانکار (طلب و بدهی).

این ماژول منطق تجاری ثبت و پیگیری «طلب‌های من» و «بدهی‌های من» را فراهم
می‌کند. هر ردیف یک :class:`~hesabyar.db.models.LedgerEntry` است که می‌تواند
سررسید (``due_date``) داشته باشد و در زمان پرداخت «تسویه» می‌شود.

قواعد مشترک پروژه:

* همه‌ی مبالغ عدد صحیح و به «تومان» هستند.
* زمان‌ها aware و در منطقه‌ی تهران‌اند (``jalali.now()`` / ``jalali.TEHRAN``).
* ``due_date`` یک :class:`datetime.date` (بدون زمان) است.
* رشته‌های نمایشی فارسی‌اند؛ مبالغ با ``money.format_amount`` و تاریخ‌ها با
  ``jalali.format_date`` قالب می‌شوند.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import jalali, money
from ..db.models import Direction, LedgerEntry
from .transactions import get_or_create_user

# بیشترین تعداد ردیف باز که در گزارش متنی نمایش داده می‌شود.
_MAX_REPORT_ROWS = 10


def add_entry(
    session: Session,
    user_id: int,
    *,
    direction: str,
    party_name: str,
    amount: int,
    due_date: dt.date | None = None,
    description: str = "",
) -> LedgerEntry:
    """یک ردیف تازه در دفتر بدهکار/بستانکار ثبت می‌کند.

    ``direction`` باید یکی از مقادیر :class:`~hesabyar.db.models.Direction`
    باشد (``RECEIVABLE`` برای طلب من، ``PAYABLE`` برای بدهی من). ``amount``
    مبلغ مثبت به تومان و ``due_date`` سررسید اختیاری است. شیء ذخیره‌شده
    برگردانده می‌شود.
    """
    # اطمینان از وجود کاربر برای رعایت کلید خارجی.
    get_or_create_user(session, user_id)
    entry = LedgerEntry(
        user_id=user_id,
        direction=direction,
        party_name=party_name,
        amount=int(amount),
        due_date=due_date,
        description=description,
    )
    session.add(entry)
    session.commit()
    return entry


def _order_open(stmt):
    """مرتب‌سازی مشترک ردیف‌های باز بر اساس سررسید.

    ردیف‌های دارای سررسید ابتدا (صعودی) و ردیف‌های بدون سررسید (``None``)
    در انتها می‌آیند؛ برای پایداری، ``id`` معیار دوم است.
    """
    # ``due_date IS NULL`` در SQLite مقدار ۰/۱ می‌دهد؛ پس ردیف‌های
    # بدون سررسید (۱) بعد از ردیف‌های دارای سررسید (۰) قرار می‌گیرند.
    return stmt.order_by(
        LedgerEntry.due_date.is_(None),
        LedgerEntry.due_date.asc(),
        LedgerEntry.id.asc(),
    )


def list_open(
    session: Session, user_id: int, direction: str | None = None
) -> list[LedgerEntry]:
    """فهرست ردیف‌های تسویه‌نشده‌ی کاربر.

    اگر ``direction`` داده شود فقط ردیف‌های همان جهت برمی‌گردند. خروجی بر
    اساس سررسید صعودی مرتب است و ردیف‌های بدون سررسید در انتها می‌آیند.
    """
    stmt = (
        select(LedgerEntry)
        .where(LedgerEntry.user_id == user_id)
        .where(LedgerEntry.is_settled.is_(False))
    )
    if direction is not None:
        stmt = stmt.where(LedgerEntry.direction == direction)
    stmt = _order_open(stmt)
    return list(session.execute(stmt).scalars().all())


def settle(
    session: Session, entry_id: int, user_id: int, when: dt.datetime
) -> LedgerEntry | None:
    """یک ردیف را تسویه‌شده علامت می‌زند.

    ``is_settled`` را ``True`` و ``settled_at`` را برابر ``when`` (زمان
    aware تسویه) می‌کند و شیء به‌روزشده را برمی‌گرداند. اگر ردیف موجود
    نبود یا متعلق به همین کاربر نبود، ``None`` برگردانده می‌شود.
    """
    entry = session.get(LedgerEntry, entry_id)
    if entry is None or entry.user_id != user_id:
        return None
    entry.is_settled = True
    entry.settled_at = when
    session.commit()
    return entry


def totals(session: Session, user_id: int) -> dict:
    """جمع طلب‌ها و بدهی‌های باز کاربر و خالص آن‌ها.

    ساختار خروجی::

        {
            'receivable': int,   # جمع طلب‌های تسویه‌نشده
            'payable': int,      # جمع بدهی‌های تسویه‌نشده
            'net': int,          # receivable منهای payable
        }
    """
    receivable = 0
    payable = 0
    for entry in list_open(session, user_id):
        amount = int(entry.amount)
        if entry.direction == Direction.RECEIVABLE:
            receivable += amount
        else:
            payable += amount
    return {
        "receivable": receivable,
        "payable": payable,
        "net": receivable - payable,
    }


def due_within(
    session: Session, user_id: int, days: int, base: dt.datetime
) -> list[LedgerEntry]:
    """ردیف‌های باز کاربر که تا ``days`` روز آینده سررسید می‌شوند.

    آستانه برابر ``base.date() + days`` است و ردیف‌هایی که سررسیدشان
    کوچک‌تر یا مساوی این آستانه باشد (شامل ردیف‌های معوقِ گذشته)
    برمی‌گردند. ردیف‌های بدون سررسید در این فهرست نمی‌آیند. خروجی بر
    اساس سررسید صعودی مرتب است.
    """
    threshold = base.date() + dt.timedelta(days=days)
    stmt = (
        select(LedgerEntry)
        .where(LedgerEntry.user_id == user_id)
        .where(LedgerEntry.is_settled.is_(False))
        .where(LedgerEntry.due_date.is_not(None))
        .where(LedgerEntry.due_date <= threshold)
    )
    stmt = _order_open(stmt)
    return list(session.execute(stmt).scalars().all())


def entries_due_for_reminder(
    session: Session, base: dt.datetime
) -> list[LedgerEntry]:
    """ردیف‌های باز همه‌ی کاربران که سررسیدشان رسیده است.

    برای صف یادآوری استفاده می‌شود: هر ردیف تسویه‌نشده با سررسیدِ کوچک‌تر
    یا مساوی ``base.date()`` (یعنی امروز و معوق‌ها) روی همه‌ی کاربران.
    خروجی بر اساس سررسید صعودی مرتب است.
    """
    today = base.date()
    stmt = (
        select(LedgerEntry)
        .where(LedgerEntry.is_settled.is_(False))
        .where(LedgerEntry.due_date.is_not(None))
        .where(LedgerEntry.due_date <= today)
    )
    stmt = _order_open(stmt)
    return list(session.execute(stmt).scalars().all())


def _direction_label(direction: str) -> str:
    """برچسب فارسی جهت ردیف را برمی‌گرداند."""
    return "طلب" if direction == Direction.RECEIVABLE else "بدهی"


def build_ledger_report(session: Session, user_id: int) -> str:
    """گزارش متنی فارسی از وضعیت دفتر بدهکار/بستانکار کاربر می‌سازد.

    شامل جمع طلب، جمع بدهی، خالص، و فهرست چند ردیف بازِ نخست با نام
    طرف‌حساب، مبلغ و سررسید (شمسی). متن چندخطیِ آماده برای ارسال در
    تلگرام است.
    """
    data = totals(session, user_id)
    net = data["net"]
    # خالص مثبت یعنی در مجموع بستانکاریم، منفی یعنی بدهکار.
    net_emoji = "🟢" if net >= 0 else "🔴"

    lines: list[str] = [
        "📒 دفتر طلب و بدهی",
        "",
        f"💚 جمع طلب من: {money.format_amount(data['receivable'])}",
        f"❤️ جمع بدهی من: {money.format_amount(data['payable'])}",
        f"{net_emoji} خالص: {money.format_amount(net)}",
    ]

    open_entries = list_open(session, user_id)
    if not open_entries:
        lines.append("")
        lines.append("هیچ ردیف بازی ثبت نشده است. ✅")
        return "\n".join(lines)

    lines.append("")
    lines.append("🗂 ردیف‌های باز:")
    for entry in open_entries[:_MAX_REPORT_ROWS]:
        label = _direction_label(entry.direction)
        amount_text = money.format_amount(int(entry.amount))
        if entry.due_date is not None:
            due_text = f"سررسید {jalali.format_date(entry.due_date)}"
        else:
            due_text = "بدون سررسید"
        lines.append(f"• {label} | {entry.party_name}: {amount_text} ({due_text})")

    remaining = len(open_entries) - _MAX_REPORT_ROWS
    if remaining > 0:
        remaining_fa = money.to_persian_digits(str(remaining))
        lines.append(f"… و {remaining_fa} ردیف دیگر")

    return "\n".join(lines)
