"""اتصال خام به Google Sheets و عملیات پایه (با تلاش مجدد).

توابع این ماژول همگی همگام (sync)‌اند؛ لایه‌ی :class:`~hesabyar.db.store.Store`
آن‌ها را با ``asyncio.to_thread`` صدا می‌زند تا حلقه‌ی async بلاک نشود.
"""
from __future__ import annotations

import functools
import json
import time
from typing import Callable

import gspread
from google.oauth2.service_account import Credentials

from .models import ALL_MODELS

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
def ensure_worksheets(spreadsheet) -> None:
    """به‌صورت idempotent هر ۸ تب را (با سطر هدر) در صورت نبود می‌سازد."""
    existing = {ws.title: ws for ws in spreadsheet.worksheets()}
    for model in ALL_MODELS:
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
