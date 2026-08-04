"""اتصال خام به Google Sheets و عملیات پایه (با تلاش مجدد).

توابع این ماژول همگی همگام (sync)‌اند؛ لایه‌ی :class:`~hesabyar.db.store.Store`
آن‌ها را با ``asyncio.to_thread`` صدا می‌زند تا حلقه‌ی async بلاک نشود.
"""
from __future__ import annotations

import functools
import json
import logging
import time
from typing import Callable, Optional, Sequence

import gspread
from google.oauth2.service_account import Credentials

from .models import ALL_MODELS

logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_RETRY_STATUS = {429, 500, 502, 503}


def get_gspread_client(settings) -> gspread.Client:
    """کلاینت gspread را از روی رشته‌ی JSON کلید سرویس‌اکانت می‌سازد."""
    info = json.loads(settings.google_service_account_json)
    creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
    return gspread.authorize(creds)


def open_spreadsheet(client: gspread.Client, sheet_id: str):
    return client.open_by_key(sheet_id)


def with_retry(fn: Callable) -> Callable:
    """در برابر خطاهای موقتی گوگل (429/5xx) با backoff نمایی تلاش می‌کند."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        delay = 1.0
        last_exc = None
        for attempt in range(5):
            try:
                return fn(*args, **kwargs)
            except gspread.exceptions.APIError as exc:
                last_exc = exc
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status in _RETRY_STATUS and attempt < 4:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise
        if last_exc:
            raise last_exc

    return wrapper


@with_retry
def create_user_spreadsheet(
    client: gspread.Client, title: str, folder_id: Optional[str] = None
) -> str:
    """یک اسپردشیت تازه برای یک کاربر می‌سازد و شناسه‌اش را برمی‌گرداند.

    اگر ``folder_id`` بدهیم، فایل داخل همان پوشه‌ی Drive ساخته می‌شود. این
    حالت توصیه‌شده است: سرویس‌اکانت به‌تنهایی کوتای Drive ندارد، پس باید در
    پوشه‌ای بسازد که مالکش یک اکانت واقعی است و به سرویس‌اکانت Editor داده.
    """
    if folder_id:
        spreadsheet = client.create(title, folder_id=folder_id)
    else:
        logger.warning(
            "DRIVE_PARENT_FOLDER_ID تنظیم نشده؛ ساخت اسپردشیت ممکن است با "
            "خطای کوتای Drive شکست بخورد."
        )
        spreadsheet = client.create(title)
    return spreadsheet.id


@with_retry
def ensure_worksheets(spreadsheet, models: Optional[Sequence] = None) -> None:
    """به‌صورت idempotent تب‌های خواسته‌شده را (با سطر هدر) می‌سازد.

    ``models`` را می‌دهیم تا اسپردشیت مرکزی فقط تب‌های رجیستری و اسپردشیت هر
    کاربر فقط تب‌های دفترِ خودش را داشته باشد. پیش‌فرض: همه‌ی مدل‌ها.
    """
    for model in (models if models is not None else ALL_MODELS):
        existing = {ws.title: ws for ws in spreadsheet.worksheets()}
        header = list(model.COLUMNS)
        if model.TABLE not in existing:
            ws = spreadsheet.add_worksheet(
                title=model.TABLE, rows=200, cols=max(len(header), 1)
            )
            ws.append_row(header)
        elif not existing[model.TABLE].get_all_values():
            existing[model.TABLE].append_row(header)


@with_retry
def read_all_records(ws) -> list[dict]:
    """همه‌ی ردیف‌های داده را به‌صورت فهرست دیکشنری (هدر→مقدار) برمی‌گرداند."""
    return ws.get_all_records()


@with_retry
def overwrite_worksheet(ws, header: list, rows: list) -> None:
    """کلِ یک تب را بازنویسی می‌کند (هدر + ردیف‌ها).

    ساده، idempotent و safe-to-retry: به‌جای به‌روزرسانی ردیف‌به‌ردیف، کل تب
    از روی حافظه دوباره نوشته می‌شود.
    """
    ws.clear()
    ws.update([header] + rows, value_input_option="RAW")
