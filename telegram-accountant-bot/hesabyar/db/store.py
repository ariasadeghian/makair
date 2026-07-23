"""لایه‌ی داده‌ی در حافظه روی Google Sheets.

کل داده هنگام بالا آمدن از شیت خوانده و در حافظه نگه‌داری می‌شود؛ همه‌ی
خواندن‌ها روی حافظه (سریع، بدون Rate Limit) و هر نوشتن هم در حافظه اعمال و هم
برای نوشتنِ دسته‌ای روی شیت صف می‌شود. هر جدول یک ``asyncio.Lock`` جدا دارد.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from ..core import jalali
from . import sheets_client as sheets
from .models import TABLE_MODELS

logger = logging.getLogger(__name__)


class Store:
    def __init__(self, spreadsheet):
        self._ss = spreadsheet
        self._ws: dict = {}
        self.data: dict = {table: {} for table in TABLE_MODELS}
        self._next: dict = {table: 1 for table in TABLE_MODELS}
        self._locks = {table: asyncio.Lock() for table in TABLE_MODELS}
        self._dirty: set = set()
        self._flush_lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self.flush_failures = 0
        #: کال‌بک اختیاری async(exc, failure_count) هنگام شکست مکرر flush.
        self.on_flush_error: Optional[Callable] = None

    # --- بارگذاری -----------------------------------------------------------

    async def load(self) -> None:
        """تب‌ها را می‌سازد (در صورت نبود) و کل داده را به حافظه می‌خواند."""
        await asyncio.to_thread(sheets.ensure_worksheets, self._ss)
        for table, model in TABLE_MODELS.items():
            ws = self._ss.worksheet(table)
            self._ws[table] = ws
            records = await asyncio.to_thread(sheets.read_all_records, ws)
            objects: dict = {}
            for record in records:
                obj = model.from_row(record)
                if obj.id is not None:
                    objects[obj.id] = obj
            self.data[table] = objects
            self._next[table] = (max(objects) + 1) if objects else 1
        logger.info(
            "Store بارگذاری شد: %s",
            {t: len(v) for t, v in self.data.items()},
        )

    # --- خواندن (بدون قفل) --------------------------------------------------

    def commit(self) -> None:
        """سازگاری با کد قدیمی: نوشتن‌ها از قبل در حافظه/صف اعمال شده‌اند."""
        return None

    def next_id(self, table: str) -> int:
        return self._next[table]

    def get(self, table: str, id_):
        if id_ is None:
            return None
        return self.data[table].get(int(id_))

    def list(self, table: str, predicate: Optional[Callable] = None) -> list:
        values = self.data[table].values()
        rows = [o for o in values if predicate is None or predicate(o)]
        return sorted(rows, key=lambda o: (o.id if o.id is not None else 0))

    # --- نوشتن (زیر قفلِ جدول) ----------------------------------------------

    async def add(self, table: str, obj):
        async with self._locks[table]:
            if obj.id is None:
                obj.id = self._next[table]
            self._next[table] = max(self._next[table], obj.id) + 1
            if hasattr(obj, "created_at") and getattr(obj, "created_at") is None:
                obj.created_at = jalali.now()
            self.data[table][obj.id] = obj
            self._dirty.add(table)
        return obj

    async def update(self, table: str, obj):
        async with self._locks[table]:
            if hasattr(obj, "updated_at"):
                obj.updated_at = jalali.now()
            self.data[table][obj.id] = obj
            self._dirty.add(table)
        return obj

    async def delete(self, table: str, id_) -> None:
        async with self._locks[table]:
            self.data[table].pop(int(id_), None)
            self._dirty.add(table)

    # --- نوشتنِ دسته‌ای روی شیت ----------------------------------------------

    async def flush(self) -> None:
        """تب‌های تغییرکرده را روی شیت بازنویسی می‌کند (idempotent)."""
        async with self._flush_lock:
            tables = list(self._dirty)
            if not tables:
                return
            try:
                for table in tables:
                    model = TABLE_MODELS[table]
                    rows = [o.to_row() for o in self.list(table)]
                    await asyncio.to_thread(
                        sheets.overwrite_worksheet,
                        self._ws[table],
                        list(model.COLUMNS),
                        rows,
                    )
                    self._dirty.discard(table)
                self.flush_failures = 0
            except Exception as exc:  # noqa: BLE001
                self.flush_failures += 1
                logger.error("خطا در نوشتن روی گوگل‌شیت (بار %s): %s", self.flush_failures, exc)
                if self.on_flush_error is not None:
                    try:
                        await self.on_flush_error(exc, self.flush_failures)
                    except Exception:  # pragma: no cover
                        pass
                raise

    # --- تسک پس‌زمینه --------------------------------------------------------

    def start_background_flush(self, interval: float = 5.0) -> None:
        async def _loop():
            while True:
                await asyncio.sleep(interval)
                try:
                    await self.flush()
                except Exception:  # pragma: no cover - در flush لاگ می‌شود
                    pass

        self._task = asyncio.ensure_future(_loop())

    async def stop(self) -> None:
        """تسک پس‌زمینه را متوقف و صف باقی‌مانده را قطعی می‌نویسد."""
        if self._task is not None:
            self._task.cancel()
            self._task = None
        try:
            await self.flush()
        except Exception:  # pragma: no cover
            pass
