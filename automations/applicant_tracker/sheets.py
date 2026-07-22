"""Thin wrapper around gspread for the Applicant Tracker spreadsheet.

Reading/writing Google Sheets is done through the official API, so it's
reliable and needs no browser. Auth uses a service-account key file
(see README step 3) -- share the spreadsheet with the service-account email.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import gspread
from google.oauth2.service_account import Credentials

from . import config

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# When True, every WRITE (set_cell / paste_block) is logged but not sent to the
# Sheet -- the reports stay fully exercisable (they still open the browser and
# read ApplicantStream) without touching production data. Set by each entry
# script's --dry-run flag. Reads are always live (harmless).
DRY_RUN = False


def _client():
    creds = Credentials.from_service_account_file(config.SERVICE_ACCOUNT_JSON, scopes=SCOPES)
    return gspread.authorize(creds)


def open_tab(tab_name: str):
    """Return a gspread Worksheet for the given tab of the tracker spreadsheet."""
    sh = _client().open_by_key(config.SPREADSHEET_KEY)
    return sh.worksheet(tab_name)


def read_as_credentials() -> tuple[str, str]:
    """Read the ApplicantStream username/password from the README tab
    (B1 = username, B2 = password). Falls back to config env vars if empty."""
    ws = open_tab(config.TAB_README)
    user = (ws.acell(config.README_USERNAME_CELL).value or "").strip()
    pwd = (ws.acell(config.README_PASSWORD_CELL).value or "").strip()
    if not user:
        user = config.AS_USERNAME
    if not pwd:
        pwd = config.AS_PASSWORD
    return user, pwd


def find_row_by_name(ws, full_name: str, name_col: int = 1):
    """Return the 1-based row index whose cell in `name_col` matches full_name
    (case-insensitive, trimmed), or None if not found."""
    target = full_name.strip().lower()
    values = ws.col_values(name_col)
    for i, v in enumerate(values, start=1):
        if v.strip().lower() == target:
            return i
    return None


def set_cell(ws, row: int, col_letter: str, value):
    """Write a value to e.g. row 42, column 'R'."""
    if DRY_RUN:
        print(f"    [dry-run] would set {col_letter}{row} = {value!r}")
        return
    ws.update_acell(f"{col_letter}{row}", value)


def first_empty_row_in_column(ws, col_letter: str) -> int:
    """1-based index of the first empty cell in a column (for append-style writes)."""
    col_index = gspread.utils.a1_to_rowcol(f"{col_letter}1")[1]
    values = ws.col_values(col_index)
    return len(values) + 1


def paste_block(ws, start_row: int, start_col_letter: str, rows: list[list]):
    """Paste a 2-D block of values starting at start_col_letter+start_row."""
    if not rows:
        return
    start = f"{start_col_letter}{start_row}"
    n_cols = max(len(r) for r in rows)
    end_col = gspread.utils.rowcol_to_a1(1, gspread.utils.a1_to_rowcol(start)[1] + n_cols - 1)
    end_col_letter = "".join(c for c in end_col if c.isalpha())
    end = f"{end_col_letter}{start_row + len(rows) - 1}"
    if DRY_RUN:
        print(f"    [dry-run] would paste {len(rows)} row(s) x {n_cols} col(s) "
              f"into {start}:{end}")
        return
    ws.update(f"{start}:{end}", rows, value_input_option="USER_ENTERED")
