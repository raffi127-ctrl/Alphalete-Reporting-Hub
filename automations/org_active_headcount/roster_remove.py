"""Take an owner OFF the 'Org Active Headcount' tab (all three people blocks).

Eve, 2026-11-24: Ana Griffin left the ORG Sales Board and All Campaigns on
2026-09-15 (two-week zero rule) but sat on this tab for two more months at 0,
because nothing ever removed a row here — the ORG board's roster_remove
cascaded to All Campaigns only. "si, sacala y arreglá el script".

The mirror of roster_add: the same three blocks, found the same way
(daily.find_ongoing / find_daily / find_delta, by name — never by row number):

  1. ongoing weekly   2. daily   3. delta box

Rows are deleted bottom-up in ONE batch, after a values snapshot of the whole
tab into BACKUP_TAB (must succeed, or nothing is deleted). Every total, SUMIF
and CHOOSECOLS on the tab shrinks by itself on a row delete; the col-A ranks
are =A{above}+1 / ROW()-based, so they renumber themselves too.

Called by org_sales_board.roster_remove's cascade, only for a name that is now
COMPLETELY off the ORG board (same condition as All Campaigns: one Headcount
line is the person across every campaign they sell).

    python -m automations.org_active_headcount.roster_remove --names "Ana Griffin"           # dry run
    python -m automations.org_active_headcount.roster_remove --names "Ana Griffin" --apply

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import List, Optional, Tuple

from automations.recruiting_report.fill import _retry
from automations.org_active_headcount import daily as dl

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:                                                  # noqa: BLE001
    pass

BACKUP_TAB = "backup_pre_remove_headcount"


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def plan(V, names: List[str]) -> List[Tuple[int, str, str]]:
    """(row, block, name) for every row of `names` in the three blocks,
    bottom-up (the order they must be deleted in)."""
    want = {_norm(n) for n in names}
    out: List[Tuple[int, str, str]] = []
    og = dl.find_ongoing(V)
    out += [(r, "semanal", dl._c(V, r, 2)) for r in og["rows"]
            if _norm(dl._c(V, r, 2)) in want]
    dd = dl.find_daily(V)
    out += [(r, "diario", n) for r, n, _camp in dd["rows"] if _norm(n) in want]
    de = dl.find_delta(V)
    out += [(r, "delta", n) for r, n in de["rows"] if _norm(n) in want]
    return sorted(out, key=lambda t: -t[0])


def _snapshot(ws, V, logfn=print) -> None:
    rows, cols = len(V), max((len(r) for r in V), default=1)
    sh = ws.spreadsheet
    try:
        bws = sh.worksheet(BACKUP_TAB)
    except Exception:                                              # noqa: BLE001
        bws = sh.add_worksheet(title=BACKUP_TAB, rows=max(rows, 1), cols=max(cols, 1))
    bws.resize(rows=max(rows, 1), cols=max(cols, 1))
    rect = [r + [""] * (cols - len(r)) for r in V]
    _retry(lambda: bws.update(range_name="A1", values=rect, value_input_option="RAW"))
    logfn(f"  snapshot -> {BACKUP_TAB!r} ({dt.datetime.now():%Y-%m-%d %H:%M})")


def remove(names: List[str], apply: bool = False, ws=None, logfn=print) -> int:
    """Returns how many rows were (or would be) deleted."""
    ws = ws or dl.open_tab()
    V = _retry(ws.get_all_values)
    hits = plan(V, names)
    for r, block, n in sorted(hits):
        logfn(f"  headcount r{r:<5} {block:<8} {n}")
    found = {_norm(n) for _r, _b, n in hits}
    missing = [n for n in names if _norm(n) not in found]
    if missing:
        logfn(f"  headcount: sin filas para {', '.join(missing)}")
    if not hits:
        return 0
    if not apply:
        logfn(f"  headcount: {len(hits)} fila(s) se borrarían — dry-run, nada escrito")
        return len(hits)
    _snapshot(ws, V, logfn)
    reqs = [{"deleteDimension": {"range": {"sheetId": ws.id, "dimension": "ROWS",
                                           "startIndex": r - 1, "endIndex": r}}}
            for r, _b, _n in hits]                                 # bottom-up
    _retry(lambda: ws.spreadsheet.batch_update({"requests": reqs}))
    left = plan(_retry(ws.get_all_values), names)
    logfn(f"  headcount: borradas {len(reqs)} fila(s); quedan {len(left)}"
          f"{' — revisar' if left else ' (ok)'}")
    return len(reqs)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="org_active_headcount.roster_remove")
    ap.add_argument("--names", required=True, help="Pipe-separated, as in col B.")
    ap.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    ap.add_argument("--sandbox", action="store_true", help="the SANDBOX copy of the tab")
    a = ap.parse_args(argv)
    names = [n.strip() for n in a.names.split("|") if n.strip()]
    remove(names, apply=a.apply, ws=dl.open_tab(sandbox=a.sandbox))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
