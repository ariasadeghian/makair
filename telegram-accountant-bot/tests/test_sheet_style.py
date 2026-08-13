"""تست‌های استایلِ خودکارِ اسپردشیت (فاز ۱۳).

قاعده‌ی اصلی: استایل فقط ظاهر است. هیچ‌کدام از این کارها نباید مقدارِ یک
سلول را عوض کند یا جلوی ساخته‌شدنِ تب را بگیرد.
"""
import pytest

from fakes import FakeSpreadsheet, FakeWorksheet

from hesabyar.db import sheets_client as sc
from hesabyar.db.models import ALL_MODELS, CENTRAL_MODELS, USER_MODELS


def _ws(title="t", spreadsheet=None):
    sheet = spreadsheet or FakeSpreadsheet()
    return sheet.add_worksheet(title)


def _ranges(ws):
    return [rng for rng, _ in ws.formats]


def _fmt_for(ws, rng):
    return next(f for r, f in ws.formats if r == rng)


# --- شماره‌ی ستون ----------------------------------------------------------------


class TestColumnLetters:
    @pytest.mark.parametrize("index,letter", [
        (1, "A"), (2, "B"), (26, "Z"), (27, "AA"), (28, "AB"), (52, "AZ"),
    ])
    def test_conversion(self, index, letter):
        assert sc._col_letter(index) == letter


# --- هدر ------------------------------------------------------------------------


class TestHeader:
    def test_header_row_is_formatted_across_all_columns(self):
        ws = _ws()
        sc.style_worksheet(ws, ["id", "amount", "note"])
        assert "A1:C1" in _ranges(ws)

    def test_header_is_bold_and_coloured(self):
        ws = _ws()
        sc.style_worksheet(ws, ["id", "note"])
        fmt = _fmt_for(ws, "A1:B1")
        assert fmt["textFormat"]["bold"] is True
        assert fmt["backgroundColor"]
        assert fmt["textFormat"]["foregroundColor"] == {
            "red": 1, "green": 1, "blue": 1
        }

    def test_header_row_is_frozen(self):
        ws = _ws()
        sc.style_worksheet(ws, ["id", "note"])
        assert ws.frozen_rows == 1

    def test_the_same_colour_everywhere(self):
        first, second = _ws("a"), _ws("b")
        sc.style_worksheet(first, ["id"])
        sc.style_worksheet(second, ["id", "amount", "note"])
        assert (_fmt_for(first, "A1:A1")["backgroundColor"]
                == _fmt_for(second, "A1:C1")["backgroundColor"])


# --- ستون‌های پولی ---------------------------------------------------------------


class TestMoneyColumns:
    def test_amount_column_gets_thousands_separator(self):
        ws = _ws()
        sc.style_worksheet(ws, ["id", "user_id", "amount", "note"])
        fmt = _fmt_for(ws, "C2:C")
        assert fmt["numberFormat"] == {"type": "NUMBER", "pattern": "#,##0"}

    def test_unit_price_and_usd_too(self):
        ws = _ws()
        sc.style_worksheet(ws, ["unit_price", "usd"])
        assert "A2:A" in _ranges(ws) and "B2:B" in _ranges(ws)

    def test_the_header_cell_is_not_number_formatted(self):
        """رنجِ عددی از ردیف ۲ شروع می‌شود تا عنوانِ ستون خراب نشود."""
        ws = _ws()
        sc.style_worksheet(ws, ["amount"])
        assert "A1:A" not in _ranges(ws)

    def test_a_table_without_money_columns_is_fine(self):
        ws = _ws()
        sc.style_worksheet(ws, ["id", "user_id", "name", "code", "is_active"])
        assert _ranges(ws) == ["A1:E1"], "نباید فرمتِ عددیِ اضافه بزند"

    def test_each_money_column_gets_its_own_range(self):
        ws = _ws()
        sc.style_worksheet(ws, ["id", "amount", "x", "unit_price"])
        assert "B2:B" in _ranges(ws)
        assert "D2:D" in _ranges(ws)


# --- پهنای ستون‌ها ---------------------------------------------------------------


class TestColumnWidths:
    def test_long_text_columns_are_widened(self):
        sheet = FakeSpreadsheet()
        ws = _ws("transactions", sheet)
        sc.style_worksheet(ws, ["id", "description", "amount"])
        assert len(sheet.batch_updates) == 1
        requests = sheet.batch_updates[0]["requests"]
        rng = requests[0]["updateDimensionProperties"]["range"]
        assert rng["dimension"] == "COLUMNS"
        assert (rng["startIndex"], rng["endIndex"]) == (1, 2)   # ستونِ description
        assert rng["sheetId"] == ws.id

    def test_several_wide_columns_go_in_one_call(self):
        sheet = FakeSpreadsheet()
        ws = _ws("invoices", sheet)
        sc.style_worksheet(ws, ["id", "note", "customer_address", "address"])
        assert len(sheet.batch_updates) == 1
        assert len(sheet.batch_updates[0]["requests"]) == 3

    def test_no_call_when_there_is_nothing_to_widen(self):
        sheet = FakeSpreadsheet()
        ws = _ws("branches", sheet)
        sc.style_worksheet(ws, ["id", "user_id", "code"])
        assert sheet.batch_updates == []

    def test_the_width_is_bigger_than_the_google_default(self):
        assert sc.WIDE_COLUMN_PX > 100


# --- مقاومت ---------------------------------------------------------------------


class TestNeverBreaks:
    def test_empty_header_does_nothing(self):
        ws = _ws()
        sc.style_worksheet(ws, [])
        sc.style_worksheet(ws, None)
        assert ws.formats == [] and ws.frozen_rows == 0

    def test_missing_columns_are_skipped_silently(self):
        """تبِ branches ستونِ amount ندارد — نباید خطا بدهد."""
        ws = _ws("branches")
        sc.style_worksheet(ws, ["id", "user_id", "name", "code"])
        assert ws.frozen_rows == 1

    def test_an_api_error_does_not_propagate(self):
        class _Angry(FakeWorksheet):
            def format(self, range_name, fmt):
                raise RuntimeError("PERMISSION_DENIED")

            def freeze(self, rows=0, cols=0):
                raise RuntimeError("PERMISSION_DENIED")

        ws = _Angry("t")
        sc.style_worksheet(ws, ["id", "amount", "note"])   # نباید بترکد

    def test_a_failing_freeze_does_not_skip_the_number_format(self):
        class _NoFreeze(FakeWorksheet):
            def freeze(self, rows=0, cols=0):
                raise RuntimeError("nope")

        sheet = FakeSpreadsheet()
        ws = _NoFreeze("t", spreadsheet=sheet, sheet_id=1)
        sc.style_worksheet(ws, ["id", "amount"])
        assert "B2:B" in _ranges(ws)

    def test_a_failing_batch_update_does_not_propagate(self):
        class _AngrySheet(FakeSpreadsheet):
            def batch_update(self, body):
                raise RuntimeError("quota")

        sheet = _AngrySheet()
        ws = _ws("t", sheet)
        sc.style_worksheet(ws, ["id", "description"])
        assert ws.frozen_rows == 1

    def test_every_real_model_header_survives(self):
        for model in ALL_MODELS:
            sheet = FakeSpreadsheet()
            ws = sheet.add_worksheet(model.TABLE)
            sc.style_worksheet(ws, list(model.COLUMNS))
            assert ws.frozen_rows == 1, model.TABLE


# --- داده دست‌نخورده می‌ماند --------------------------------------------------------


class TestDataIsUntouched:
    def test_styling_does_not_change_any_cell(self):
        ws = _ws()
        ws.append_row(["id", "amount", "note"])
        ws.append_row(["1", "5000", "سلام"])
        before = ws.get_all_values()
        sc.style_worksheet(ws, ["id", "amount", "note"])
        assert ws.get_all_values() == before

    def test_ensure_worksheets_still_writes_only_the_header(self):
        sheet = FakeSpreadsheet()
        sc.ensure_worksheets(sheet, models=CENTRAL_MODELS)
        for model in CENTRAL_MODELS:
            ws = sheet.worksheet(model.TABLE)
            assert ws.get_all_values() == [list(model.COLUMNS)]

    async def test_a_full_write_and_reload_still_works(self, store):
        """استایل نباید به چرخه‌ی نوشتن/خواندن آسیب بزند."""
        from hesabyar.services import transactions as tx
        from hesabyar.core import jalali
        from hesabyar.db.models import Kind

        await tx.get_or_create_user(store, 15_001)
        await store.ensure_user_spreadsheet(15_001, "تست")
        await tx.add_transaction(
            store, 15_001, kind=Kind.EXPENSE, amount=1_234_567,
            category="متفرقه", description="شرحِ بلند", occurred_at=jalali.now(),
        )
        await store.flush()
        rows = store.list("transactions")
        assert len(rows) == 1 and rows[0].amount == 1_234_567


# --- فقط برای تبِ تازه ------------------------------------------------------------


class TestOnlyOnCreation:
    def test_new_tabs_are_styled(self):
        sheet = FakeSpreadsheet()
        sc.ensure_worksheets(sheet, models=USER_MODELS)
        for model in USER_MODELS:
            assert sheet.worksheet(model.TABLE).frozen_rows == 1, model.TABLE

    def test_existing_tabs_are_not_restyled(self):
        """هر بار بالا آمدنِ بات نباید ده‌ها فراخوانیِ اضافه به API بزند."""
        sheet = FakeSpreadsheet()
        sc.ensure_worksheets(sheet, models=USER_MODELS)
        counts = {ws.title: len(ws.formats) for ws in sheet.worksheets()}
        calls = len(sheet.batch_updates)

        sc.ensure_worksheets(sheet, models=USER_MODELS)   # اجرای دوم
        assert {ws.title: len(ws.formats) for ws in sheet.worksheets()} == counts
        assert len(sheet.batch_updates) == calls

    async def test_a_users_new_spreadsheet_is_styled(self, store):
        from hesabyar.services import transactions as tx
        await tx.get_or_create_user(store, 15_002)
        sheet_id = await store.ensure_user_spreadsheet(15_002, "کسب‌وکارِ من")
        user_sheet = store._client.sheets[sheet_id]
        for model in USER_MODELS:
            ws = user_sheet.worksheet(model.TABLE)
            assert ws.frozen_rows == 1, model.TABLE
            assert ws.formats, model.TABLE

    async def test_the_amount_column_of_transactions_is_formatted(self, store):
        from hesabyar.services import transactions as tx
        await tx.get_or_create_user(store, 15_003)
        sheet_id = await store.ensure_user_spreadsheet(15_003, "کسب‌وکارِ من")
        ws = store._client.sheets[sheet_id].worksheet("transactions")
        amount_index = list(
            next(m for m in USER_MODELS if m.TABLE == "transactions").COLUMNS
        ).index("amount") + 1
        letter = sc._col_letter(amount_index)
        assert f"{letter}2:{letter}" in _ranges(ws)


# --- هماهنگ‌سازیِ هدرِ تبِ موجود (فاز ۱۹ — سازگاریِ نصبِ قدیمی) --------------------


class _FakeModel:
    """مدلِ ساختگی با COLUMNS دلخواه — بدون درگیرشدن با مدل‌های واقعی."""

    def __init__(self, table, columns):
        self.TABLE = table
        self.COLUMNS = tuple(columns)


class TestReconcileHeaderAppendsSafely:
    def test_missing_worksheet_is_created_with_full_header(self):
        sheet = FakeSpreadsheet()
        model = _FakeModel("widgets", ["id", "name", "extra"])
        sc.ensure_worksheets(sheet, models=[model])
        ws = sheet.worksheet("widgets")
        assert ws.row_values(1) == ["id", "name", "extra"]

    def test_an_old_prefix_header_gets_the_missing_columns_appended(self):
        sheet = FakeSpreadsheet()
        ws = sheet.add_worksheet("widgets")
        ws.append_row(["id", "name"])
        ws.append_row(["1", "رضا"])
        model = _FakeModel("widgets", ["id", "name", "extra1", "extra2"])

        sc.ensure_worksheets(sheet, models=[model])

        assert ws.row_values(1) == ["id", "name", "extra1", "extra2"]
        # ردیفِ داده دست‌نخورده مانده (کوتاه‌تر از هدرِ تازه، که طبیعی است).
        assert ws.get_all_values()[1][:2] == ["1", "رضا"]

    def test_old_data_rows_read_back_with_empty_values_for_new_columns(self):
        """پیامدِ عملی: ردیفِ قدیمی بعدِ خواندن، مقدارِ ستونِ تازه را خالی می‌بیند."""
        sheet = FakeSpreadsheet()
        ws = sheet.add_worksheet("widgets")
        ws.append_row(["id", "name"])
        ws.append_row(["1", "رضا"])
        model = _FakeModel("widgets", ["id", "name", "extra"])
        sc.ensure_worksheets(sheet, models=[model])

        records = sc.read_all_records(ws)
        assert records == [{"id": "1", "name": "رضا", "extra": ""}]

    def test_an_already_current_header_is_left_alone(self):
        sheet = FakeSpreadsheet()
        ws = sheet.add_worksheet("widgets")
        ws.append_row(["id", "name"])
        ws.append_row(["1", "رضا"])
        model = _FakeModel("widgets", ["id", "name"])

        sc.ensure_worksheets(sheet, models=[model])

        assert ws.get_all_values() == [["id", "name"], ["1", "رضا"]]

    def test_an_empty_existing_worksheet_just_gets_the_header(self):
        sheet = FakeSpreadsheet()
        sheet.add_worksheet("widgets")  # تب هست ولی هیچ ردیفی ندارد
        model = _FakeModel("widgets", ["id", "name"])

        sc.ensure_worksheets(sheet, models=[model])

        assert sheet.worksheet("widgets").get_all_values() == [["id", "name"]]

    def test_calling_it_twice_is_idempotent(self):
        sheet = FakeSpreadsheet()
        ws = sheet.add_worksheet("widgets")
        ws.append_row(["id"])
        ws.append_row(["1"])
        model = _FakeModel("widgets", ["id", "name", "extra"])

        sc.ensure_worksheets(sheet, models=[model])
        after_first = ws.get_all_values()
        sc.ensure_worksheets(sheet, models=[model])
        after_second = ws.get_all_values()

        assert after_first == after_second == [["id", "name", "extra"], ["1"]]

    def test_grid_is_resized_when_the_new_header_needs_more_columns(self):
        sheet = FakeSpreadsheet()
        ws = sheet.add_worksheet("widgets", rows=200, cols=1)
        ws.append_row(["id"])
        model = _FakeModel("widgets", ["id", "name", "extra"])

        sc.ensure_worksheets(sheet, models=[model])

        assert ws.col_count >= 3


class TestReconcileHeaderFailsLoudlyOnMismatch:
    def test_a_non_prefix_header_raises_schema_mismatch(self):
        sheet = FakeSpreadsheet()
        ws = sheet.add_worksheet("widgets")
        ws.append_row(["id", "renamed_column"])
        ws.append_row(["1", "x"])
        model = _FakeModel("widgets", ["id", "name", "extra"])

        with pytest.raises(sc.SchemaMismatchError) as exc_info:
            sc.ensure_worksheets(sheet, models=[model])
        err = exc_info.value
        assert err.table == "widgets"
        assert err.current_header == ["id", "renamed_column"]
        assert err.expected_header == ["id", "name", "extra"]

    def test_a_header_longer_than_expected_also_raises(self):
        """ستونی که از کدِ فعلی حذف شده هم باید بلند خطا بدهد، نه بی‌سروصدا رد شود."""
        sheet = FakeSpreadsheet()
        ws = sheet.add_worksheet("widgets")
        ws.append_row(["id", "name", "extra", "even_more"])
        model = _FakeModel("widgets", ["id", "name", "extra"])

        with pytest.raises(sc.SchemaMismatchError):
            sc.ensure_worksheets(sheet, models=[model])

    def test_the_mismatched_data_is_not_touched(self):
        sheet = FakeSpreadsheet()
        ws = sheet.add_worksheet("widgets")
        ws.append_row(["id", "renamed_column"])
        ws.append_row(["1", "x"])
        model = _FakeModel("widgets", ["id", "name", "extra"])

        with pytest.raises(sc.SchemaMismatchError):
            sc.ensure_worksheets(sheet, models=[model])

        assert ws.get_all_values() == [["id", "renamed_column"], ["1", "x"]]

    def test_error_message_names_the_worksheet(self):
        sheet = FakeSpreadsheet()
        ws = sheet.add_worksheet("widgets")
        ws.append_row(["id", "renamed_column"])
        model = _FakeModel("widgets", ["id", "name", "extra"])

        with pytest.raises(sc.SchemaMismatchError, match="widgets"):
            sc.ensure_worksheets(sheet, models=[model])
