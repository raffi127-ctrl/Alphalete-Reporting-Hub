"""Read and write one office's row on the `Office Settings` tab.

BY COLUMN NAME, ALWAYS. That tab gained an `Owner` column from another session
on 2026-11-06 and a positional read returned the wrong cell in silence. It is
also shared: office_admin writes State and City for Sterling, icd_onboarding
reads Blue Ink and Rate of Pay, and apex reads the eight pay answers. So a
write touches ONLY the columns it was given and leaves every other cell alone.

MISSING COLUMNS ARE CREATED, not assumed. `Blue Ink` and `Rate of Pay` were
read by the code and absent from the sheet until 2026-11-19 -- the answer was
impossible to give. Adding a header is the one structural change this makes,
and it appends to the right of what is there so nothing shifts under anybody.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Tuple

from automations.eco_onboarding import settings as S


def _book(book=None):
    if book is not None:
        return book
    from automations.icd_alerts import post as P
    from automations.recruiting_report.fill import open_by_key
    return open_by_key(P.RELAY_SPREADSHEET_ID)


def _sheet(book=None):
    return _book(book).worksheet(S.TAB)


def headers(ws) -> List[str]:
    return [str(h).strip() for h in ws.row_values(1)]


def ensure_columns(ws, log=print) -> List[str]:
    """Add any column this form writes that the tab does not carry. Returns
    the ones added, so a run says what it changed rather than only that it
    succeeded."""
    have = headers(ws)
    missing = S.missing_columns(have)
    if not missing:
        return []
    start = len(have) + 1
    ws.update(
        values=[missing],
        range_name="%s1:%s1" % (_a1(start), _a1(start + len(missing) - 1)))
    log("added column(s): %s" % ", ".join(missing))
    return missing


def _a1(n: int) -> str:
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def find_row(ws, office_key: str) -> Optional[int]:
    """The 1-indexed row for this office, or None. Case and space insensitive
    -- the tab holds '  Vincent ' as readily as 'vincent'."""
    want = str(office_key or "").strip().lower()
    if not want:
        return None
    have = headers(ws)
    if S.COL_OFFICE not in have:
        return None
    col = have.index(S.COL_OFFICE) + 1
    for i, said in enumerate(ws.col_values(col), start=1):
        if i == 1:
            continue
        if str(said).strip().lower() == want:
            return i
    return None


def read(office_key: str, book=None) -> Dict[str, str]:
    """{column: value} for one office, or {} when the office has no row."""
    ws = _sheet(book)
    row = find_row(ws, office_key)
    if row is None:
        return {}
    have = headers(ws)
    vals = ws.row_values(row)
    return {h: (vals[i] if i < len(vals) else "")
            for i, h in enumerate(have) if h}


def save(office_key: str, row: Dict[str, str], *, book=None,
         dry_run: bool = True, log=print) -> Tuple[bool, str]:
    """Write one office's answers. (changed, what happened).

    ONLY THE COLUMNS GIVEN. Everything else on that row belongs to somebody
    else -- Sterling's updater, the AppStream list, the onboarding sheet link
    -- and a full-row write is how one form quietly erases another's work.
    """
    key = str(office_key or "").strip()
    if not key:
        return (False, "no office key")
    ws = _sheet(book)
    if not dry_run:
        ensure_columns(ws, log=log)
    have = headers(ws)
    at = find_row(ws, key)
    if at is None:
        if dry_run:
            return (False, "would add a new row for %r" % key)
        ws.append_row([key] + [""] * (len(have) - 1),
                      value_input_option="USER_ENTERED")
        at = find_row(ws, key)
        if at is None:
            return (False, "could not add a row for %r" % key)
    writes = []
    for column, value in row.items():
        if column not in have:
            if dry_run:
                writes.append("%s=%r (new column)" % (column, value))
                continue
            return (False, "the tab has no %r column" % column)
        cell = "%s%d" % (_a1(have.index(column) + 1), at)
        writes.append("%s=%r" % (column, value))
        if not dry_run:
            ws.update(values=[[value]], range_name=cell)
    what = "row %s · %s" % (at, "; ".join(writes))
    if dry_run:
        return (False, "DRY RUN · would write " + what)
    log("wrote " + what)
    return (True, "saved " + what)


def stamp() -> str:
    return dt.datetime.now().strftime("%-m/%-d/%Y %H:%M:%S"
                                      if _supports_dash() else "%m/%d/%Y %H:%M:%S")


def _supports_dash() -> bool:
    """`%-m` is glibc/BSD only; Windows wants `%#m`. Built by hand rather than
    guessed at, because every report here has to run on both."""
    try:
        dt.datetime.now().strftime("%-m")
        return True
    except ValueError:
        return False


def offices(book=None) -> List[str]:
    """Every office key already on the tab, A-Z.

    The form offers these rather than asking somebody to TYPE their key: a
    typed key that does not match creates a second row for an office that
    already has one, and nothing downstream would ever look at it. It also
    means the form works without the owner pressing Enter, which is the whole
    reason the first version appeared to do nothing.
    """
    try:
        ws = _sheet(book)
        have = headers(ws)
        if S.COL_OFFICE not in have:
            return []
        col = have.index(S.COL_OFFICE) + 1
        said = [str(v).strip() for v in ws.col_values(col)[1:]]
        return sorted({v for v in said if v}, key=str.lower)
    except Exception:          # noqa: BLE001
        return []
