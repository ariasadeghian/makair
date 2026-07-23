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


async def send_due_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    """برای هر کاربر، ردیف‌های سررسیدشده‌ی امروز و معوق را یادآوری می‌کند."""
    store = context.application.bot_data["store"]
    base = jalali.now()
    entries = ledger_service.entries_due_for_reminder(store, base)
    by_user: dict[int, list] = defaultdict(list)
    for entry in entries:
        by_user[entry.user_id].append(entry)

    for user_id, items in by_user.items():
        lines = ["🔔 <b>یادآوری سررسید</b>"]
        for entry in items:
            label = "طلب از" if entry.direction == Direction.RECEIVABLE else "بدهی به"
            due = (
                f" (سررسید {jalali.format_date(entry.due_date)})"
                if entry.due_date else ""
            )
            lines.append(
                f"• {label} {entry.party_name}: {money.format_amount(entry.amount)}{due}"
            )
        try:
            await context.bot.send_message(
                chat_id=user_id, text="\n".join(lines), parse_mode="HTML"
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
