"""Fill the delta-box rows that have no daily table to sum — every day, by itself.

WHO THIS IS FOR. A cross-cutting delta box (TRANG'S ORG, RAF SPECIAL TEAM)
carries people from several captains' rosters, and each row is a =SUMIF over
whichever daily table that person actually sits in. A few of them sit in NONE:
they have no row anywhere else on the board, so there is no range to sum and
their per-day cells are plain numbers. Jacob Morgan is the standing case — a rep
under owner 'Jess Lieberman', not an ICD, so the board's daily tables (which are
ICD-level) have nowhere to put him.

WHY IT IS AUTOMATED. Those numbers were keyed in by hand off Tableau's PRODUCT
SALES SUMMARY, every single day. A daily manual step that nobody is paged about
is a daily step that eventually doesn't happen, and its failure mode is silent:
the row reads 0, the box's totals row sums it happily, and the org total is short
with nothing anywhere saying so. Eve, 2026-08-26: "no te voy a recordar todos los
días". So the daily fill does it.

WHO GETS FILLED IS DERIVED, NOT LISTED. `rollover.manual_fill_rows` marks a rep
whose ONLY appearance in col B of the whole tab is their delta row — that is
exactly "has no daily table of their own". Add such a person to a cross-cutting
box tomorrow and they are picked up with no code edit; give one of them a real
daily row and they drop out the same day, because then the =SUMIF works and the
row stops being manual.

THE NUMBER. All Units — every product type — for that ONE day, the same rule the
rest of the box follows (verified 2026-08-26 against the ten formula rows of
TRANG'S ORG: nine matched exactly on both elapsed days). Looked up as an OWNER
first, since that is what a normal board row means, and only then as a REP: the
people who land here are usually individual contributors, but the next one might
be an owner and the board's own convention has to win.

WHAT IT REFUSES TO DO. A rep the crosstab does not mention at all is left alone
and reported — absent is not the same as zero, and writing 0 would invent a fact
about somebody's day. A cell that currently holds a formula is never overwritten:
if a =SUMIF appeared there, that person got a daily table and this module has no
business in their row. Only days the crosstab actually carries are written.

    python -m automations.org_sales_board.delta_manual_fill            # dry-run
    python -m automations.org_sales_board.delta_manual_fill --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automations.recruiting_report.fill import open_by_key, _retry     # noqa: E402
from automations.org_sales_board.run import SHEET_ID, SANDBOX_TAB      # noqa: E402
from automations.org_sales_board import rollover as ro                 # noqa: E402
from automations.org_sales_board import week as wk                     # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                                      # noqa: BLE001
    pass


def _cell(grid, r1: int, c1: int) -> str:
    row = grid[r1 - 1] if 0 < r1 <= len(grid) else []
    return str(row[c1 - 1]).strip() if 0 < c1 <= len(row) else ""


def _num(v) -> int:
    s = str(v).replace(",", "").strip()
    if not s:
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def per_day_all_units(path: Path, days: List[str]) -> Tuple[dict, dict]:
    """({owner: {day: units}}, {rep: {day: units}}) from a PSS crosstab.

    Both levels come out of one read because which one a manual row means is
    not knowable in advance — see the module docstring. Every product type is
    summed: 'Apps' on this board is the high-level count, not a breakout.
    """
    from automations.weekly_knock_dispositions import apps as A
    rows = A._read_tsv(path)
    if not rows:
        raise RuntimeError(f"PSS crosstab {path} is empty.")
    headers = [h.strip() for h in rows[0]]
    try:
        o_col, r_col = headers.index("Owner Name"), headers.index("Rep")
    except ValueError:
        raise RuntimeError(f"PSS crosstab missing 'Owner Name'/'Rep': {headers}")
    day_cols = {d: headers.index(d) for d in days if d in headers}
    by_owner: Dict[str, Dict[str, int]] = {}
    by_rep: Dict[str, Dict[str, int]] = {}
    for r in rows[1:]:
        if len(r) < 4:
            continue
        owner = (r[o_col] or "").strip()
        rep = (r[r_col] or "").strip()
        ptype = (r[2] or "").strip().upper()
        if ptype in ("", "TOTAL") or rep.lower() == "total":
            continue
        for who, bucket in ((owner, by_owner), (rep, by_rep)):
            if not who:
                continue
            d = bucket.setdefault(who.lower(), {})
            for day, i in day_cols.items():
                d[day] = d.get(day, 0) + (_num(r[i]) if i < len(r) else 0)
    return by_owner, by_rep


def plan(grid, formulas, path: Path, today: dt.date,
         logfn=print) -> Tuple[List[dict], List[str]]:
    """[{range, values}] for the manual rows' completed days, plus notes."""
    from automations.weekly_knock_dispositions import apps as A

    manual = {rep for _t, rep in ro.manual_fill_rows(grid)}
    notes: List[str] = []
    if not manual:
        return [], ["no hay filas de relleno manual en el board"]

    completed = wk.completed_days(today)
    days = [A.day_name(d) for d in completed]
    if not days:
        return [], ["ningún día cerrado todavía esta semana"]
    by_owner, by_rep = per_day_all_units(path, days)

    updates: List[dict] = []
    for t in ro.find_delta_tables(grid):
        tw = sorted(t["this_cols"])
        for r in t["data_rows"]:
            rep = _cell(grid, r, 2)
            if rep.strip().lower() not in manual:
                continue
            # A row whose cells are FORMULAS is not manual, whatever the
            # col-B heuristic says. `manual_fill_rows` keys on the label being
            # unique on the tab, and a label can be unique for a reason that
            # has nothing to do with this: RAF SPECIAL TEAM writes Aya's name
            # without the hyphen ("Aya Alkhafaji") while her daily table has
            # "Aya Al-Khafaji", so her label looks one-of-a-kind — but her
            # =SUMIF carries the hyphenated spelling and works. The formula is
            # the authority on whether a row has a source; the label is not.
            if _cell(formulas, r, tw[0]).startswith("="):
                continue
            src = (by_owner.get(rep.strip().lower())
                   or by_rep.get(rep.strip().lower()))
            if src is None:
                notes.append(f"{rep}: no figura en el Product Sales de esta "
                             f"semana — se deja como está (no se escribe 0)")
                continue
            level = ("owner" if rep.strip().lower() in by_owner else "rep")
            for day, col in zip(days, tw):
                if _cell(formulas, r, col).startswith("="):
                    notes.append(f"{rep} {ro.a1col(col)}{r}: tiene fórmula — "
                                 f"ya no es manual, no se toca")
                    continue
                want, cur = src.get(day, 0), _num(_cell(grid, r, col))
                if want != cur:
                    updates.append({"range": f"{ro.a1col(col)}{r}",
                                    "values": [[want]]})
                    logfn(f"    {ro.a1col(col)}{r} {rep} ({level}) {day}: "
                          f"{cur} → {want}")
    return updates, notes


def apply_manual_fill(ws, today: Optional[dt.date] = None,
                      dry_run: bool = False, logfn=print) -> List[dict]:
    """Download the week's crosstab and fill the manual delta rows on `ws`."""
    from automations.weekly_knock_dispositions import apps as A
    today = today or dt.date.today()
    we_sunday = wk.reporting_sunday(today)
    path = A.download(we_sunday, verbose=False)
    grid = _retry(ws.get_all_values)
    formulas = _retry(lambda: ws.get_all_values(value_render_option="FORMULA"))
    updates, notes = plan(grid, formulas, path, today, logfn=logfn)
    for n in notes:
        logfn(f"    [!] {n}")
    if updates and not dry_run:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    logfn(f"  filas manuales de las cajas delta: {len(updates)} celda(s)"
          + (" (dry-run)" if dry_run else " escritas" if updates else ""))
    return updates


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="completa las filas de las cajas delta que no tienen "
                    "tabla diaria, desde el Product Sales Summary")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--tab", default=SANDBOX_TAB)
    ap.add_argument("--today", default=None, help="YYYY-MM-DD")
    args = ap.parse_args(argv)
    today = (dt.date.fromisoformat(args.today) if args.today
             else dt.date.today())
    print(f"=== relleno manual de cajas delta — {args.tab!r} — "
          f"{'APPLY' if args.apply else 'DRY-RUN'} ===")
    ws = _retry(lambda: open_by_key(SHEET_ID).worksheet(args.tab))
    apply_manual_fill(ws, today=today, dry_run=not args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
