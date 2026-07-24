"""ساخت و پیکربندی برنامه‌ی تلگرام (داده روی Google Sheets)."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from telegram import BotCommand
from telegram.ext import Application

from ..config import Settings
from ..core import jalali
from ..db import sheets_client
from ..db.store import Store
from ..services import ocr as ocr_service
from ..services import stt as stt_service
from . import handlers, reminders

logger = logging.getLogger(__name__)


async def _on_startup(application: Application) -> None:
    """اتصال به گوگل‌شیت، بارگذاری داده، و روشن‌کردن نوشتنِ پس‌زمینه."""
    settings: Settings = application.bot_data["settings"]

    delay = 2.0
    last_exc = None
    for attempt in range(5):
        try:
            client = await asyncio.to_thread(sheets_client.get_gspread_client, settings)
            spreadsheet = await asyncio.to_thread(
                sheets_client.open_spreadsheet, client, settings.google_sheet_id
            )
            store = Store(spreadsheet)
            await store.load()
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.error("اتصال به گوگل‌شیت ناموفق (تلاش %s): %s", attempt + 1, exc)
            if attempt < 4:
                await asyncio.sleep(delay)
                delay *= 2
    else:
        logger.critical("اتصال به گوگل‌شیت برقرار نشد؛ خروج. %s", last_exc)
        raise SystemExit(1)

    application.bot_data["store"] = store
    store.start_background_flush(interval=5.0)

    async def _alert(exc, count):
        if count >= 3 and settings.admin_ids:
            for admin_id in settings.admin_ids:
                try:
                    await application.bot.send_message(
                        chat_id=admin_id,
                        text=(
                            "⚠️ اتصال به گوگل‌شیت مشکل دارد و نوشتن داده‌ها "
                            f"{count} بار پشت‌سرهم ناموفق بوده است."
                        ),
                    )
                except Exception:  # noqa: BLE001
                    continue

    store.on_flush_error = _alert

    # منوی دستورات تلگرام (دکمه‌ی «/») برای کشف‌پذیری بهتر.
    try:
        await application.bot.set_my_commands([
            BotCommand("start", "شروع / منوی اصلی"),
            BotCommand("help", "راهنما"),
            BotCommand("list", "تراکنش‌های اخیر"),
            BotCommand("dashboard", "داشبورد تصویری"),
            BotCommand("export", "خروجی اکسل"),
            BotCommand("backup", "پشتیبان کامل"),
            BotCommand("search", "جست‌وجو در تراکنش‌ها"),
            BotCommand("products", "کالاهای من"),
            BotCommand("balance", "وضعیت مالی گروه"),
            BotCommand("undo", "لغو آخرین ثبت"),
            BotCommand("cancel", "لغو"),
        ])
    except Exception:  # noqa: BLE001 - منوی دستورات ضروری نیست
        logger.warning("تنظیم منوی دستورات ناموفق بود.")

    logger.info("Store آماده شد؛ نوشتن پس‌زمینه هر ۵ ثانیه فعال است.")


async def _on_shutdown(application: Application) -> None:
    """قبل از خاموش‌شدن، صف نوشتن را قطعی روی شیت می‌نویسد."""
    store = application.bot_data.get("store")
    if store is not None:
        await store.stop()
        logger.info("صف نوشتن پیش از خاموش‌شدن خالی شد.")


def build_application(settings: Settings) -> Application:
    """اپلیکیشن را می‌سازد؛ اتصال به شیت در ``post_init`` انجام می‌شود."""
    application = (
        Application.builder()
        .token(settings.bot_token)
        .post_init(_on_startup)
        .post_shutdown(_on_shutdown)
        .build()
    )
    application.bot_data["settings"] = settings
    application.bot_data["ocr"] = ocr_service.get_ocr_provider(settings)
    application.bot_data["stt"] = stt_service.get_stt_provider(settings)

    handlers.register(application)

    job_queue = application.job_queue
    if job_queue is not None:
        run_at = dt.time(
            hour=settings.reminder_hour,
            minute=settings.reminder_minute,
            tzinfo=jalali.TEHRAN,
        )
        job_queue.run_daily(
            reminders.send_due_reminders, time=run_at, name="due_reminders"
        )
        if settings.backup_weekly:
            job_queue.run_repeating(
                reminders.weekly_backup,
                interval=dt.timedelta(days=7),
                first=dt.timedelta(hours=1),
                name="weekly_backup",
            )
        if settings.nightly_summary:
            job_queue.run_daily(
                reminders.send_nightly_summary,
                time=dt.time(
                    hour=settings.nightly_summary_hour, tzinfo=jalali.TEHRAN
                ),
                name="nightly_summary",
            )
    else:
        logger.warning(
            "JobQueue در دسترس نیست؛ یادآوری و پشتیبان‌گیری غیرفعال‌اند."
        )

    return application
