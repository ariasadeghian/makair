"""اسپردشیت ساختگی برای تست‌ها (بدون اتصال به اینترنت).

رفتار حداقلیِ لازم از gspread را در حافظه شبیه‌سازی می‌کند: ``worksheets``،
``worksheet``، ``add_worksheet`` و روی هر تب ``get_all_values``،
``get_all_records``، ``append_row``، ``clear`` و ``update``.
"""
from __future__ import annotations


def _cell(x) -> str:
    return "" if x is None else str(x)


class FakeWorksheet:
    def __init__(self, title: str):
        self.title = title
        self._values: list[list[str]] = []  # سطر اول = هدر

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

    def append_row(self, row):
        self._values.append([_cell(x) for x in row])

    def append_rows(self, rows):
        for r in rows:
            self.append_row(r)

    def clear(self):
        self._values = []

    def update(self, values, value_input_option=None, range_name=None):
        self._values = [[_cell(x) for x in row] for row in values]


class FakeSpreadsheet:
    def __init__(self):
        self._ws: dict[str, FakeWorksheet] = {}

    def worksheets(self):
        return list(self._ws.values())

    def worksheet(self, title: str) -> FakeWorksheet:
        return self._ws[title]

    def add_worksheet(self, title: str, rows: int = 100, cols: int = 20) -> FakeWorksheet:
        ws = FakeWorksheet(title)
        self._ws[title] = ws
        return ws
