"""لایه‌ی داده‌ی در حافظه روی Google Sheets (چند-اسپردشیتی).

معماری:

* یک اسپردشیت **مرکزی** که رجیستری حساب‌هاست: ``users``، ``subscriptions``،
  ``payments``، ``rates``، ``branches``، ``branch_members`` و ``sequences``.
  این‌ها مرکزی‌اند چون کوئری‌شان ذاتاً بین‌کاربری است (ادمین پرداختی را فقط با
  شناسه‌اش تأیید می‌کند؛ کارمند با «کد» به شعبه می‌پیوندد در حالی که هنوز مالک
  را نمی‌شناسیم؛ نرخ دلار سراسری است).
* برای هر کاربر یک اسپردشیت **اختصاصی** که دفترِ واقعیِ کسب‌وکار اوست:
  ``transactions``، ``ledger_entries``، ``invoices``، ``invoice_items``،
  ``products`` و ``group_events``.

خواندن‌ها از حافظه‌اند (سریع، بدون Rate Limit) و نوشتن‌ها هم در حافظه اعمال و هم
برای نوشتنِ دسته‌ای صف می‌شوند. داده‌ی هر کاربر **تنبل** (lazy) و در اولین
دسترسی بارگذاری می‌شود؛ ``get_or_create_user`` این کار را انجام می‌دهد.

شناسه‌ها از یک شمارنده‌ی مرکزی (``sequences``) گرفته می‌شوند تا داده‌ی دو کاربرِ
مختلف در حافظه روی هم نیفتد.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from ..core import jalali
from . import sheets_client as sheets
from .models import (
    CENTRAL_MODELS,
    CENTRAL_TABLES,
    OWNER_FIELD,
    TABLE_MODELS,
    USER_MODELS,
    USER_TABLES,
    Sequence,
)

logger = logging.getLogger(__name__)


class Store:
    """داده‌ی در حافظه روی یک اسپردشیت مرکزی + اسپردشیت اختصاصیِ هر کاربر.

    :param central: اسپردشیت مرکزی (رجیستری).
    :param client: کلاینت gspread برای باز/ساختِ اسپردشیت کاربرها. اگر ندهیم،
        فقط جدول‌های مرکزی کار می‌کنند (مفید در تست‌های خالص).
    :param folder_id: پوشه‌ی Drive برای ساخت اسپردشیت کاربران.
    """

    def __init__(self, central, client=None, folder_id: str = ""):
        self._central = central
        self._client = client
        self._folder_id = folder_id or ""
        #: تب‌های اسپردشیت مرکزی
        self._ws: dict = {}
        #: user_id -> اسپردشیتِ باز‌شده‌ی همان کاربر (کش)
        self._user_ss: dict = {}
        #: user_id -> {table: worksheet}
        self._user_ws: dict = {}
        #: کاربرانی که داده‌شان در حافظه بارگذاری شده است
        self._loaded_users: set = set()

        self.data: dict = {table: {} for table in TABLE_MODELS}
        self._seq: dict = {}
        self._locks = {table: asyncio.Lock() for table in TABLE_MODELS}
        #: تب‌های مرکزیِ تغییرکرده
        self._dirty: set = set()
        #: (user_id, table) های تغییرکرده
        self._dirty_user: set = set()
        self._flush_lock = asyncio.Lock()
        self._user_lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self.flush_failures = 0
        #: کال‌بک اختیاری async(exc, failure_count) هنگام شکست مکرر flush.
        self.on_flush_error: Optional[Callable] = None

    # --- بارگذاری -----------------------------------------------------------

    async def load(self) -> None:
        """تب‌های مرکزی را می‌سازد (در صورت نبود) و به حافظه می‌خواند.

        داده‌ی کاربرها اینجا خوانده **نمی‌شود**؛ هر کاربر در اولین دسترسی
        بارگذاری می‌شود (:meth:`load_user`).
        """
        await asyncio.to_thread(sheets.ensure_worksheets, self._central, CENTRAL_MODELS)
        for model in CENTRAL_MODELS:
            table = model.TABLE
            ws = self._central.worksheet(table)
            self._ws[table] = ws
            records = await asyncio.to_thread(sheets.read_all_records, ws)
            objects: dict = {}
            for record in records:
                obj = model.from_row(record)
                if obj.id is not None:
                    objects[obj.id] = obj
            self.data[table] = objects

        # شمارنده‌ها را از تب sequences بردار
        self._seq = {
            row.name: int(row.last_id)
            for row in self.data[Sequence.TABLE].values()
            if row.name
        }
        logger.info(
            "Store مرکزی بارگذاری شد: %s",
            {t: len(self.data[t]) for t in CENTRAL_TABLES},
        )

    async def load_user(self, user_id: int) -> bool:
        """داده‌ی یک کاربر را از اسپردشیت اختصاصی‌اش به حافظه می‌خواند.

        idempotent است؛ اگر قبلاً بارگذاری شده یا کاربر هنوز اسپردشیت ندارد،
        بی‌سروصدا رد می‌شود. ``True`` یعنی داده‌ای بارگذاری شد.
        """
        user_id = int(user_id)
        if user_id in self._loaded_users:
            return False
        async with self._user_lock:
            if user_id in self._loaded_users:  # رقابت هم‌زمان
                return False
            spreadsheet = await self._open_user_spreadsheet(user_id)
            if spreadsheet is None:
                return False
            ws_map = {}
            for model in USER_MODELS:
                table = model.TABLE
                ws = spreadsheet.worksheet(table)
                ws_map[table] = ws
                records = await asyncio.to_thread(sheets.read_all_records, ws)
                for record in records:
                    obj = model.from_row(record)
                    if obj.id is not None:
                        self.data[table][obj.id] = obj
            self._user_ws[user_id] = ws_map
            self._loaded_users.add(user_id)
        return True

    async def load_all_users(self) -> int:
        """دفترِ همه‌ی کاربرانِ رجیستری را بارگذاری می‌کند.

        برای کارهای زمان‌بندی‌شده‌ای لازم است که ذاتاً بین‌کاربری‌اند (یادآوری
        سررسید، خلاصه‌ی شب، سنجه‌های پایلوت). چون این jobها روزی یک‌بار اجرا
        می‌شوند، هزینه‌ی بازکردنِ اسپردشیت‌ها قابل‌قبول است.
        """
        count = 0
        for user_id in list(self.data["users"]):
            try:
                if await self.load_user(user_id):
                    count += 1
            except Exception as exc:  # noqa: BLE001 - یک کاربرِ خراب کل job را نخواباند
                logger.error("بارگذاری دفترِ کاربر %s ناموفق: %s", user_id, exc)
        return count

    async def _open_user_spreadsheet(self, user_id: int):
        """اسپردشیت اختصاصیِ کاربر را باز می‌کند (با کش)؛ ``None`` اگر نداشته باشد."""
        if user_id in self._user_ss:
            return self._user_ss[user_id]
        user = self.data["users"].get(int(user_id))
        if user is None or not user.sheet_id or self._client is None:
            return None
        spreadsheet = await asyncio.to_thread(
            sheets.open_spreadsheet, self._client, user.sheet_id
        )
        self._user_ss[user_id] = spreadsheet
        return spreadsheet

    async def refresh_summary(self, user_id: int) -> bool:
        """تبِ نمایشیِ «📋 خلاصه» را از روی داده‌ی واقعی از نو می‌سازد.

        هیچ‌جای بات از این تب نمی‌خواند؛ شکستش هم بی‌خطر است (فقط لاگ) چون
        منبعِ حقیقت همان تب‌های اصلی است.
        """
        from ..services import products as products_service
        from ..services import subscription as sub_service

        user_id = int(user_id)
        user = self.data["users"].get(user_id)
        if user is None:
            return False
        spreadsheet = await self._open_user_spreadsheet(user_id)
        if spreadsheet is None:
            return False
        grouped = products_service.by_category(self, user_id)
        plan = sub_service.tier_label_for(self, user_id)
        try:
            await asyncio.to_thread(
                sheets.rebuild_summary_sheet, spreadsheet, user, grouped, plan
            )
            ws = self._user_ws.get(user_id, {}).get("products")
            if ws is not None:
                await asyncio.to_thread(
                    sheets.apply_category_colors, spreadsheet, ws, list(grouped)
                )
        except Exception as exc:  # noqa: BLE001 - تبِ نمایشی، نه داده
            logger.warning("ساختِ تبِ خلاصه ناموفق بود: %s", exc)
            return False
        return True

    async def ensure_user_spreadsheet(self, user_id: int, title: str = "") -> str:
        """اسپردشیت اختصاصیِ کاربر را می‌سازد (اگر ندارد) و شناسه‌اش را می‌دهد.

        تب‌های دفترِ کاربر را هم می‌سازد و ``sheet_id`` را در رجیستریِ مرکزی
        ذخیره می‌کند.
        """
        user_id = int(user_id)
        user = self.data["users"].get(user_id)
        if user is None:
            raise KeyError(f"کاربر {user_id} در رجیستری نیست.")
        if user.sheet_id:
            return user.sheet_id
        if self._client is None:
            return ""

        name = title or user.business_name or str(user_id)
        sheet_title = f"حسابیار — {name} ({user_id})"
        sheet_id = await asyncio.to_thread(
            sheets.create_user_spreadsheet, self._client, sheet_title, self._folder_id
        )
        spreadsheet = await asyncio.to_thread(
            sheets.open_spreadsheet, self._client, sheet_id
        )
        await asyncio.to_thread(sheets.ensure_worksheets, spreadsheet, USER_MODELS)

        self._user_ss[user_id] = spreadsheet
        self._user_ws[user_id] = {
            m.TABLE: spreadsheet.worksheet(m.TABLE) for m in USER_MODELS
        }
        self._loaded_users.add(user_id)

        user.sheet_id = sheet_id
        await self.update("users", user)
        logger.info("اسپردشیت اختصاصی برای کاربر %s ساخته شد.", user_id)
        return sheet_id

    # --- خواندن (بدون قفل) --------------------------------------------------

    def commit(self) -> None:
        """سازگاری با کد قدیمی: نوشتن‌ها از قبل در حافظه/صف اعمال شده‌اند."""
        return None

    def next_id(self, table: str) -> int:
        """شناسه‌ی بعدی از شمارنده‌ی مرکزی (یکتا در بین همه‌ی کاربران)."""
        return self._seq.get(table, 0) + 1

    def get(self, table: str, id_):
        if id_ is None:
            return None
        return self.data[table].get(int(id_))

    def list(self, table: str, predicate: Optional[Callable] = None) -> list:
        values = self.data[table].values()
        rows = [o for o in values if predicate is None or predicate(o)]
        return sorted(rows, key=lambda o: (o.id if o.id is not None else 0))

    # --- تشخیص مالکِ یک ردیف -------------------------------------------------

    def _owner_of(self, table: str, obj) -> Optional[int]:
        """کاربری که این ردیف به دفترش تعلق دارد."""
        field = OWNER_FIELD.get(table)
        if field is not None:
            value = getattr(obj, field, None)
            return int(value) if value is not None else None
        if table == "invoice_items":  # مالکِ قلم = مالکِ فاکتورش
            invoice = self.data["invoices"].get(int(obj.invoice_id or 0))
            return int(invoice.user_id) if invoice is not None else None
        return None

    def _mark_dirty(self, table: str, obj=None) -> None:
        if table in CENTRAL_TABLES:
            self._dirty.add(table)
            return
        owner = self._owner_of(table, obj) if obj is not None else None
        if owner is not None:
            self._dirty_user.add((owner, table))

    # --- نوشتن (زیر قفلِ جدول) ----------------------------------------------

    async def add(self, table: str, obj):
        async with self._locks[table]:
            if obj.id is None:
                obj.id = self.next_id(table)
            self._seq[table] = max(self._seq.get(table, 0), int(obj.id))
            self._dirty.add(Sequence.TABLE)
            if hasattr(obj, "created_at") and getattr(obj, "created_at") is None:
                obj.created_at = jalali.now()
            self.data[table][obj.id] = obj
            self._mark_dirty(table, obj)
        return obj

    async def update(self, table: str, obj):
        async with self._locks[table]:
            if hasattr(obj, "updated_at"):
                obj.updated_at = jalali.now()
            self.data[table][obj.id] = obj
            self._mark_dirty(table, obj)
        return obj

    async def delete(self, table: str, id_) -> None:
        async with self._locks[table]:
            obj = self.data[table].pop(int(id_), None)
            self._mark_dirty(table, obj)

    # --- نوشتنِ دسته‌ای روی شیت ----------------------------------------------

    def _sequence_rows(self) -> list:
        """تب شمارنده‌ها را از روی حافظه بازمی‌سازد."""
        rows, i = [], 0
        for name, last in sorted(self._seq.items()):
            i += 1
            rows.append(Sequence(id=i, name=name, last_id=last).to_row())
        return rows

    async def flush(self) -> None:
        """تب‌های تغییرکرده را بازنویسی می‌کند (مرکزی + اسپردشیتِ هر کاربر)."""
        async with self._flush_lock:
            central = list(self._dirty)
            per_user = list(self._dirty_user)
            if not central and not per_user:
                return
            try:
                for table in central:
                    model = TABLE_MODELS[table]
                    if table == Sequence.TABLE:
                        rows = self._sequence_rows()
                    else:
                        rows = [o.to_row() for o in self.list(table)]
                    await asyncio.to_thread(
                        sheets.overwrite_worksheet,
                        self._ws[table], list(model.COLUMNS), rows,
                    )
                    self._dirty.discard(table)

                for owner, table in per_user:
                    ws = (self._user_ws.get(owner) or {}).get(table)
                    if ws is None:  # کاربر هنوز اسپردشیت ندارد
                        self._dirty_user.discard((owner, table))
                        continue
                    model = TABLE_MODELS[table]
                    rows = [
                        o.to_row() for o in self.list(table)
                        if self._owner_of(table, o) == owner
                    ]
                    await asyncio.to_thread(
                        sheets.overwrite_worksheet,
                        ws, list(model.COLUMNS), rows,
                    )
                    self._dirty_user.discard((owner, table))
                self.flush_failures = 0
            except Exception as exc:  # noqa: BLE001
                self.flush_failures += 1
                logger.error(
                    "خطا در نوشتن روی گوگل‌شیت (بار %s): %s", self.flush_failures, exc
                )
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
