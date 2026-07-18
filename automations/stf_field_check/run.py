"""STF Field Check — flip 'STF' to 'X' for reps who didn't really work.

Raf's rule (Loom 2026-07-17): a rep marked "STF" (Straight To Field) on the
Sales Board who worked LESS THAN 3 HOURS that day didn't actually work the
field, so their status should read "X", not "STF" — that keeps his
"reps-scheduled-in-the-field" count honest.

WHAT IT DOES (per run, for ONE day):
  1. Open the Sales Board and find the current-week 'Sales Board WE m.d' tab.
  2. In that day's Roll Call column, find every rep whose status == "STF".
  3. Pull that same day's Ownerville Time Tracker (p=510 — Raf's master view,
     no impersonation) and read each rep's First Knock / Last Knock.
  4. worked = Last Knock − First Knock.  If worked < 3:00 (or the rep has no
     knocks at all → never showed up), overwrite the "STF" cell with "X".

WHEN: 11pm CST for the CURRENT day — late enough that reps are out of the
field and the day's knocks are final, but before the 4am sales-board post.
The harvested Daily Rep Breakdown can't be used (it fills the next morning,
so it has no same-day knocks) — this scrapes Time Tracker live.

WHERE: the mini only (Ownerville is single-session; a second login evicts the
session holder). Safe by default: DRY-RUN unless --write is passed.

Run:
  # dry-run (no writes), today:
  .venv/bin/python -m automations.stf_field_check.run
  # a specific past day (backfill), dry-run:
  .venv/bin/python -m automations.stf_field_check.run --date 2026-07-15
  # actually write the X's:
  .venv/bin/python -m automations.stf_field_check.run --write
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import sys
from pathlib import Path

from automations.recruiting_report.fill import open_by_key
from automations.alphalete_production.capture import SHEET_ID, find_week_tab, col_letter
from automations.total_knocks.fill import _clock_key

DAY_NAMES = {"MON", "TUES", "WED", "THU", "FRI", "SAT", "SUN"}
STF = "STF"
X = "X"
DEFAULT_THRESHOLD_MIN = 180  # 3 hours


# ---- pure helpers (offline-testable) ------------------------------------

def norm(s: str) -> str:
    """Lowercase + collapse whitespace, for forgiving name comparison."""
    return " ".join((s or "").split()).lower()


def squash(s: str) -> str:
    """Drop ALL spaces too — matches 'Mustafa Alzaidy' (board) to
    'Mustafa Al Zaidy' (Ownerville)."""
    return norm(s).replace(" ", "")


def worked_minutes(first: str, last: str):
    """Minutes worked = last-knock − first-knock. Returns a float, or None if
    the rep has no usable knock pair (blank/unparseable → didn't work)."""
    f, l = _clock_key(first), _clock_key(last)
    if f == float("inf") or l == float("inf"):
        return None
    return l - f


def fmt_hm(mins) -> str:
    if mins is None:
        return "—"
    h, m = divmod(int(round(mins)), 60)
    return f"{h}:{m:02d}"


def index_knocks(reps: list[dict]) -> dict:
    """Build {squashed_name: rep_dict} from scraped Time Tracker rows, keeping
    the row with the widest knock span if a name repeats."""
    out: dict = {}
    for r in reps:
        key = squash(r.get("name", ""))
        if not key:
            continue
        prev = out.get(key)
        if prev is None:
            out[key] = r
        else:  # keep the fuller record (real knocks beat blanks)
            wm_new = worked_minutes(r.get("first_knock", ""), r.get("last_knock", ""))
            wm_old = worked_minutes(prev.get("first_knock", ""), prev.get("last_knock", ""))
            if (wm_old is None) or (wm_new is not None and wm_new > wm_old):
                out[key] = r
    return out


def decide(board_name: str, knocks_by_name: dict, threshold_min: int) -> dict:
    """Decide whether a single STF rep should be flipped to X.

    Returns a dict: {name, matched_ov_name, first, last, worked_min,
    action ('flip'|'keep'|'review'), reason}.
    """
    key = squash(board_name)
    rep = knocks_by_name.get(key)
    if rep is None:
        # No Time-Tracker row at all. Could be a genuine no-show (→ X) OR a
        # name-spelling miss. Surface the closest OV names so a human can tell.
        close = difflib.get_close_matches(key, list(knocks_by_name), n=3, cutoff=0.6)
        close_names = [knocks_by_name[k].get("name", k) for k in close]
        return {
            "name": board_name, "matched_ov_name": None,
            "first": "", "last": "", "worked_min": None,
            "action": "flip",
            "reason": ("no knocks in Time Tracker — never showed → X"
                       + (f" (closest OV names: {', '.join(close_names)})"
                          if close_names else "")),
        }
    first = rep.get("first_knock", "").strip()
    last = rep.get("last_knock", "").strip()
    wm = worked_minutes(first, last)
    if wm is None:
        return {"name": board_name, "matched_ov_name": rep.get("name"),
                "first": first, "last": last, "worked_min": None,
                "action": "flip", "reason": "knocks present but no valid span → X"}
    if wm < threshold_min:
        return {"name": board_name, "matched_ov_name": rep.get("name"),
                "first": first, "last": last, "worked_min": wm,
                "action": "flip",
                "reason": f"worked {fmt_hm(wm)} < {fmt_hm(threshold_min)} → X"}
    return {"name": board_name, "matched_ov_name": rep.get("name"),
            "first": first, "last": last, "worked_min": wm,
            "action": "keep",
            "reason": f"worked {fmt_hm(wm)} ≥ {fmt_hm(threshold_min)} → leave STF"}


# ---- board read ---------------------------------------------------------

def _date_for_rc(grid, rc: int, year: int, month: int):
    """Map a Roll Call column to its calendar date via the day-name (row 0) +
    day-of-month (row 1) headers in that 7-wide day block."""
    for c in range(rc, max(-1, rc - 8), -1):
        dn = grid[0][c].strip() if c < len(grid[0]) else ""
        dom = grid[1][c].strip() if c < len(grid[1]) else ""
        if dn in DAY_NAMES and dom.isdigit():
            try:
                return dt.date(year, month, int(dom))
            except ValueError:
                return None
    return None


def find_stf_cells(ws, target: dt.date) -> list[dict]:
    """Return [{name, a1, row, col}] for every STF cell in target's Roll Call
    column. Rep names live in col C (index 2); the label row (index 2) holds
    'Roll Call'."""
    grid = ws.get_all_values()
    rc_cols = [c for c in range(len(grid[2])) if grid[2][c].strip().lower() == "roll call"]
    target_rc = None
    for rc in rc_cols:
        if _date_for_rc(grid, rc, target.year, target.month) == target:
            target_rc = rc
            break
    if target_rc is None:
        return []
    out = []
    for r in range(3, len(grid)):
        name = grid[r][2].strip() if len(grid[r]) > 2 else ""
        if not name or name.upper() in DAY_NAMES or name.upper() == "TOTALS":
            continue
        val = grid[r][target_rc].strip() if target_rc < len(grid[r]) else ""
        if val.upper() == STF:
            out.append({"name": name, "row": r + 1, "col": target_rc,
                        "a1": f"{col_letter(target_rc)}{r + 1}"})
    return out


# ---- Ownerville scrape (mini only) --------------------------------------

def scrape_knocks(target: dt.date, verbose: bool = True) -> list[dict]:
    """Live Time Tracker scrape for `target`, Raf's master view (no
    impersonation). Returns the raw rep dicts from scrape_day."""
    # Imported lazily so the offline/dry-run+injected path never needs patchright.
    from automations.shared.tableau_patchright import ownerville_session
    from automations.focus_office_att.step5_fill_one_owner import scrape_day

    TT = "p=510"
    with ownerville_session(headless=True, verbose=verbose) as page:
        rqst = page.evaluate("typeof rqstValue !== 'undefined' ? rqstValue : null")
        page.goto(f"https://v2.ownerville.com/index.cfm?{TT}&rqst={rqst}",
                  wait_until="domcontentloaded", timeout=45000)
        return scrape_day(page, target)


# ---- main ---------------------------------------------------------------

def run(target: dt.date, write: bool, threshold_min: int,
        injected_knocks: list[dict] | None = None, verbose: bool = True) -> dict:
    ss = open_by_key(SHEET_ID)
    ws = find_week_tab(ss, target)
    print(f"Sales Board tab : {ws.title}")
    print(f"Day             : {target.isoformat()} ({target.strftime('%A')})")
    print(f"Threshold       : worked < {fmt_hm(threshold_min)} → X")
    print(f"Mode            : {'WRITE' if write else 'DRY-RUN (no writes)'}")

    stf = find_stf_cells(ws, target)
    if not stf:
        print("\nNo reps marked STF for this day. Nothing to do.")
        return {"stf": 0, "flipped": 0, "kept": 0, "decisions": []}
    print(f"\nSTF reps this day ({len(stf)}): "
          + ", ".join(f"{s['name']} [{s['a1']}]" for s in stf))

    reps = injected_knocks if injected_knocks is not None else scrape_knocks(target, verbose)
    print(f"Time Tracker rows scraped: {len(reps)}")
    knocks = index_knocks(reps)

    decisions = []
    writes = []
    for s in stf:
        d = decide(s["name"], knocks, threshold_min)
        d["a1"] = s["a1"]
        decisions.append(d)
        if d["action"] == "flip":
            writes.append({"range": s["a1"], "values": [[X]]})

    # ---- report ----
    print("\n" + "=" * 78)
    print(f"{'Rep':24s} {'Cell':7s} {'First':9s} {'Last':9s} {'Worked':7s} Action")
    print("-" * 78)
    for d in decisions:
        act = "STF → X" if d["action"] == "flip" else "keep STF"
        print(f"{d['name'][:24]:24s} {d['a1']:7s} {d['first'][:9]:9s} "
              f"{d['last'][:9]:9s} {fmt_hm(d['worked_min']):7s} {act}")
        print(f"    ↳ {d['reason']}")
    print("=" * 78)

    flipped = sum(1 for d in decisions if d["action"] == "flip")
    print(f"\n{flipped} to flip STF→X, {len(decisions) - flipped} to keep.")

    if write and writes:
        # Re-read each cell right before writing so we never clobber a status
        # someone changed off STF since we scanned (idempotent, safe).
        safe_writes = []
        for w in writes:
            cur = ws.acell(w["range"]).value or ""
            if cur.strip().upper() == STF:
                safe_writes.append(w)
            else:
                print(f"  ⚠ {w['range']} is now {cur!r}, not STF — skipping.")
        if safe_writes:
            ws.batch_update(safe_writes, value_input_option="USER_ENTERED")
            print(f"✓ Wrote X to {len(safe_writes)} cell(s): "
                  + ", ".join(w["range"] for w in safe_writes))
    elif writes:
        print("(dry-run — no cells written. Re-run with --write to apply.)")

    return {"stf": len(stf), "flipped": flipped, "kept": len(decisions) - flipped,
            "decisions": decisions}


def _parse_date(s: str | None) -> dt.date:
    if not s:
        return dt.date.today()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise SystemExit(f"Bad --date {s!r}; use YYYY-MM-DD or MM/DD/YYYY")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Flip STF→X for reps who worked <3h.")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD or MM/DD/YYYY; default today")
    ap.add_argument("--write", action="store_true", help="actually write X (default: dry-run)")
    ap.add_argument("--dry-run", action="store_true",
                    help="force dry-run even if --write is present (wins; lets the "
                         "nightly wrapper default to --write yet still be testable)")
    ap.add_argument("--threshold-min", type=int, default=DEFAULT_THRESHOLD_MIN,
                    help="minutes below which STF→X (default 180 = 3h)")
    ap.add_argument("--knocks-json", default=None,
                    help="offline test: read scraped Time Tracker rows from a JSON "
                         "file (list of {name,first_knock,last_knock}) instead of scraping")
    args = ap.parse_args(argv)

    target = _parse_date(args.date)
    injected = None
    if args.knocks_json:
        data = json.loads(Path(args.knocks_json).read_text())
        injected = data["reps"] if isinstance(data, dict) and "reps" in data else data

    write = args.write and not args.dry_run
    run(target, write=write, threshold_min=args.threshold_min,
        injected_knocks=injected)
    return 0


if __name__ == "__main__":
    sys.exit(main())
