"""Step 7 — copy the week's PNL into `Raf PNL 2026`.

The week's commission workbook has a `PNL` tab (REP / LEVEL / BROUGHT IN /
PAYOUT / PROFIT-LOSS). The year grid in "All in One Local Office - Raf" has one
three-column block per week — `Brought In`, `Got Paid`, `Profit/Loss` under a
`WE <M/D>` banner in row 1 — and one row per person, split into First Name
(col E) and Last Name (col F).

What this does, per JD's Loom 2026-09-03:
  * finds the week's block by its `WE M/D` BANNER, never by column position
    (53 blocks across the year; the week ending comes from PNL!A1)
  * matches each rep to a row on First+Last, and writes Brought In / Got Paid
  * flips `Current Employee Y or N` from N to Y for anyone who has money this
    week — a rep who left months ago still gets paid on a late activation, and
    JD needs them visible
  * drops anyone it cannot place into the spare `EXTRA` rows at the bottom of
    the grid with their first/last name filled in, leaving Team for JD

What it deliberately does NOT do:
  * write `Profit/Loss` — that column is a live `=SUM(DEn)-(DFn*1.12)` formula
  * clear or blank ANY cell. The week's block already carries JD's hand-typed
    Partner Pay / Chef / Food Cost lines, which the commission PNL knows nothing
    about; a "clean rebuild" of the block would silently delete them. Only cells
    belonging to a matched rep are written, and any that already held a
    different value are reported.

    python -m automations.commission_sheet.pnl              # dry run
    python -m automations.commission_sheet.pnl --write
    python -m automations.commission_sheet.pnl --hide-inactive
"""
from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from automations.commission_sheet import config as C
from automations.commission_sheet.names import match_person, nrm

#: Row 3 is the first person; the rep block ends before the spare EXTRA rows.
FIRST_REP_ROW = 3
#: Column A of a spare row reads this. They are JD's overflow slots.
EXTRA_MARKER = "EXTRA"
#: Google Sheets' serial-date epoch.
_EPOCH = dt.date(1899, 12, 30)


@dataclass
class Row:
    rep: str
    brought: Optional[float]
    paid: Optional[float]
    target_row: int = 0
    target_name: str = ""
    note: str = ""
    overwrites: List[str] = field(default_factory=list)


@dataclass
class Plan:
    week: dt.date
    banner: str
    brought_col: str
    paid_col: str
    matched: List[Row] = field(default_factory=list)
    extras: List[Row] = field(default_factory=list)
    ambiguous: List[Row] = field(default_factory=list)
    unplaced: List[Row] = field(default_factory=list)
    flips: List[Row] = field(default_factory=list)


def col_letter(idx0: int) -> str:
    n, out = idx0 + 1, ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def _as_date(value) -> dt.date:
    """PNL!A1 holds the week ending, as a serial number or a printed date."""
    if isinstance(value, (int, float)):
        return _EPOCH + dt.timedelta(days=int(value))
    text = str(value or "").strip()
    for fmt in ("%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot read a week-ending date from PNL!A1: {value!r}")


def banner_for(week: dt.date) -> str:
    """"WE 8/30" — no zero padding, and built by hand because %-m is
    Mac-only and these reports run on Windows too."""
    return f"WE {week.month}/{week.day}"


def _num(value) -> Optional[float]:
    if value in ("", None):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("$", "").replace(",", "").strip()
    if not text or text.startswith("#"):
        return None
    try:
        return float(text.strip("()")) * (-1 if text.startswith("(") else 1)
    except ValueError:
        return None


def _source_rows(workbook_id: str) -> Tuple[dt.date, List[Row]]:
    from automations.recruiting_report.fill import open_by_key
    ws = open_by_key(workbook_id).worksheet(C.TAB_PNL)
    grid = ws.get("A1:E400", value_render_option="UNFORMATTED_VALUE")
    week = _as_date(grid[0][0] if grid and grid[0] else "")
    out: List[Row] = []
    for raw in grid[4:]:                       # data starts at row 5
        cells = list(raw) + [""] * 5
        rep = str(cells[0]).strip()
        # The rep column is a spilled SORT(); its tail carries #N/A noise.
        if not rep or rep.startswith("#"):
            continue
        out.append(Row(rep=rep, brought=_num(cells[2]), paid=_num(cells[3])))
    return week, out


def _target(all_in_one_id: str):
    from automations.recruiting_report.fill import open_by_key
    return open_by_key(all_in_one_id).worksheet(C.TAB_YEAR_PNL)


def analyze(workbook_id: str = C.WORKBOOK_ID,
            all_in_one_id: str = C.ALL_IN_ONE_ID) -> Plan:
    week, source = _source_rows(workbook_id)
    ws = _target(all_in_one_id)

    banner = banner_for(week)
    header = ws.get("A1:GZ1")[0]
    hits = [i for i, c in enumerate(header) if nrm(c) == nrm(banner)]
    if not hits:
        have = [c for c in header if str(c).strip().upper().startswith("WE ")]
        raise KeyError(f"No {banner!r} banner on {C.TAB_YEAR_PNL}. Weeks present: {have}")
    if len(hits) > 1:
        raise KeyError(f"{banner!r} appears {len(hits)} times on {C.TAB_YEAR_PNL}")
    base = hits[0]
    plan = Plan(week=week, banner=banner,
                brought_col=col_letter(base), paid_col=col_letter(base + 1))

    # People, plus whatever the week's block already holds. The scan stops at
    # the end of column A: below the rep block the tab carries other sections
    # (a name lookup list, summary totals) that also have names in E/F, and
    # matching a rep into one of those would pay into a dead row.
    people = ws.get(f"A{FIRST_REP_ROW}:F600")
    last_rep_off = max((i for i, raw in enumerate(people)
                        if str((list(raw) + [""])[0]).strip()), default=-1)
    people = people[:last_rep_off + 1]
    block = ws.get(f"{plan.brought_col}{FIRST_REP_ROW}:{plan.paid_col}600")

    by_name: Dict[str, List[int]] = {}
    roster: List[str] = []
    row_name: Dict[int, str] = {}
    current: Dict[int, str] = {}
    free_extras: List[int] = []
    for off, raw in enumerate(people):
        r = FIRST_REP_ROW + off
        cells = list(raw) + [""] * 6
        flag = str(cells[0]).strip()
        first, last = str(cells[4]).strip(), str(cells[5]).strip()
        full = " ".join(x for x in (first, last) if x)
        if flag.upper() == EXTRA_MARKER and not full:
            free_extras.append(r)
            continue
        if not full:
            continue
        by_name.setdefault(nrm(full), []).append(r)
        row_name[r] = full
        current[r] = flag
        roster.append(full)

    def existing(r: int) -> Tuple[str, str]:
        off = r - FIRST_REP_ROW
        cells = (list(block[off]) + ["", ""]) if off < len(block) else ["", ""]
        return str(cells[0]).strip(), str(cells[1]).strip()

    for row in source:
        rows = by_name.get(nrm(row.rep), [])
        if not rows:
            guess, cands = match_person(row.rep, roster)
            if guess:
                rows = by_name.get(nrm(guess), [])
                row.note = f"matched to {guess!r}"
            elif cands:
                row.note = f"closest on the grid: {cands}"
        if len(rows) > 1:
            row.note = f"{len(rows)} rows share this name — rows {rows}"
            plan.ambiguous.append(row)
            continue
        if not rows:
            if free_extras:
                row.target_row = free_extras.pop(0)
                row.note = (row.note + "; " if row.note else "") + "new — into a spare EXTRA row"
                plan.extras.append(row)
            else:
                row.note = (row.note + "; " if row.note else "") + "no spare EXTRA rows left"
                plan.unplaced.append(row)
            continue

        row.target_row = rows[0]
        row.target_name = row_name[rows[0]]
        had_b, had_p = existing(rows[0])
        for label, had, want in (("Brought In", had_b, row.brought),
                                 ("Got Paid", had_p, row.paid)):
            if not had:
                continue
            if want is None:
                # The PNL has nothing for this rep, but the grid already holds a
                # figure JD typed. Writing "" here would delete it silently.
                row.overwrites.append(f"{label} {had} LEFT ALONE (PNL is blank)")
            elif _num(had) != want:
                row.overwrites.append(f"{label} {had} -> {_fmt(want)}")
        plan.matched.append(row)
        if current.get(rows[0], "").strip().upper() == "N" and (row.paid or row.brought):
            plan.flips.append(row)

    return plan


def _fmt(v: Optional[float]) -> str:
    return "" if v is None else f"{v:,.2f}".rstrip("0").rstrip(".")


def report(plan: Plan) -> str:
    out = [f"\nWeek ending {plan.week:%b %d, %Y}  ->  {plan.banner} "
           f"(cols {plan.brought_col}/{plan.paid_col})"]
    out.append(f"\nMATCHED  ({len(plan.matched)})")
    for r in plan.matched:
        note = f"  [{r.note}]" if r.note else ""
        over = f"  !! overwrites {'; '.join(r.overwrites)}" if r.overwrites else ""
        out.append(f"  row {r.target_row:<4} {r.rep[:26]:<26} "
                   f"in {_fmt(r.brought):>9}  paid {_fmt(r.paid):>9}{note}{over}")
    for title, items in (("N -> Y (had money but marked not-current)", plan.flips),
                         ("NEW — going into spare EXTRA rows", plan.extras),
                         ("AMBIGUOUS — not written", plan.ambiguous),
                         ("NOWHERE TO PUT — not written", plan.unplaced)):
        out.append(f"\n{title}  ({len(items)})")
        if not items:
            out.append("  —")
        for r in items:
            where = f"row {r.target_row:<4} " if r.target_row else ""
            out.append(f"  {where}{r.rep[:26]:<26} "
                       f"in {_fmt(r.brought):>9}  paid {_fmt(r.paid):>9}"
                       f"{('  [' + r.note + ']') if r.note else ''}")
    return "\n".join(out)


def _split_name(full: str) -> Tuple[str, str]:
    parts = full.split()
    return (parts[0], " ".join(parts[1:])) if len(parts) > 1 else (full, "")


def apply(plan: Plan, all_in_one_id: str = C.ALL_IN_ONE_ID) -> Dict[str, int]:
    """Write the matched rows and the EXTRA placements. Never clears a cell."""
    ws = _target(all_in_one_id)
    payload: List[dict] = []

    for r in plan.matched + plan.extras:
        if not r.target_row:
            continue
        # A None is "the PNL says nothing", NOT "make it empty" — writing ""
        # would wipe a figure JD typed by hand.
        if r.brought is not None:
            payload.append({"range": f"{plan.brought_col}{r.target_row}",
                            "values": [[r.brought]]})
        if r.paid is not None:
            payload.append({"range": f"{plan.paid_col}{r.target_row}",
                            "values": [[r.paid]]})
    for r in plan.extras:
        first, last = _split_name(r.rep)
        payload.append({"range": f"E{r.target_row}:F{r.target_row}",
                        "values": [[first, last]]})
    for r in plan.flips:
        payload.append({"range": f"A{r.target_row}", "values": [["Y"]]})

    if payload:
        ws.batch_update(payload, value_input_option="USER_ENTERED")
    return {"cells": len(payload), "reps": len(plan.matched) + len(plan.extras),
            "flips": len(plan.flips)}


def hide_inactive(all_in_one_id: str = C.ALL_IN_ONE_ID) -> int:
    """JD's last move: collapse the grid back down to the people with
    activity, i.e. hide every row whose col A is N."""
    ws = _target(all_in_one_id)
    flags = ws.get(f"A{FIRST_REP_ROW}:A600")
    requests = []
    for off, raw in enumerate(flags):
        if str((list(raw) + [""])[0]).strip().upper() == "N":
            r = FIRST_REP_ROW + off
            requests.append({"updateDimensionProperties": {
                "range": {"sheetId": ws.id, "dimension": "ROWS",
                          "startIndex": r - 1, "endIndex": r},
                "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}})
    if requests:
        ws.spreadsheet.batch_update({"requests": requests})
    return len(requests)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workbook", default=C.WORKBOOK_ID)
    ap.add_argument("--write", action="store_true", help="apply (default: dry run)")
    ap.add_argument("--hide-inactive", action="store_true",
                    help="afterwards, hide every row marked N")
    args = ap.parse_args(argv)

    plan = analyze(workbook_id=args.workbook)
    print(report(plan))
    if not args.write:
        print("\n(dry run — nothing written; add --write to apply)")
        return 0
    done = apply(plan)
    print(f"\nWrote {done['cells']} cell(s) for {done['reps']} rep(s); "
          f"flipped {done['flips']} to Y.")
    if args.hide_inactive:
        print(f"Hid {hide_inactive()} row(s) marked N.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
