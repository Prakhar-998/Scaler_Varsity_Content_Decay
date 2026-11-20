"""Google Sheets writer (gspread + service account). Only touches its own spreadsheet."""
from __future__ import annotations

import pandas as pd

from . import tables
from .gsc import credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class Sheet:
    def __init__(self, spreadsheet_id: str):
        import gspread
        self.gc = gspread.authorize(credentials(SCOPES))
        self.ss = self.gc.open_by_key(spreadsheet_id)

    def _ws(self, title: str, rows: int = 100, cols: int = 30):
        import gspread
        try:
            return self.ss.worksheet(title)
        except gspread.WorksheetNotFound:
            return self.ss.add_worksheet(title=title, rows=rows, cols=cols)

    def read(self, title: str) -> list[list]:
        import gspread
        try:
            return self.ss.worksheet(title).get_all_values()
        except gspread.WorksheetNotFound:
            return []

    def write(self, title: str, header: list | None, rows: list[list], freeze_cols: int = 1):
        data = ([header] if header else []) + rows
        width = max((len(r) for r in data), default=1)
        ws = self._ws(title, rows=max(len(data) + 10, 50), cols=max(width, 5))
        ws.clear()
        if ws.col_count < width:
            ws.add_cols(width - ws.col_count)
        if ws.row_count < len(data):
            ws.add_rows(len(data) - ws.row_count)
        if data:
            ws.update(range_name="A1", values=data, value_input_option="USER_ENTERED")
        if header:
            ws.freeze(rows=1, cols=freeze_cols)
            ws.format("1:1", {"textFormat": {"bold": True}, "backgroundColor": {"red": .93, "green": .93, "blue": .96}})


def read_refresh_log(sheet: Sheet, title: str) -> pd.DataFrame:
    vals = sheet.read(title)
    if len(vals) < 2:
        return pd.DataFrame(columns=tables.REFRESH_INPUT_KEYS)
    rows = [r[:5] + [""] * (5 - len(r[:5])) for r in vals[1:] if any(c.strip() for c in r[:5])]
    return pd.DataFrame(rows, columns=tables.REFRESH_INPUT_KEYS)


def read_scope(sheet: Sheet, title: str) -> pd.DataFrame:
    vals = sheet.read(title)
    if len(vals) < 2:
        return pd.DataFrame()
    return pd.DataFrame(vals[1:], columns=vals[0])
