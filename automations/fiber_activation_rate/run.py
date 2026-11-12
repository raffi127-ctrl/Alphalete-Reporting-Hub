"""Fiber Activation Rate by rep — daily log (Raf, Slack 2026-11-12).

Ask (Raf at Haytham's office, thread "Metrics - Fiber - Activation rates"):
"take the 4-week rolling and turn it into an ongoing activation rate report…
and also get it per rep… basically this [the Ongoing Cancel image], but in
activation format." Same idea as nds_activation_rate (NDS, 2026-11-11), for ATT
Fiber. (His JEP-% request in the same thread was withdrawn — not built.)

SOURCE (one download serves every Fiber office)
  Tableau → ATTTRACKER2_1-D2D → Metrics → saved view MetricsINTfullyEXP
  (Internet, rep rows expanded; also read by captainship_abp_6days) → worksheet 'Metrics Call Last week data (Internet)' → rows
  Captain's Bonus Teams / ICD Owner Name (rep) / Rep Name → columns
    'Rolling 4 Weeks'                         (= 0-30 day activation rate)
    '30-60 day New Internet activation rate'
  NOT the base view: since 2026-08-07 it exports collapsed to owners (no
  'Rep Name' column) — the first run here died on exactly that (Lucy 4,
  2026-11-12). Expect an owner's Total to sit 0.1-1.5 pts off the Captainship
  Activation Rate tabs on 30-60: the expanded view counts partial cohorts a
  little differently (see captainship_abp_6days.pull).

Tableau only shows TODAY's rolling number, so the day-by-day history is ours:
each run appends today's numbers to the 'Fiber Activation Log' tab
(Date | Team | Owner | Rep | 0-30 | 30-60; Rep 'Total' = the owner's office
number). slack_board.py draws the images from that log. The log is the
PERMANENT record (Eve 2026-11-12: "no es info desechable") — nothing is ever
deleted from it; only a re-run of the same day replaces that day's rows.

  python -m automations.fiber_activation_rate.run --dry-run       # pull + print
  python -m automations.fiber_activation_rate.run                 # SANDBOX log
  python -m automations.fiber_activation_rate.run --real          # real workbook
  python -m automations.fiber_activation_rate.run --csv file.csv  # offline parse
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "fiber_activation_rate"

TEAM_COL = "Captain's Bonus Teams"
OWNER_COL = "ICD Owner Name (rep)"
REP_COL = "Rep Name"
TOTAL = "Total"
# window key -> crosstab column (same names country_metrics / the captainship
# tabs read, so a Tableau rename breaks all of them together, loudly).
WINDOWS = (("0-30", "Rolling 4 Weeks"),
           ("30-60", "30-60 day New Internet activation rate"))
WIN_KEYS = [k for k, _ in WINDOWS]
VIEW_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
            "ATTTRACKER2_1-D2D/Metrics/"
            "de2c904b-1438-4d76-bb14-8e5b2861d2ec/MetricsINTfullyEXP")
WORKSHEET = "Metrics Call Last week data (Internet)"

SHEET_IDS = {   # same workbook pair as nds_activation_rate (Captainship Metrics)
    "real": "1P95BxzlmLKkuvcL0gqjD9EfEHPLniGN-m4eE9UsPe_E",
    "sandbox": "1Je8W3Pv5sQ1GurNQeExBQBimzgDjN5gAxJq2o7P17-M",
}
LOG_TAB = "Fiber Activation Log"
LOG_HEADER = ["Date", "Team", "Owner", "Rep"] + WIN_KEYS


def _pct(cell: str) -> str:
    v = (cell or "").strip()
    if not v.endswith("%"):
        return ""
    try:
        float(v.rstrip("%").replace(",", ""))
    except ValueError:
        return ""
    return v


def parse(rows: List[List[str]]) -> Dict[str, Dict]:
    """Crosstab rows -> {owner: {"team": str, "reps": {rep: {win: '83.3%'}}}}.
    Rep 'Total' is the owner's own number. Team/owner cells that Tableau
    leaves blank under a group carry down from the row above. Team-level
    'Total' rows and the 'Grand Total' are skipped (not an office)."""
    if not rows:
        raise ValueError("empty crosstab")
    header = [h.lstrip("﻿").strip() for h in rows[0]]
    missing = [c for c in (OWNER_COL, REP_COL) + tuple(c for _, c in WINDOWS)
               if c not in header]
    if missing:
        raise ValueError(f"Metrics crosstab is missing {missing}; got {header}. "
                         "If 'Rep Name' is missing the view came back collapsed "
                         "to owners — this report needs the rep rows.")
    team_i = header.index(TEAM_COL) if TEAM_COL in header else None
    owner_i, rep_i = header.index(OWNER_COL), header.index(REP_COL)
    win_i = {k: header.index(c) for k, c in WINDOWS}

    out: Dict[str, Dict] = {}
    team = owner = ""
    for r in rows[1:]:
        r = list(r) + [""] * (len(header) - len(r))
        if team_i is not None and r[team_i].strip():
            team = r[team_i].strip()
        if r[owner_i].strip():
            owner = r[owner_i].strip()
        rep = r[rep_i].strip()
        if not owner or not rep or owner in (TOTAL, "Grand Total") \
                or team == "Grand Total":
            continue
        vals = {k: _pct(r[i]) for k, i in win_i.items()}
        o = out.setdefault(owner, {"team": team, "reps": {}})
        if rep == TOTAL or any(vals.values()):     # a rep with no number = noise
            o["reps"][rep] = vals
    if not out:
        raise ValueError("no owner rows in the Metrics crosstab")
    return out


def log_rows(day: dt.date, data: Dict) -> List[List[str]]:
    d = day.isoformat()
    rows = []
    for owner, o in data.items():
        for rep, vals in sorted(o["reps"].items(),
                                key=lambda kv: (kv[0] != TOTAL, kv[0].lower())):
            rows.append([d, o["team"], owner, rep] + [vals.get(k, "") for k in WIN_KEYS])
    return rows


def _col(n: int) -> str:
    s = ""
    while n:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def open_book(sandbox: bool):
    from automations.new_internet_churn import fill as _shared
    return _shared.open_by_key(SHEET_IDS["sandbox" if sandbox else "real"])


def write_log(book, day: dt.date, new_rows, *, logfn=print) -> None:
    """Append today's rows. A re-run of the same day replaces that day's
    rows; older days are NEVER touched (the log is the permanent record)."""
    from automations.new_internet_churn import fill as _shared
    try:
        ws = book.worksheet(LOG_TAB)
    except Exception:  # noqa: BLE001 — WorksheetNotFound: first run
        ws = book.add_worksheet(title=LOG_TAB, rows=max(1000, len(new_rows) + 100),
                                cols=len(LOG_HEADER))
    grid = _shared._retry(ws.get_all_values)
    if not grid or grid[0][:len(LOG_HEADER)] != LOG_HEADER:
        if grid and any(any(c for c in r) for r in grid):
            raise RuntimeError(f"'{LOG_TAB}' has an unexpected header "
                               f"{grid[0][:8]} — not touching it")
        grid = [LOG_HEADER]
        ws.update(values=[LOG_HEADER], range_name="A1")
    d = day.isoformat()
    body = grid[1:]
    keep = [r for r in body if r and r[0] != d]
    if len(keep) != len(body):
        logfn(f"  log: re-run — replacing {len(body) - len(keep)} row(s) of {d}")
        all_rows = [LOG_HEADER] + keep + new_rows
        if ws.row_count < len(all_rows) + 10:
            ws.add_rows(len(all_rows) + 500 - ws.row_count)
        ws.batch_clear([f"A2:{_col(len(LOG_HEADER))}{ws.row_count}"])
        ws.update(values=all_rows, range_name="A1", value_input_option="RAW")
    else:
        if ws.row_count < len(grid) + len(new_rows) + 10:
            ws.add_rows(len(new_rows) + 500)
        ws.append_rows(new_rows, value_input_option="RAW")
    logfn(f"  log: {len(new_rows)} row(s) for {d} in '{LOG_TAB}'")


def _read_csv(path: Path) -> List[List[str]]:
    from automations.captainship_activation_rate.pull import _read_crosstab
    rows = _read_crosstab(path)
    if not rows:
        raise ValueError(f"could not read {path}")
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--real", action="store_true", help="write the REAL workbook")
    ap.add_argument("--dry-run", action="store_true", help="pull + print, write nothing")
    ap.add_argument("--csv", default=None, help="parse this crosstab instead of pulling")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default today, CT)")
    args = ap.parse_args(argv)
    day = (dt.date.fromisoformat(args.date) if args.date
           else dt.datetime.now(TZ).date())
    where = "REAL" if args.real else "SANDBOX"
    print(f"Fiber activation by rep — {day} — {where} workbook"
          f"{' (dry-run)' if args.dry_run else ''}", flush=True)

    if args.csv:
        path = Path(args.csv)
    else:
        from automations.shared.tableau_patchright import download_crosstab_patchright
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = download_crosstab_patchright(
            VIEW_URL, WORKSHEET, OUT_DIR / f"metrics_{day.isoformat()}.csv")
    data = parse(_read_csv(path))
    n_reps = sum(1 for o in data.values() for r in o["reps"] if r != TOTAL)
    print(f"  {len(data)} owner(s), {n_reps} rep(s) with a number", flush=True)
    for owner, o in sorted(data.items()):
        t = o["reps"].get(TOTAL, {})
        print(f"     {owner} [{o['team'] or '-'}]: 0-30 {t.get('0-30') or '–'}"
              f" | 30-60 {t.get('30-60') or '–'} | {len(o['reps']) - (TOTAL in o['reps'])} rep(s)")
    if args.dry_run:
        print("\n(dry-run) nothing written.")
        return 0
    write_log(open_book(not args.real), day, log_rows(day, data))
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
