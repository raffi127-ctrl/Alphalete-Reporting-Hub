"""Org Active Headcount — every owner's DAY-BY-DAY week, kept after the roll.

WHY (Rafael 2026-10-25, the per-org summaries in org_split): the tab keeps only
TOTALS for past weeks (its 'WE M.D' rows). Each owner's Monday..Sunday is
cleared by the Tuesday roll, so a per-org '4 Week AVG' had nothing to average.
From now on the roll copies the closing week here first: one row per owner per
week, with their Org Head, seven headcounts and seven App Avgs.

THE TAB: 'Org Headcount History' in the same workbook, hidden (nobody types in
it; it is this report's record). A sandbox roll writes 'Org Headcount History
SANDBOX' instead, so a test never puts numbers in the real record.

NOTHING IS RECOMPUTED: the cells are copied as the daily block shows them on
the morning of the roll. A week already stored is never written twice, so a
roll that is re-run cannot double a week.

SEEDED 2026-10-25: WE 10.18 from 'backup_pre_rollover_headcount' (the 10/20
roll's snapshot); WE 10.11, 10.04 and 09.27 read off the board picture in that
week's Monday "through Sun" email (alphaletereporting Sent Mail). Each rebuilt
week matched the tab on all 7 daily totals ('WE M.D' rows) and on every
owner's Sunday headcount + App Avg (Ongoing block) before it was stored. Org
Head for those weeks = the owner's tag on 10/25.

    python -m automations.org_active_headcount.org_history                       # show what's stored
    python -m automations.org_active_headcount.org_history --from-backup         # dry run
    python -m automations.org_active_headcount.org_history --from-backup --apply
`--from-backup` is also the RECOVERY if a roll ever logs that it could not save
the week: the backup tab still holds that week until the next roll.
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Dict, List, Optional

from automations.org_active_headcount import daily as d

HISTORY_TAB = "Org Headcount History"
SANDBOX_SUFFIX = " SANDBOX"
SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
HEADER = (["Week Ending", "Owner", "Org Head"] + [f"{x} HC" for x in SHORT]
          + [f"{x} App Avg" for x in SHORT])


def tab_name(sandbox: bool) -> str:
    return HISTORY_TAB + (SANDBOX_SUFFIX if sandbox else "")


def week_rows(g, we: dt.date) -> List[list]:
    """The rows to store for the week ending `we`, read off a grid whose daily
    block still holds that week. Pure. Org Head comes from the delta box ('' if
    an owner is not there — kept, not dropped: a gap is a fact)."""
    dl, dx = d.find_daily(g), d.find_delta(g)
    sub = dx["sub"]
    oh = next((k for k in range(1, len(g[sub - 1]) + 1)
               if d._c(g, sub, k).lower() == "org head"), None)
    org = {n.lower(): (d._c(g, r, oh) if oh else "") for r, n in dx["rows"]}
    out = []
    for r, name, _camp in dl["rows"]:
        hc = [d._c(g, r, k) for k in dl["days"]]
        app = [d._c(g, r, k) if k else "" for k in dl["avg"]]
        out.append([we.isoformat(), name, org.get(name.lower(), "")] + hc + app)
    return out


def _open(sh, sandbox: bool, create: bool):
    name = tab_name(sandbox)
    try:
        return sh.worksheet(name)
    except Exception:                                              # noqa: BLE001
        if not create:
            return None
    ws = sh.add_worksheet(title=name, rows=200, cols=len(HEADER))
    ws.update(range_name="A1", values=[HEADER], value_input_option="RAW")
    try:
        sh.batch_update({"requests": [{"updateSheetProperties": {
            "properties": {"sheetId": ws.id, "hidden": True},
            "fields": "hidden"}}]})
    except Exception:                                              # noqa: BLE001
        pass
    return ws


def save_week(sh, g, we: dt.date, sandbox: bool = False,
              apply_changes: bool = True, logfn=print) -> int:
    """Append the week ending `we` unless it is already stored. Returns the
    number of rows written (0 = already there)."""
    return save_rows(sh, week_rows(g, we), we, sandbox, apply_changes, logfn)


def save_rows(sh, rows: List[list], we: dt.date, sandbox: bool = False,
              apply_changes: bool = True, logfn=print) -> int:
    """Append already-built rows for the week ending `we` (save_week's write;
    also used for weeks rebuilt from the emailed pictures)."""
    ws = _open(sh, sandbox, create=apply_changes)
    have = ws.col_values(1) if ws else []
    if we.isoformat() in have:
        logfn(f"  history: WE {we:%m/%d} already in {tab_name(sandbox)!r} — nothing written")
        return 0
    if not apply_changes:
        logfn(f"  history (dry run): would add {len(rows)} owner row(s) for WE {we:%m/%d}")
        return 0
    from automations.recruiting_report.fill import _retry
    _retry(ws.append_rows, rows, value_input_option="RAW")
    logfn(f"  history: WE {we:%m/%d} -> {len(rows)} owner row(s) in {tab_name(sandbox)!r}")
    return len(rows)


def parse(values: List[list]) -> Dict[dt.date, Dict[str, dict]]:
    """{week ending: {owner: {'org', 'hc': [7], 'app': [7]}}} from the tab's
    values (header row included). Pure."""
    out: Dict[dt.date, Dict[str, dict]] = {}
    for row in values[1:]:
        row = list(row) + [""] * (len(HEADER) - len(row))
        try:
            we = dt.date.fromisoformat(row[0].strip())
        except ValueError:
            continue
        out.setdefault(we, {})[row[1].strip()] = {
            "org": row[2].strip(),
            "hc": [d._num(v) for v in row[3:10]],
            "app": [_float(v) for v in row[10:17]],
        }
    return out


def _float(s) -> Optional[float]:
    try:
        return float(str(s).replace(",", "").strip())
    except ValueError:
        return None


def load(sh=None, sandbox: bool = False) -> Dict[dt.date, Dict[str, dict]]:
    if sh is None:
        from automations.recruiting_report.fill import open_by_key
        sh = open_by_key(d.SHEET_ID)
    ws = _open(sh, sandbox, create=False)
    return parse(ws.get_all_values()) if ws else {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="org_active_headcount.org_history")
    ap.add_argument("--from-backup", action="store_true",
                    help=f"store the week held in {d.BACKUP_TAB!r} (the last roll's snapshot)")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    a = ap.parse_args(argv)
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(d.SHEET_ID)
    if a.from_backup:
        b = sh.worksheet(d.BACKUP_TAB).get_all_values()
        dl = d.find_daily(b)
        sun = d._num(d._c(b, dl["daynum"], dl["days"][-1]))
        # The backup is the tab as it stood just before the last roll: the
        # week before the one the tab shows now. Its own Sunday day number
        # must agree, or it is not the week we think it is.
        we = d.board_sunday(d.open_tab(False).get_all_values(),
                            dt.date.today()) - dt.timedelta(days=7)
        if we.day != sun:
            raise SystemExit(f"backup's Sunday is the {sun}th, expected WE {we} — "
                             "not storing a week I can't date")
        save_week(sh, b, we, apply_changes=a.apply)
    for we, owners in sorted(load(sh).items()):
        tot = [sum((o["hc"][i] or 0) for o in owners.values()) for i in range(7)]
        print(f"WE {we:%m/%d}: {len(owners)} owners, daily totals {tot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
