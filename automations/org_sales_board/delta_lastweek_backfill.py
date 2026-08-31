"""Backfill the per-day 'Last week' cells of a delta-box row that was added
AFTER last week's freeze — the daily breakdown a new person never got.

THE RULE THIS ENFORCES (Eve, 2026-08-31, on JAIRO CAPTAINSHIP):
"siempre que agregues a alguien a una capitania y a un delta chart, hay que
backfillear el desglose diario de la semana pasada de estas personas."

WHY THE CELLS ARE EMPTY. In a delta box every day is a THIS WEEK / LAST WEEK /
DELTA triplet. The 'This week' cells are =SUMIFs over the section's daily
table, so somebody added today is populated the same morning. The 'Last week'
cells are NOT formulas — they are last week's numbers FROZEN into place by
Tuesday's rollover (`rollover.plan_delta_rollover`). A row that did not exist
on that Tuesday was never frozen, so its seven per-day 'Last week' cells stay
BLANK and col D ('Total for week' -> Last week, an enumerated =G+J+M+P+S+V+Y)
sums to 0.

WHY THAT IS WORSE THAN IT LOOKS. Nothing errors. The row shows a real week
against 0, its Delta reads a flat 0.00%, and the box's totals row — whose
'Last week' cells are =SUM() over these very cells
([[project_org-board-delta-totals-lastweek-never-rolls]]) — comes out SHORT by
exactly the people who were added. Abdallah Ghousheh and Fernando Munoz had
sold 62 and 67 in the week Jairo's box was comparing against, and it said 0.

WHERE THE NUMBERS COME FROM: `backup_pre_rollover`, the board's own values-only
snapshot taken immediately BEFORE each Tuesday's rollover (rollover.BACKUP_TAB).
In that snapshot the person's delta row still shows last week as 'This week' —
which is, exactly, the cell the freeze would have copied. So this is not a
second opinion about somebody's week, it is the freeze being run late for one
row. No Tableau, no crosstab, no metric to choose: a Fiber box gets the Fiber
number and an NDS box the NDS one, because both come off the same board.

The snapshot only holds the week that just closed, so this has to run before
the next Tuesday overwrites it. It runs daily, inside the board fill.

IT CHECKS THE SNAPSHOT BEFORE IT TRUSTS IT. Every delta row that ALREADY has
its 'Last week' days filled is a known answer: it must equal that person's
'This week' in the snapshot. Those rows are compared first and a mismatch
refuses the whole run — that is what a stale or half-written backup tab looks
like, and it is not something to find out by writing 126 wrong cells.

BLANK IS THE SIGNAL, AND ONLY BLANK. A cell is filled only when it is empty:
empty means "nobody ever froze anything here", a literal 0 means "frozen, and
the answer was zero". So this is idempotent, it can never walk over a
rollover's work, and a row that is already complete costs nothing. A cell
holding a FORMULA is never touched either.

ABSENT IS NOT ZERO. Somebody the snapshot does not carry — a genuinely NEW ICD,
not one moved between captainships — is left blank and NAMED in the log, the
same rule `delta_manual_fill` follows: writing 0 would invent a fact about
their week. Their week has to come off the section's own Tableau view pinned to
that week (see `output/nds_lastweek_pull_2026-08-31.py` for the shape of it).

    python -m automations.org_sales_board.delta_lastweek_backfill          # dry-run
    python -m automations.org_sales_board.delta_lastweek_backfill --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automations.recruiting_report.fill import open_by_key, _retry     # noqa: E402
from automations.org_sales_board.run import SHEET_ID, SANDBOX_TAB      # noqa: E402
from automations.org_sales_board import rollover as ro                 # noqa: E402
from automations.org_sales_board.delta_manual_fill import _cell        # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                                      # noqa: BLE001
    pass

# How many already-frozen rows have to agree with the snapshot before its
# numbers are used for the blank ones. Low enough that a small board still
# calibrates, high enough that it is not one lucky row.
MIN_CALIBRATION_ROWS = 5


def _key(name: str) -> str:
    """Accent- and case-insensitive name key.

    One board can type 'Fernando Munoz' where another types 'Fernando Muñoz'.
    A plain .lower() match misses that and the person is reported as absent —
    which reads exactly like a real 'was not here last week', so the backfill
    would quietly do nothing for the one row it exists for."""
    s = unicodedata.normalize("NFKD", (name or "").strip().lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.split())


def _day_names(grid, table: dict) -> Dict[int, str]:
    """{this-week column -> weekday name}, read off the row ABOVE the header.

    The header row is 'This week / Last week / Delta' repeated seven times with
    nothing in it saying which day a triplet belongs to; the day names sit one
    row up. By label, never by column letter."""
    day_row = table["header_row"] - 1
    out: Dict[int, str] = {}
    for c in table["this_cols"]:
        name = _cell(grid, day_row, c)
        if name:
            out[c] = name
    return out


def box_kind(grid, table: dict) -> str:
    """What a delta box COUNTS, from the sub-label under its own title.

    A person is not enough to key on: Rafael and the five Fiber captains each
    have TWO boxes over the same roster — 'NEW INTERNET UNITS' and 'ALL UNITS'
    — so the same name carries two different (and both correct) sets of
    numbers. Keying on the person alone made 40 of them ambiguous.

    The sub-label sits one row under the box's title row and lives in col A on
    this board, col B on others, so read B then A — the same fallback
    `captainship_drafts.sales_board` uses on these very blocks."""
    hdr = table["header_row"]
    for r in (hdr, hdr - 1):
        txt = (_cell(grid, r, 2) or _cell(grid, r, 1)).upper()
        if "NEW INTERNET" in txt:
            return "NEW INTERNET"
        if "ALL UNITS" in txt or txt.endswith("UNITS"):
            return "ALL UNITS"
    return "ALL UNITS"          # the board's default box, and the NDS/B2B one


def snapshot_index(backup) -> Tuple[Dict[tuple, Dict[str, str]], List[str]]:
    """({(kind, name) -> {day: value}}, ambiguous keys) from the backup.

    Read off the snapshot's own delta boxes, 'This week' side: on that Tuesday
    morning 'This week' WAS the week the live board now calls 'Last week'.

    A key that still lands in two boxes with DIFFERENT numbers is dropped and
    reported rather than guessed at — a captainship box and a cross-cutting one
    (TRANG'S ORG, RAF SPECIAL TEAM) can legitimately count different products
    for the same person, and picking whichever came first would be a coin flip.
    Two boxes that agree are not ambiguous, just duplicated."""
    seen: Dict[tuple, List[Dict[str, str]]] = {}
    manual = {rep for _t, rep in ro.manual_fill_rows(backup)}
    for t in ro.find_delta_tables(backup):
        days = _day_names(backup, t)
        kind = box_kind(backup, t)
        for r in t["data_rows"]:
            name = _cell(backup, r, 2)
            if not name or name.strip().lower() in manual:
                continue        # hand-keyed rows: delta_manual_fill owns them
            got = {d: _cell(backup, r, c) for c, d in days.items()}
            seen.setdefault((kind, _key(name)), []).append(got)
    index: Dict[tuple, Dict[str, str]] = {}
    ambiguous: List[str] = []
    for k, rows in seen.items():
        if all(r == rows[0] for r in rows[1:]):
            index[k] = rows[0]
        else:
            ambiguous.append(f"{k[1]} ({k[0]})")
    return index, ambiguous


def calibrate(grid, index) -> Tuple[int, List[str]]:
    """(rows checked, disagreements) between the live 'Last week' cells that
    ARE filled and the snapshot. The snapshot is only trusted when this is
    clean — see the module docstring."""
    checked, bad = 0, []
    manual = {rep for _t, rep in ro.manual_fill_rows(grid)}
    for t in ro.find_delta_tables(grid):
        days = _day_names(grid, t)
        kind = box_kind(grid, t)
        for r in t["data_rows"]:
            name = _cell(grid, r, 2)
            if not name or name.strip().lower() in manual:
                continue
            src = index.get((kind, _key(name)))
            if not src:
                continue
            pairs = [(days[c], _cell(grid, r, c + 1)) for c in days]
            if any(v == "" for _d, v in pairs):
                continue                       # not fully frozen: nothing to check
            checked += 1
            diff = [f"{d} {v!r}≠{src.get(d, '')!r}" for d, v in pairs
                    if v != src.get(d, "")]
            if diff:
                bad.append(f"{name} (fila {r}): " + ", ".join(diff))
    return checked, bad


def blank_cells(grid, formulas) -> List[dict]:
    """Every delta-box cell that is an EMPTY per-day 'Last week'.

    [{row, name, last_col, day}] — the whole planning input, derived from the
    grid alone so the caller can skip the backup tab when it comes back
    empty."""
    out: List[dict] = []
    manual = {rep for _t, rep in ro.manual_fill_rows(grid)}
    for t in ro.find_delta_tables(grid):
        days = _day_names(grid, t)
        kind = box_kind(grid, t)
        for r in t["data_rows"]:
            name = _cell(grid, r, 2)
            if not name or name.strip().lower() in manual:
                continue
            for c, day in days.items():
                lc = c + 1                     # the triplet's 'Last week'
                if _cell(grid, r, lc) != "":
                    continue                   # frozen already (0 counts)
                if _cell(formulas, r, lc).startswith("="):
                    continue                   # a formula owns this cell
                out.append({"row": r, "name": name, "kind": kind,
                            "last_col": lc, "day": day})
    return out


def plan(cells, index) -> Tuple[List[dict], List[str]]:
    """[{range, values}] for `blank_cells`, plus notes."""
    updates: List[dict] = []
    notes: List[str] = []
    missing: set = set()
    for c in cells:
        src = index.get((c["kind"], _key(c["name"])))
        if src is None:
            if c["name"] not in missing:
                missing.add(c["name"])
                notes.append(
                    f"{c['name']}: no está en el snapshot pre-roleo — es un "
                    f"ICD nuevo, no un pase de capitanía; se deja en blanco "
                    f"(no se escribe 0)")
            continue
        updates.append({"range": f"{ro.a1col(c['last_col'])}{c['row']}",
                        "values": [[src.get(c["day"], 0) or 0]]})
    return updates, notes


def apply_backfill(ws, today: Optional[dt.date] = None,
                   dry_run: bool = False, logfn=print) -> List[dict]:
    """Fill every blank per-day 'Last week' cell on `ws` from the pre-rollover
    snapshot. Reads the grid first and returns before touching the backup tab
    when nothing is blank, so the normal day costs one read."""
    grid = _retry(ws.get_all_values)
    formulas = _retry(lambda: ws.get_all_values(value_render_option="FORMULA"))
    cells = blank_cells(grid, formulas)
    if not cells:
        logfn("  cajas delta: ningún 'Last week' por día en blanco — nada que "
              "backfillear")
        return []

    try:
        bws = ws.spreadsheet.worksheet(ro.BACKUP_TAB)
    except Exception as e:                                    # noqa: BLE001
        logfn(f"  [!] no hay pestaña {ro.BACKUP_TAB!r} ({e}) — no se puede "
              f"backfillear el desglose de la semana pasada")
        return []
    backup = _retry(bws.get_all_values)
    index, ambiguous = snapshot_index(backup)
    for a in ambiguous:
        logfn(f"    [!] {a}: aparece en dos cajas del snapshot con números "
              f"distintos — se deja en blanco")

    checked, disagree = calibrate(grid, index)
    if disagree:
        for d in disagree[:8]:
            logfn(f"    [!] {d}")
        logfn(f"  [!] {ro.BACKUP_TAB!r} NO coincide con las filas ya "
              f"congeladas ({len(disagree)} de {checked}) — snapshot viejo o a "
              f"medio escribir; no se escribe nada")
        return []
    if checked < MIN_CALIBRATION_ROWS:
        logfn(f"  [!] sólo {checked} fila(s) congeladas para verificar el "
              f"snapshot (hacen falta {MIN_CALIBRATION_ROWS}) — no se escribe "
              f"nada")
        return []
    logfn(f"  snapshot {ro.BACKUP_TAB!r} verificado contra {checked} fila(s) "
          f"ya congeladas")

    updates, notes = plan(cells, index)
    for n in notes:
        logfn(f"    [!] {n}")
    for u in updates:
        logfn(f"    {u['range']} ← {u['values'][0][0]}")
    if updates and not dry_run:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    logfn(f"  'Last week' por día backfilleado: {len(updates)} celda(s)"
          + (" (dry-run)" if dry_run else " escritas" if updates else ""))
    return updates


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="completa el desglose diario de 'Last week' de las filas "
                    "que se agregaron a una caja delta después del roleo")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--tab", default=SANDBOX_TAB)
    ap.add_argument("--today", default=None, help="YYYY-MM-DD")
    args = ap.parse_args(argv)
    today = (dt.date.fromisoformat(args.today) if args.today
             else dt.date.today())
    print(f"=== backfill 'Last week' por día — {args.tab!r} — "
          f"{'APPLY' if args.apply else 'DRY-RUN'} ===")
    ws = _retry(lambda: open_by_key(SHEET_ID).worksheet(args.tab))
    apply_backfill(ws, today=today, dry_run=not args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
