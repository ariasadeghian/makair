"""ساخت و پیکربندی برنامه‌ی تلگرام."""
from __future__ import annotations

import datetime as dt
import logging

from telegram.ext import Application

from ..config import Settings
from ..core import jalali
from ..db.database import init_db, make_engine, make_session_factory
from ..services import ocr as ocr_service
from . import handlers, reminders

logger = logging.getLogger(__name__)


def build_application(settings: Settings) -> Application:
    """موتور دیتابیس، نشست، هندلرها و یادآوری روزانه را سیم‌کشی می‌کند."""
    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)

    application = Application.builder().token(settings.bot_token).build()
    application.bot_data["session_factory"] = session_factory
    application.bot_data["settings"] = settings
    application.bot_data["ocr"] = ocr_service.get_ocr_provider(settings)

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
        logger.info("یادآوری روزانه روی ساعت %s تنظیم شد.", run_at)
    else:
        logger.warning(
            "JobQueue در دسترس نیست؛ یادآوری سررسید غیرفعال است. "
            "برای فعال‌سازی، python-telegram-bot را با اکسترای [job-queue] نصب کنید."
        )

    return application
