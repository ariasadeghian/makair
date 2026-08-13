"""اسپردشیت ساختگی برای تست‌ها (بدون اتصال به اینترنت).

رفتار حداقلیِ لازم از gspread را در حافظه شبیه‌سازی می‌کند: ``worksheets``،
``worksheet``، ``add_worksheet`` و روی هر تب ``get_all_values``،
``get_all_records``، ``append_row``، ``clear``، ``update`` و ``row_values``/
``resize``/``col_count`` (برای هماهنگ‌سازیِ هدر در ``ensure_worksheets``).

فراخوانی‌های ظاهری (``format``، ``freeze``، ``batch_update``) هم ثبت می‌شوند
تا تست بتواند ثابت کند استایل اعمال شده و به مقدارِ سلول‌ها دست نزده است.
"""
from __future__ import annotations

import re


def _cell(x) -> str:
    return "" if x is None else str(x)


def _col_index(letters: str) -> int:
    """نمایشِ حرفیِ ستون به عدد: ``"A"`` → ۱، ``"AA"`` → ۲۷."""
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index


def _parse_a1_range(range_name: str) -> tuple[int, int, int, int]:
    """``"D1:E1"`` → ``(start_row, start_col, end_row, end_col)`` (۱-پایه)."""
    m = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", range_name)
    if not m:
        raise ValueError(f"fake worksheet: unsupported A1 range {range_name!r}")
    c1, r1, c2, r2 = m.groups()
    return int(r1), _col_index(c1), int(r2), _col_index(c2)


class FakeWorksheet:
    def __init__(self, title: str, spreadsheet=None, sheet_id: int = 0,
                 rows: int = 200, cols: int = 20):
        self.title = title
        self._values: list[list[str]] = []  # سطر اول = هدر
        self.spreadsheet = spreadsheet
        self.id = sheet_id
        self.formats: list = []
        self.frozen_rows: int = 0
        self.row_count = rows
        self.col_count = cols

    def get_all_values(self):
        return [list(r) for r in self._values]

    def get_all_records(self):
        if not self._values:
            return []
        header = self._values[0]
        out = []
        for row in self._values[1:]:
            padded = list(row) + [""] * (len(header) - len(row))
            out.append(dict(zip(header, padded)))
        return out

    def row_values(self, row: int) -> list:
        """مثلِ gspread واقعی: بدونِ padding، سلول‌های خالیِ انتها هم افتاده."""
        idx = row - 1
        if idx < 0 or idx >= len(self._values):
            return []
        line = [_cell(x) for x in self._values[idx]]
        while line and line[-1] == "":
            line.pop()
        return line

    def append_row(self, row):
        self._values.append([_cell(x) for x in row])

    def append_rows(self, rows):
        for r in rows:
            self.append_row(r)

    def clear(self):
        self._values = []

    def resize(self, rows: int | None = None, cols: int | None = None):
        if rows is not None:
            self.row_count = rows
        if cols is not None:
            self.col_count = cols

    def update(self, values, value_input_option=None, range_name=None):
        if range_name is None:
            # مثلِ استفاده‌ی امروزیِ کد: همیشه بعد از ``clear()`` صدا زده
            # می‌شود، پس نوشتن از A1 معادلِ جایگزینیِ کل تب است.
            self._values = [[_cell(x) for x in row] for row in values]
            return
        start_row, start_col, _end_row, _end_col = _parse_a1_range(range_name)
        while len(self._values) < start_row - 1 + len(values):
            self._values.append([])
        for r_offset, row in enumerate(values):
            line = self._values[start_row - 1 + r_offset]
            needed = start_col - 1 + len(row)
            if len(line) < needed:
                line.extend([""] * (needed - len(line)))
            for c_offset, val in enumerate(row):
                line[start_col - 1 + c_offset] = _cell(val)

    # --- ظاهر (به مقدارِ سلول‌ها دست نمی‌زنند) ---------------------------------

    def format(self, range_name: str, fmt: dict):
        self.formats.append((range_name, fmt))

    def freeze(self, rows: int = 0, cols: int = 0):
        self.frozen_rows = rows


class FakeSpreadsheet:
    def __init__(self, id: str = "central"):
        self.id = id
        self._ws: dict[str, FakeWorksheet] = {}
        self.batch_updates: list = []

    def worksheets(self):
        return list(self._ws.values())

    def worksheet(self, title: str) -> FakeWorksheet:
        return self._ws[title]

    def add_worksheet(self, title: str, rows: int = 100, cols: int = 20) -> FakeWorksheet:
        ws = FakeWorksheet(title, spreadsheet=self, sheet_id=len(self._ws) + 1,
                            rows=rows, cols=cols)
        self._ws[title] = ws
        return ws

    def batch_update(self, body: dict):
        self.batch_updates.append(body)

    def fetch_sheet_metadata(self, params=None):
        return {"sheets": [
            {"properties": {"sheetId": ws.id}, "conditionalFormats": []}
            for ws in self._ws.values()
        ]}


class FakeClient:
    """کلاینت ساختگیِ gspread: ساخت و بازکردنِ اسپردشیت‌های اختصاصیِ کاربران."""

    def __init__(self):
        self.sheets: dict[str, FakeSpreadsheet] = {}
        self.created: list[tuple[str, str]] = []  # (title, folder_id)
        self._n = 0

    def create(self, title: str, folder_id: str | None = None) -> FakeSpreadsheet:
        self._n += 1
        sheet_id = f"sheet-{self._n}"
        ss = FakeSpreadsheet(id=sheet_id)
        self.sheets[sheet_id] = ss
        self.created.append((title, folder_id or ""))
        return ss

    def open_by_key(self, sheet_id: str) -> FakeSpreadsheet:
        return self.sheets[sheet_id]
