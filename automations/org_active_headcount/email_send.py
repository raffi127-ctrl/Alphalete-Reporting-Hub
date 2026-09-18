"""Org Active Headcount — the daily screenshot EMAIL.

Eve 2026-09-18: it started as a Slack group DM to Rafael, Carlos and Evelyn
the same morning; Rafael then asked for it BY EMAIL instead. TWO pictures a day,
in ONE message (shared.report_email: from alphaletereporting@gmail.com, the
same sender and credential as every other automated mail):

  1. THE BOARD — the top of the tab: Headcount Summary, Current vs Prior Weeks,
     the Ongoing (WE) block and the per-day 'All Campaigns HC' block down to its
     'WE M.D' history rows. Right edge = the 'PREVIOUS WEEK'S TOTALS' column, so
     the Campaign / Org Head helper columns stay out.
  2. THE DELTA BOX — 'This week / Last week / Delta' per owner, cropped "like the
     other reports": org_sales_board.rollover.delta_block_range, the one
     derivation the Country and All Units boards already share. It cuts the days
     that have not happened (a Friday column of 0 / -100% is noise, not data).

Runs AFTER the morning fill (org_active_headcount_daily), after the Org Sales
Board is posted and after the tracker thread is up — the gates live in
schedule_config (`org_active_headcount_email`).

    python -m automations.org_active_headcount.email_send            # dry run
    python -m automations.org_active_headcount.email_send --post
    python -m automations.org_active_headcount.email_send --post --only eve@alphaletemarketing.com
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                                  # noqa: BLE001
    pass

from automations.org_active_headcount import daily as d

RECIPIENTS = [
    "CarlosHidalgo349@gmail.com",     # Carlos Hidalgo
    "raffi127@gmail.com",             # Rafael Hidalgo
    "eve@alphaletemarketing.com",     # Eve Sobrino
]
TITLE = "Org Active Headcount"
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "org_active_headcount"


def board_range(g) -> str:
    """A1 through the per-day block's 'PREVIOUS WEEK'S TOTALS' column, down to
    the last 'WE M.D' history row (or its Totals row if there is none)."""
    dl = d.find_daily(g)
    stack = d.find_stack(g, dl["totals"])
    return f"A1:{d.A(dl['prevw'])}{stack[-1] if stack else dl['totals']}"


def delta_range(g, today: Optional[dt.date] = None) -> str:
    """The delta box, cropped to the elapsed days — the same derivation the
    Country / All Units boards use. Widened to col A when the rank numbers are
    there (delta_block_range starts at B)."""
    from automations.org_sales_board import rollover as org_ro
    tables = [t for t in org_ro.find_delta_tables(g)
              if "ongoing headcount" in str(g[t["header_row"] - 2][0]).lower()]
    if not tables:
        raise ValueError("delta box ('All Campaings Ongoing Headcount' / "
                         "'Total this week') not found")
    t = tables[0]
    rng = org_ro.delta_block_range(g, t, today=today)
    first = t["data_rows"][0]
    if str(g[first - 1][0]).strip():
        rng = "A" + rng.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    return rng


def build_pngs(today: Optional[dt.date] = None) -> List[Tuple[Path, str]]:
    from automations.org_sales_board.screenshot_email import _export_png, _access_token
    ws = d.open_tab()
    g = ws.get_all_values()
    parts = [("board", board_range(g)), ("delta", delta_range(g, today))]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    token = _access_token()
    out = []
    for name, rng in parts:
        p = OUT_DIR / f"org_active_headcount_{name}.png"
        _export_png(ws.id, rng, p, token, spreadsheet_id=d.SHEET_ID)
        out.append((p, rng))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="org_active_headcount.email_send")
    ap.add_argument("--post", action="store_true", help="send (default: dry run)")
    ap.add_argument("--only", default="",
                    help="comma-separated email(s) INSTEAD of the list (test)")
    ap.add_argument("--today", type=dt.date.fromisoformat, help="pretend today is this date")
    a = ap.parse_args(argv)
    from automations.shared import report_email
    today = a.today or dt.date.today()
    to = [u.strip() for u in a.only.split(",") if u.strip()] or list(RECIPIENTS)
    shots = build_pngs(today)
    for p, rng in shots:
        print(f"screenshot {rng} -> {p} ({p.stat().st_size // 1024} KB)")
    yday = today - dt.timedelta(days=1)
    try:
        resp = report_email.send_boards(
            subject=f"{TITLE} — through {yday:%a %m/%d}",
            to=to, title=TITLE.upper(),
            blocks=[("Headcount", shots[0][0]), ("Delta vs last week", shots[1][0])],
            dry_run=not a.post)
    except Exception as e:                                         # noqa: BLE001
        # A failed send must fail the run, so the orchestrator alerts instead of
        # recording a mail nobody got.
        print(f"  FAILED — {type(e).__name__}: {e}")
        return 1
    print(f"  result: {resp}")
    return 0 if resp.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
