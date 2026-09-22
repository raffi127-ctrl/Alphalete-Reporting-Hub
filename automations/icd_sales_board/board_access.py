"""One access code per ICD, so each owner's link opens ONLY their own office.

The public board used to have a single code, and that code opened every
office — Raf's link showed all sixteen offices' reps and daily numbers. For
"every ICD has their own live board" (Megan 2026-09-22) each owner needs a
code that is theirs.

WHERE THE CODES LIVE. A 'Board Access' tab in the automation workbook — never
the repo, and never a secrets file somebody has to hand-edit per office. The
Cloud app already reads that workbook for the board's own numbers, so it can
read this too. Megan can see every code in one place, copy one, send it.

NEVER OVERWRITTEN. seed() only fills in ICDs that have no code yet. Rotating a
code is a deliberate edit in the sheet — a re-run must never silently lock out
an owner who already has theirs.

    python -m automations.icd_sales_board.board_access --list
    python -m automations.icd_sales_board.board_access --seed
"""
from __future__ import annotations

import datetime as dt
import re
import secrets
import time

from automations.icd_sales_board import tableau_days as TD

SHEET_ID = TD.SHEET_ID
TAB = "Board Access"
COLUMNS = ["ICD", "Code", "Created"]

# No 0/O, 1/l/I: a code gets read out over the phone and typed on one.
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"

_CACHE: dict = {"at": 0.0, "codes": None}
_TTL = 120


def make_code(icd: str) -> str:
    """'rafael-7k2m' — the owner's first name, then four random characters.

    The name makes it recognisable to the person who receives it; the random
    part is what makes it a key. secrets, not random, because it is one."""
    first = re.sub(r"[^a-z]", "", (icd or "office").split()[0].lower()) \
        or "office"
    return f"{first}-" + "".join(secrets.choice(_ALPHABET) for _ in range(4))


def _tab(create: bool = False):
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(SHEET_ID)
    try:
        return sh.worksheet(TAB)
    except Exception:   # noqa: BLE001 — gspread's WorksheetNotFound
        if not create:
            return None
        ws = sh.add_worksheet(title=TAB, rows=200, cols=len(COLUMNS))
        ws.update(values=[COLUMNS], range_name="A1")
        return ws


def _grid() -> list:
    from automations.recruiting_report.fill import _retry
    ws = _tab()
    return (_retry(ws.get_all_values) or []) if ws else []


def codes(force: bool = False) -> dict:
    """{code lowered: ICD name}. Cached briefly — the gate asks on every page
    load and the tab changes a few times a month."""
    if (not force and _CACHE["codes"] is not None
            and time.time() - _CACHE["at"] < _TTL):
        return _CACHE["codes"]
    out: dict = {}
    grid = _grid()
    if grid:
        head = [str(h).strip() for h in grid[0]]
        if "ICD" in head and "Code" in head:
            i_icd, i_code = head.index("ICD"), head.index("Code")
            for row in grid[1:]:
                if len(row) <= max(i_icd, i_code):
                    continue
                icd, code = str(row[i_icd]).strip(), str(row[i_code]).strip()
                if icd and code:
                    out[code.lower()] = icd
    _CACHE.update(at=time.time(), codes=out)
    return out


def seed(icds, log=print) -> list:
    """Give every ICD without a code one. -> [(icd, code) added].

    Existing rows are kept exactly as they are, so this is safe to run as
    often as offices are added."""
    from automations.recruiting_report.fill import _retry
    ws = _tab(create=True)
    grid = _retry(ws.get_all_values) or [COLUMNS]
    head = [str(h).strip() for h in grid[0]]
    i_icd = head.index("ICD") if "ICD" in head else 0
    have = {str(r[i_icd]).strip().lower() for r in grid[1:]
            if len(r) > i_icd and str(r[i_icd]).strip()}
    taken = {c for c in codes(force=True)}

    today = dt.date.today().isoformat()
    added = []
    for icd in sorted({str(i).strip() for i in icds if str(i).strip()}):
        if icd.lower() in have:
            continue
        code = make_code(icd)
        while code.lower() in taken:
            code = make_code(icd)
        taken.add(code.lower())
        added.append((icd, code))
    if added:
        # One append for the lot — a row-at-a-time loop is what 429s the
        # quota for whoever writes next.
        _retry(ws.append_rows, [[i, c, today] for i, c in added],
               value_input_option="RAW")
        codes(force=True)
    log(f"board access: {len(added)} code(s) added, {len(have)} kept")
    return added


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="board_access")
    ap.add_argument("--seed", action="store_true",
                    help="Add a code for every ICD that has none.")
    ap.add_argument("--list", action="store_true", help="Print every code.")
    a = ap.parse_args(argv)

    if a.seed:
        from automations.icd_sales_board import profiles as P
        seed(P.load().keys())
    if a.list or not a.seed:
        for code, icd in sorted(codes(force=True).items(),
                                key=lambda kv: kv[1]):
            print(f"  {icd:28} {code}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
