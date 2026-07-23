"""یادآوری روزانه‌ی سررسید طلب و بدهی."""
from __future__ import annotations

from collections import defaultdict

from telegram.ext import ContextTypes

from ..core import jalali, money
from ..db.models import Direction
from ..services import ledger as ledger_service


async def send_due_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    """برای هر کاربر، ردیف‌های سررسیدشده‌ی امروز و معوق را یادآوری می‌کند."""
    factory = context.application.bot_data["session_factory"]
    base = jalali.now()
    session = factory()
    try:
        entries = ledger_service.entries_due_for_reminder(session, base)
        by_user: dict[int, list] = defaultdict(list)
        for entry in entries:
            by_user[entry.user_id].append(entry)

        for user_id, items in by_user.items():
            lines = ["🔔 <b>یادآوری سررسید</b>"]
            for entry in items:
                label = (
                    "طلب از" if entry.direction == Direction.RECEIVABLE else "بدهی به"
                )
                due = (
                    f" (سررسید {jalali.format_date(entry.due_date)})"
                    if entry.due_date
                    else ""
                )
                lines.append(
                    f"• {label} {entry.party_name}: "
                    f"{money.format_amount(entry.amount)}{due}"
                )
            try:
                await context.bot.send_message(
                    chat_id=user_id, text="\n".join(lines), parse_mode="HTML"
                )
            except Exception:
                # اگر کاربر بات را بلاک کرده باشد، بی‌صدا رد می‌شویم.
                continue
    finally:
        session.close()
