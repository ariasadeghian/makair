"""ساخت گزارش‌های متنی فارسی از تراکنش‌ها.

گزارش‌ها متن چندخطیِ آماده برای ارسال در تلگرام‌اند: عنوان دوره، جمع
درآمد و هزینه، مانده با علامت، تعداد تراکنش و چند دسته‌ی برتر هزینه.
"""
from __future__ import annotations

import datetime as dt

from ..core import jalali, money
from ..db.store import Store
from . import ledger, transactions

#: «نزدیکِ سررسید» یعنی تا این تعداد روزِ آینده.
DUE_SOON_DAYS = 2

# نگاشت نام دوره به تابع بازه‌ی متناظر در ماژول jalali.
_BOUNDS = {
    "day": jalali.day_bounds,
    "week": jalali.week_bounds,
    "month": jalali.month_bounds,
}

# برچسب فارسی هر دوره برای عنوان گزارش.
_PERIOD_LABELS = {
    "day": "امروز",
    "week": "این هفته",
    "month": "این ماه",
}

# بیشترین تعداد دسته‌ی هزینه‌ای که در گزارش نمایش داده می‌شود.
_TOP_CATEGORIES = 3


def period_label(period: str) -> str:
    """برچسب فارسی دوره را برمی‌گرداند («امروز»/«این هفته»/«این ماه»)."""
    return _PERIOD_LABELS.get(period, period)


def build_report(
    store: Store, user_id: int, base: dt.datetime, period: str
) -> str:
    """گزارش متنی فارسی برای دوره‌ی خواسته‌شده می‌سازد.

    ``period`` یکی از ``'day'``، ``'week'`` یا ``'month'`` است. بازه با
    ``jalali.*_bounds`` نسبت به ``base`` محاسبه و خلاصه با
    :func:`transactions.summary` گرفته می‌شود.
    """
    bounds_fn = _BOUNDS.get(period, jalali.day_bounds)
    start, end = bounds_fn(base)
    data = transactions.summary(store, user_id, start, end)
    label = period_label(period)

    # عنوان دوره به همراه تاریخ آغاز بازه برای وضوح بیشتر.
    header = f"📊 گزارش {label} ({jalali.format_date_long(start)})"

    if data["count"] == 0:
        return f"{header}\n\nهنوز تراکنشی در این بازه ثبت نشده است. 📭"

    income = data["income"]
    expense = data["expense"]
    balance = data["balance"]
    # علامت مانده: سبز برای مثبت/صفر، قرمز برای منفی.
    balance_emoji = "🟢" if balance >= 0 else "🔴"

    lines: list[str] = [
        header,
        "",
        f"💰 درآمد: {money.format_amount(income)}",
        f"💸 هزینه: {money.format_amount(expense)}",
        f"{balance_emoji} مانده: {money.format_amount(balance)}",
        f"🧾 تعداد تراکنش: {money.to_persian_digits(str(data['count']))}",
    ]

    # چند دسته‌ی برتر هزینه بر اساس مبلغ، نزولی.
    top_expenses = sorted(
        data["expense_by_category"].items(), key=lambda item: item[1], reverse=True
    )[:_TOP_CATEGORIES]
    if top_expenses:
        lines.append("")
        lines.append("🏷 بیشترین هزینه‌ها:")
        for rank, (category, amount) in enumerate(top_expenses, start=1):
            rank_fa = money.to_persian_digits(str(rank))
            lines.append(f"{rank_fa}. {category}: {money.format_amount(amount)}")

    return "\n".join(lines)


def _created_today(store: Store, table: str, user_id: int, start, end) -> int:
    """تعداد ردیف‌هایی از یک جدول که امروز ساخته شده‌اند."""
    return len(store.list(
        table,
        lambda row: row.user_id == user_id and row.created_at is not None
        and start <= row.created_at <= end,
    ))


def daily_activity(store: Store, user_id: int, now: dt.datetime) -> dict:
    """آمارِ «امروز»ِ یک کاربر — پایه‌ی خلاصه‌ی شبانه.

    «فعالیت» فقط تراکنش نیست: صدور فاکتور و ثبتِ طلب/بدهی هم روزِ کاری را
    فعال می‌کند، وگرنه کسی که امروز فقط فاکتور زده هیچ خلاصه‌ای نمی‌گرفت.
    """
    start, end = jalali.day_bounds(now)
    data = transactions.summary(store, user_id, start, end)
    invoices = _created_today(store, "invoices", user_id, start, end)
    entries = _created_today(store, "ledger_entries", user_id, start, end)
    return {
        **data,
        "start": start,
        "invoices": invoices,
        "ledger_entries": entries,
        "due_soon": len(ledger.due_within(store, user_id, DUE_SOON_DAYS, now)),
        "active": bool(data["count"] or invoices or entries),
    }


def build_daily_digest(
    store: Store, user_id: int, now: dt.datetime
) -> str | None:
    """خلاصه‌ی فعالیت مالیِ «امروز»؛ ``None`` اگر امروز چیزی ثبت نشده باشد.

    برای پیام خودکار شبانه استفاده می‌شود؛ کاربرانِ بدون فعالیتِ امروز پیامی
    نمی‌گیرند تا مزاحمت ایجاد نشود.
    """
    stats = daily_activity(store, user_id, now)
    if not stats["active"]:
        return None

    balance = stats["balance"]
    balance_emoji = "🟢" if balance >= 0 else "🔴"
    lines = [
        f"🌙 <b>خلاصه‌ی امروز</b> ({jalali.format_date(stats['start'])})",
        "",
        f"💰 درآمد: {money.format_amount(stats['income'])}",
        f"💸 هزینه: {money.format_amount(stats['expense'])}",
        f"{balance_emoji} مانده‌ی امروز: {money.format_amount(balance)}",
        f"🧾 {money.to_persian_digits(str(stats['count']))} تراکنش",
    ]
    if stats["invoices"]:
        lines.append(
            f"📄 {money.to_persian_digits(str(stats['invoices']))} فاکتور صادر شد"
        )
    if stats["ledger_entries"]:
        lines.append(
            f"📒 {money.to_persian_digits(str(stats['ledger_entries']))} ثبت در دفتر"
        )
    if stats["due_soon"]:
        lines.append("")
        lines.append(
            f"⏰ {money.to_persian_digits(str(stats['due_soon']))} مورد نزدیکِ سررسید "
            f"(تا {money.to_persian_digits(str(DUE_SOON_DAYS))} روز آینده)"
        )
    return "\n".join(lines)
