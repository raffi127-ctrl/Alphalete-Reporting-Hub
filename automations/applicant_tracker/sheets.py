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

# Socket timeout for every Sheets call. google-auth's AuthorizedSession ships
# with NO timeout, so a stalled connection blocks forever — and nothing above
# this module was bounded either, which is one of the two ways the 2026-08-18
# morning run burned its whole 25m without printing a single office.
HTTP_TIMEOUT_S = 90

# When True, every WRITE (set_cell / paste_block) is logged but not sent to the
# Sheet -- the reports stay fully exercisable (they still open the browser and
# read ApplicantStream) without touching production data. Set by each entry
# script's --dry-run flag. Reads are always live (harmless).
DRY_RUN = False


def _client():
    creds = Credentials.from_service_account_file(config.SERVICE_ACCOUNT_JSON, scopes=SCOPES)
    gc = gspread.authorize(creds)
    # Give every request a socket timeout (see HTTP_TIMEOUT_S). Best-effort:
    # gspread's internals are not ours, so a shape change degrades to today's
    # behaviour instead of failing the report.
    try:
        sess = gc.session
        if not getattr(sess, "_tracker_timeout_wrapped", False):
            _request = sess.request

            def _timed(method, url, *a, **kw):
                kw.setdefault("timeout", HTTP_TIMEOUT_S)
                return _request(method, url, *a, **kw)

            sess.request = _timed
            sess._tracker_timeout_wrapped = True
    except Exception:  # noqa: BLE001 — a timeout wrapper must never block a run
        pass
    return gc


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


# {(spreadsheet_id, worksheet_id, name_col): {name_lower: row}} for this process.
_NAME_INDEX: dict = {}


def clear_name_index() -> None:
    """Drop the cached name→row maps (call if a run ever writes into a name
    column — nothing does today)."""
    _NAME_INDEX.clear()


def find_row_by_name(ws, full_name: str, name_col: int = 1):
    """Return the 1-based row index whose cell in `name_col` matches full_name
    (case-insensitive, trimmed), or None if not found.

    The name column is read ONCE per run and indexed. It used to be a full
    `col_values` API call PER APPLICANT: 17 offices x every second-round name
    was hundreds of reads of a tab that has grown near Google's 40,207-row grid
    cap, which is slow and burns the 60-reads/minute quota. Safe to cache — no
    phase writes into the name column (morning writes H/I/J, evening AT/AU/R),
    so the mapping can't go stale mid-run."""
    # Key on the live worksheet object (open_tab is called once per run and the
    # handle is reused), plus its sheet id/title so a recycled id can't hand
    # back another tab's index. gspread's own id attributes moved between
    # versions and the mini is on an older one, so don't depend on them.
    key = (id(ws), getattr(ws, "id", None), getattr(ws, "title", None), name_col)
    index = _NAME_INDEX.get(key)
    if index is None:
        index = {}
        for i, v in enumerate(ws.col_values(name_col), start=1):
            k = (v or "").strip().lower()
            if k and k not in index:      # first row wins, as the scan did
                index[k] = i
        _NAME_INDEX[key] = index
    return index.get(full_name.strip().lower())


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


def _ensure_grid(ws, need_row: int, need_col: int) -> None:
    """Grow the worksheet grid so a write to (need_row, need_col) fits. The Call
    List is append-only and grew into Google's grid cap (40,207 rows), so an append
    past it failed `Range … exceeds grid limits` and silently dropped whole offices
    — the 'partial' syncs since 2026-07-24. Adds rows/cols (with a buffer so we're
    not resizing every single append); never removes anything. Best-effort: a
    resize hiccup shouldn't sink the write, which will then surface its own error."""
    try:
        cur_rows = int(getattr(ws, "row_count", 0) or 0)
        cur_cols = int(getattr(ws, "col_count", 0) or 0)
        if need_row > cur_rows:
            ws.add_rows(need_row - cur_rows + 1000)   # +buffer to amortize
        if need_col > cur_cols:
            ws.add_cols(need_col - cur_cols + 2)
    except Exception as e:  # noqa: BLE001
        print(f"    (grid resize skipped: {type(e).__name__}: {e})")


def paste_block(ws, start_row: int, start_col_letter: str, rows: list[list]):
    """Paste a 2-D block of values starting at start_col_letter+start_row."""
    if not rows:
        return
    start = f"{start_col_letter}{start_row}"
    n_cols = max(len(r) for r in rows)
    start_col_idx = gspread.utils.a1_to_rowcol(start)[1]
    end_col = gspread.utils.rowcol_to_a1(1, start_col_idx + n_cols - 1)
    end_col_letter = "".join(c for c in end_col if c.isalpha())
    last_row = start_row + len(rows) - 1
    end = f"{end_col_letter}{last_row}"
    if DRY_RUN:
        print(f"    [dry-run] would paste {len(rows)} row(s) x {n_cols} col(s) "
              f"into {start}:{end}")
        return
    _ensure_grid(ws, last_row, start_col_idx + n_cols - 1)
    ws.update(f"{start}:{end}", rows, value_input_option="USER_ENTERED")
