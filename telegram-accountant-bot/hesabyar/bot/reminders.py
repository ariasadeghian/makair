"""یادآوری روزانه‌ی سررسید و پشتیبان هفتگی (روی :class:`Store`)."""
from __future__ import annotations

import os
import tempfile
from collections import defaultdict

from telegram.ext import ContextTypes

from ..core import jalali, money
from ..db.models import Direction
from ..services import backup as backup_service
from ..services import ledger as ledger_service
from . import texts


def _entry_line(entry) -> str:
    label = "طلب از" if entry.direction == Direction.RECEIVABLE else "بدهی به"
    return f"• {label} {entry.party_name}: {money.format_amount(entry.amount)}"


def build_reminder_message(items: list, base) -> str:
    """پیام یادآوری را در سه بخش می‌سازد: معوق، امروز، نزدیک.

    اگر ردیفی نباشد رشته‌ی خالی برمی‌گرداند تا پیامی فرستاده نشود.
    """
    today = base.date()
    buckets: dict[str, list] = {"overdue": [], "today": [], "upcoming": []}
    for entry in items:
        buckets[ledger_service.due_bucket(entry, base)].append(entry)

    lines = [texts.REMINDER_HEADER]
    if buckets["overdue"]:
        lines.append("")
        lines.append(texts.REMINDER_OVERDUE_TITLE)
        for e in buckets["overdue"]:
            days = money.to_persian_digits(str((today - e.due_date).days))
            lines.append(
                f"{_entry_line(e)} — {texts.REMINDER_OVERDUE_TAG.format(days=days)}"
                f" (سررسید {jalali.format_date(e.due_date)})"
            )
    if buckets["today"]:
        lines.append("")
        lines.append(texts.REMINDER_TODAY_TITLE)
        for e in buckets["today"]:
            lines.append(f"{_entry_line(e)} — {texts.REMINDER_TODAY_TAG}")
    if buckets["upcoming"]:
        lines.append("")
        lines.append(texts.REMINDER_UPCOMING_TITLE)
        for e in buckets["upcoming"]:
            days = money.to_persian_digits(str((e.due_date - today).days))
            lines.append(
                f"{_entry_line(e)} — {texts.REMINDER_UPCOMING_TAG.format(days=days)}"
                f" (سررسید {jalali.format_date(e.due_date)})"
            )
    if len(lines) <= 1:
        return ""
    return "\n".join(lines)


async def send_due_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    """یادآوری سررسیدها: معوق، سررسیدِ امروز، و نزدیک (چند روز مانده)."""
    store = context.application.bot_data["store"]
    settings = context.application.bot_data.get("settings")
    lead_days = getattr(settings, "reminder_lead_days", 0)
    base = jalali.now()
    entries = ledger_service.entries_due_for_reminder(store, base, lead_days=lead_days)
    by_user: dict[int, list] = defaultdict(list)
    for entry in entries:
        by_user[entry.user_id].append(entry)

    for user_id, items in by_user.items():
        text = build_reminder_message(items, base)
        if not text:
            continue
        try:
            await context.bot.send_message(
                chat_id=user_id, text=text, parse_mode="HTML"
            )
        except Exception:
            continue


async def weekly_backup(context: ContextTypes.DEFAULT_TYPE) -> None:
    """پشتیبان هفتگی: کل اسپردشیت را xlsx می‌کند و برای ادمین‌ها می‌فرستد."""
    settings = context.application.bot_data["settings"]
    if not settings.admin_ids:
        return
    out_path = os.path.join(tempfile.gettempdir(), "hesabyar-backup.xlsx")
    path = backup_service.download_spreadsheet_xlsx(settings, out_path)
    if not path:
        return
    try:
        for admin_id in settings.admin_ids:
            try:
                with open(path, "rb") as fh:
                    await context.bot.send_document(
                        chat_id=admin_id, document=fh,
                        filename="hesabyar-backup.xlsx",
                        caption="📦 پشتیبان هفتگی داده‌ها (اکسل).",
                    )
            except Exception:
                continue
    finally:
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass
