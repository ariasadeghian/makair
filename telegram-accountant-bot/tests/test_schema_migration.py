"""یکپارچگیِ نسخه: یک نصبِ واقعیِ فازِ ۱۸ باید با کدِ فازِ ۱۹ بدون خطا بالا بیاید.

شبیه‌سازی می‌کند: اسپردشیتِ مرکزی با هدرِ ``users``ی فازِ ۱۸ (بدون ستون‌های
اعلان/جمع‌بندی)، و اسپردشیتِ اختصاصیِ یک کاربر که فقط تب‌های فازِ ۱۸ را دارد —
``ledger_entries`` بدون ``snooze_until`` و اصلاً بدون تبِ ``retention_events``.
سپس با کدِ فعلی بارگذاری می‌شود و می‌بایست: خطا ندهد، داده‌ی قدیمی دست‌نخورده
بماند، تبِ غایب ساخته شود، ستون‌های غایب اضافه شوند، پیش‌فرض‌ها درست باشند، و
همه‌چیز idempotent و پایدار بمانَد.
"""
import datetime as dt

from fakes import FakeClient, FakeSpreadsheet

from hesabyar.core import jalali
from hesabyar.db.models import (
    Customer, Direction, GroupEvent, Instrument, Invoice, InvoiceItem, Kind,
    LedgerEntry, Product, RetentionEvent, Sequence, Transaction, User,
)
from hesabyar.db.sheets_client import SchemaMismatchError
from hesabyar.db.store import Store
from hesabyar.services import transactions as tx_service

UID = 55_001
CENTRAL_SHEET_ID = "central"
USER_SHEET_ID = "user-sheet-1"


def _phase18_columns(model, drop: tuple) -> list:
    """ستون‌های فعلیِ مدل منهای اضافاتِ فازِ ۱۹ — دقیقاً چیزی که یک نصبِ
    واقعیِ فازِ ۱۸ روی شیت داشته (فرض: اضافاتِ تازه همیشه در انتهای
    COLUMNS آمده‌اند، نه وسط)."""
    kept = [c for c in model.COLUMNS if c not in drop]
    assert kept == list(model.COLUMNS[: len(kept)]), "فرضِ پیشوند برقرار نیست"
    return kept


PHASE18_USER_COLUMNS = _phase18_columns(
    User, drop=("notify_daily_close", "notify_due_reminders", "last_daily_close_date")
)
PHASE18_LEDGER_COLUMNS = _phase18_columns(LedgerEntry, drop=("snooze_until",))


def _seed(spreadsheet, table: str, header: list, rows: list[list]):
    ws = spreadsheet.add_worksheet(title=table, rows=200, cols=max(len(header), 1))
    ws.append_row(header)
    for row in rows:
        ws.append_row(row)
    return ws


def _build_phase18_installation():
    """یک اسپردشیتِ مرکزی + یک اسپردشیتِ اختصاصی، دقیقاً به شکلِ فازِ ۱۸."""
    client = FakeClient()
    central = FakeSpreadsheet(id=CENTRAL_SHEET_ID)
    client.sheets[CENTRAL_SHEET_ID] = central

    user = User(
        id=UID, business_name="قنادی قدیمی", phone="02100000000",
        sheet_id=USER_SHEET_ID, created_at=jalali.now(),
    )
    _seed(central, "users", PHASE18_USER_COLUMNS,
          [user.to_row()[: len(PHASE18_USER_COLUMNS)]])
    # شمارنده‌ها را هم واقعی بکاریم — وگرنه next_id از صفر شروع می‌کند و
    # شناسه‌ی رکوردهای تازه با رکوردهای «قدیمیِ» کاشته‌شده تصادم می‌کند.
    _seed(central, "sequences", list(Sequence.COLUMNS), [
        Sequence(id=1, name="transactions", last_id=1).to_row(),
        Sequence(id=2, name="ledger_entries", last_id=1).to_row(),
        Sequence(id=3, name="invoices", last_id=1).to_row(),
        Sequence(id=4, name="invoice_items", last_id=1).to_row(),
        Sequence(id=5, name="customers", last_id=1).to_row(),
    ])
    # سایرِ جدول‌های مرکزی عمداً کاشته نمی‌شوند — بین فازِ ۱۸ و ۱۹ عوض
    # نشده‌اند؛ ``ensure_worksheets`` باید بی‌خطا برایشان تبِ خالی بسازد.

    user_ss = FakeSpreadsheet(id=USER_SHEET_ID)
    client.sheets[USER_SHEET_ID] = user_ss

    old_tx = Transaction(
        id=1, user_id=UID, kind=Kind.EXPENSE, amount=250_000,
        category="قبوض", description="قبضِ برق", occurred_at=jalali.now(),
        created_at=jalali.now(),
    )
    _seed(user_ss, "transactions", list(Transaction.COLUMNS), [old_tx.to_row()])

    old_entry = LedgerEntry(
        id=1, user_id=UID, direction=Direction.RECEIVABLE, party_name="علی",
        amount=500_000, due_date=jalali.now().date(), created_at=jalali.now(),
        instrument=Instrument.CASH,
    )
    _seed(user_ss, "ledger_entries", PHASE18_LEDGER_COLUMNS,
          [old_entry.to_row()[: len(PHASE18_LEDGER_COLUMNS)]])

    old_invoice = Invoice(
        id=1, user_id=UID, number="۱۴۰۳-۰۰۰۱", seq=1, customer_name="سارا",
        issue_date=jalali.now().date(), created_at=jalali.now(),
    )
    _seed(user_ss, "invoices", list(Invoice.COLUMNS), [old_invoice.to_row()])

    old_item = InvoiceItem(id=1, invoice_id=1, title="کیک", quantity=1, unit_price=900_000)
    _seed(user_ss, "invoice_items", list(InvoiceItem.COLUMNS), [old_item.to_row()])

    _seed(user_ss, "products", list(Product.COLUMNS), [])
    _seed(user_ss, "group_events", list(GroupEvent.COLUMNS), [])

    old_customer = Customer(id=1, user_id=UID, name="سارا", created_at=jalali.now())
    _seed(user_ss, "customers", list(Customer.COLUMNS), [old_customer.to_row()])

    # عمداً هیچ تبِ retention_events ساخته نمی‌شود — دقیقاً نبودش، بحرانِ اصلی است.
    assert "retention_events" not in user_ss._ws

    return client, central, user_ss


async def _load_store(client, central) -> Store:
    store = Store(central, client=client, folder_id="folder-x")
    await store.load()
    return store


class TestExistingInstallationBootsCleanly:
    async def test_load_and_load_user_do_not_raise(self):
        client, central, _user_ss = _build_phase18_installation()
        store = await _load_store(client, central)
        loaded = await store.load_user(UID)  # نباید WorksheetNotFound بدهد
        assert loaded is True

    async def test_old_transaction_survives_untouched(self):
        client, central, _user_ss = _build_phase18_installation()
        store = await _load_store(client, central)
        await store.load_user(UID)
        tx = store.get("transactions", 1)
        assert tx is not None
        assert tx.amount == 250_000
        assert tx.category == "قبوض"
        assert tx.description == "قبضِ برق"

    async def test_old_ledger_entry_survives_and_has_no_snooze(self):
        client, central, _user_ss = _build_phase18_installation()
        store = await _load_store(client, central)
        await store.load_user(UID)
        entry = store.get("ledger_entries", 1)
        assert entry is not None
        assert entry.amount == 500_000
        assert entry.party_name == "علی"
        assert entry.snooze_until is None

    async def test_old_invoice_and_customer_survive(self):
        client, central, _user_ss = _build_phase18_installation()
        store = await _load_store(client, central)
        await store.load_user(UID)
        invoice = store.get("invoices", 1)
        customer = store.get("customers", 1)
        assert invoice is not None and invoice.customer_name == "سارا"
        assert customer is not None and customer.name == "سارا"

    async def test_retention_events_worksheet_gets_created(self):
        client, central, user_ss = _build_phase18_installation()
        store = await _load_store(client, central)
        await store.load_user(UID)
        assert "retention_events" in user_ss._ws
        assert user_ss._ws["retention_events"].row_values(1) == list(RetentionEvent.COLUMNS)
        assert store.list("retention_events", lambda e: e.user_id == UID) == []

    async def test_snooze_until_column_is_appended_to_ledger_entries(self):
        client, central, user_ss = _build_phase18_installation()
        store = await _load_store(client, central)
        await store.load_user(UID)

        header = user_ss._ws["ledger_entries"].row_values(1)
        assert header == list(LedgerEntry.COLUMNS)

        # ردیفِ قدیمی: بخشِ قبلی دست‌نخورده، سلولِ تازه (snooze_until) خالی.
        raw_row = user_ss._ws["ledger_entries"].get_all_values()[1]
        old_prefix = raw_row[: len(PHASE18_LEDGER_COLUMNS)]
        expected_prefix = LedgerEntry(
            id=1, user_id=UID, direction=Direction.RECEIVABLE, party_name="علی",
            amount=500_000, due_date=jalali.now().date(),
            instrument=Instrument.CASH,
        ).to_row()[: len(PHASE18_LEDGER_COLUMNS)]
        # created_at با استمپِ واقعیِ ساخت فرق دارد؛ همه‌چیز جز آن را چک کن.
        created_at_index = PHASE18_LEDGER_COLUMNS.index("created_at")
        for i in range(len(PHASE18_LEDGER_COLUMNS)):
            if i == created_at_index:
                continue
            assert old_prefix[i] == expected_prefix[i], PHASE18_LEDGER_COLUMNS[i]
        snooze_index = list(LedgerEntry.COLUMNS).index("snooze_until")
        # ردیفِ خام کوتاه‌تر از هدر مانده (دست‌نخورده) — یعنی سلولِ جدید
        # یا اصلاً وجود ندارد یا خالی است؛ هردو یعنی «هنوز اسنوز نشده».
        assert len(raw_row) <= snooze_index or raw_row[snooze_index] == ""

    async def test_notification_columns_are_appended_to_users_and_default_on(self):
        client, central, _user_ss = _build_phase18_installation()
        store = await _load_store(client, central)
        header = central.worksheet("users").row_values(1)
        assert header == list(User.COLUMNS)

        user = store.get("users", UID)
        assert user.notify_daily_close is True
        assert user.notify_due_reminders is True
        assert user.last_daily_close_date is None

    async def test_old_users_row_is_not_reordered_or_truncated(self):
        client, central, _user_ss = _build_phase18_installation()
        await _load_store(client, central)
        row = central.worksheet("users").get_all_values()[1]
        header = central.worksheet("users").row_values(1)
        as_dict = dict(zip(header, row))
        assert as_dict["business_name"] == "قنادی قدیمی"
        assert as_dict["phone"] == "02100000000"
        assert as_dict["sheet_id"] == USER_SHEET_ID


class TestMigrationIsIdempotent:
    async def test_running_it_twice_does_not_error_or_duplicate(self):
        client, central, user_ss = _build_phase18_installation()
        store1 = await _load_store(client, central)
        await store1.load_user(UID)

        # «ری‌استارت»: یک Store کاملاً تازه، روی همان اسپردشیت‌های حالا-مهاجرت‌شده.
        store2 = Store(central, client=client, folder_id="folder-x")
        await store2.load()
        await store2.load_user(UID)

        assert store2.get("transactions", 1) is not None
        assert store2.get("ledger_entries", 1) is not None
        assert len(user_ss._ws["ledger_entries"].get_all_values()) == 2  # هدر + یک ردیف
        assert len(central.worksheet("users").get_all_values()) == 2

    async def test_header_is_stable_after_two_reconciliations(self):
        client, central, user_ss = _build_phase18_installation()
        store1 = await _load_store(client, central)
        await store1.load_user(UID)
        header_after_first = user_ss._ws["ledger_entries"].row_values(1)

        store2 = Store(central, client=client, folder_id="folder-x")
        await store2.load()
        await store2.load_user(UID)
        header_after_second = user_ss._ws["ledger_entries"].row_values(1)

        assert header_after_first == header_after_second == list(LedgerEntry.COLUMNS)


class TestWriteFlushReloadSurvivesMigration:
    async def test_old_and_new_fields_all_survive_a_round_trip(self):
        client, central, user_ss = _build_phase18_installation()
        store = await _load_store(client, central)
        await store.load_user(UID)

        # چیزِ تازه بنویس (فیلدِ فازِ ۱۹) روی رکوردِ قدیمی.
        user = store.get("users", UID)
        user.notify_daily_close = False
        await store.update("users", user)

        entry = store.get("ledger_entries", 1)
        entry.snooze_until = jalali.now().date() + dt.timedelta(days=3)
        await store.update("ledger_entries", entry)

        # یک تراکنشِ تازه هم اضافه کن تا مطمئن شویم نوشتنِ عادی خراب نشده.
        await tx_service.add_transaction(
            store, UID, kind=Kind.INCOME, amount=1_000_000, category="فروش",
            description="", occurred_at=jalali.now(),
        )

        await store.flush()

        # حالا از صفر، با یک Store کاملاً تازه، دوباره بخوان.
        store2 = Store(central, client=client, folder_id="folder-x")
        await store2.load()
        await store2.load_user(UID)

        reloaded_user = store2.get("users", UID)
        assert reloaded_user.notify_daily_close is False       # نوِ تازه
        assert reloaded_user.business_name == "قنادی قدیمی"     # قدیمیِ دست‌نخورده

        reloaded_entry = store2.get("ledger_entries", 1)
        assert reloaded_entry.snooze_until == jalali.now().date() + dt.timedelta(days=3)
        assert reloaded_entry.party_name == "علی"               # قدیمیِ دست‌نخورده

        txs = store2.list("transactions", lambda t: t.user_id == UID)
        assert len(txs) == 2  # قدیمی + تازه
        assert any(t.amount == 250_000 for t in txs)
        assert any(t.amount == 1_000_000 for t in txs)


class TestSchemaMismatchFailsLoudly:
    async def test_a_header_that_is_not_a_valid_prefix_raises(self):
        client, central, user_ss = _build_phase18_installation()
        # هدرِ ledger_entries را دستکاری کن تا نه برابر باشد نه پیشوند
        # (ترتیبِ دو ستون را عوض می‌کنیم — یک ناسازگاریِ واقعی).
        ws = user_ss._ws["ledger_entries"]
        mutated = list(PHASE18_LEDGER_COLUMNS)
        mutated[0], mutated[1] = mutated[1], mutated[0]
        ws._values[0] = mutated

        store = await _load_store(client, central)
        raised = False
        try:
            await store.load_user(UID)
        except SchemaMismatchError as exc:
            raised = True
            assert exc.table == "ledger_entries"
            assert exc.current_header == mutated
        assert raised, "باید به‌جای خرابکردنِ بی‌سروصدا، بلند خطا بدهد"

        # داده‌ی خام روی شیت دست‌نخورده مانده — هیچ چیزی بازنویسی نشده.
        assert ws.get_all_values()[0] == mutated
