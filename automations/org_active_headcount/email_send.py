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
    python -m automations.org_active_headcount.email_send --post --update   # resend after a fix
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

REPORT_ID = "org_active_headcount_email"        # schedule_config id

RECIPIENTS = [
    "CarlosHidalgo349@gmail.com",     # Carlos Hidalgo
    "raffi127@gmail.com",             # Rafael Hidalgo
    "eve@alphaletemarketing.com",     # Eve Sobrino
    "coltenwrightsc@gmail.com",       # Colten Wright (added 2026-09-19, Eve)
]
TITLE = "Org Active Headcount"
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "org_active_headcount"


def board_range(g) -> str:
    """A1 through SUNDAY, down to the last 'WE M.D' history row (or its Totals
    row if there is none).

    It used to run out to 'PREVIOUS WEEK'S TOTALS'. Eve asked for Sunday on
    2026-09-20 (`con que hagamos captura hasta columna I esta bien`), once she
    had painted RUNNING WEEK / LAST WEEK'S / PREVIOUS WEEK'S black on black to
    keep their numbers without showing them. NOTE this also cuts the Ongoing
    block, which is wider: it runs ten weeks, and the mail now shows the seven
    that fit. Widen this to `og['wcols'][-1][0]` to put the other three back."""
    dl = d.find_daily(g)
    stack = d.find_stack(g, dl["totals"])
    return f"A1:{d.A(dl['days'][-1])}{stack[-1] if stack else dl['totals']}"


def delta_range(g, today: Optional[dt.date] = None) -> str:
    """The delta box's WEEK triplet only — This week / Last week / Delta — from
    its title row down to its totals row.

    It used to be the whole box cropped to the elapsed days, borrowed from the
    Country / All Units boards (`org_sales_board.rollover.delta_block_range`).
    Those boards accumulate, so their per-day columns each say something new.
    This one does not: every day is its own ongoing headcount, so the seven
    per-day triplets were seven ways of saying what the week triplet already
    says. Eve, 2026-09-20: `con que capturamos hasta columna E todos los dias,
    esta bien`. Dropping that borrowed derivation also drops its anchor on the
    exact string 'Total this week', which she had just edited away."""
    dx = d.find_delta(g)
    last = dx["this"][0] - 1          # the week triplet's Delta, left of Monday
    return f"A{dx['hdr']}:{d.A(last)}{dx['totals']}"


def totals_mismatch(g) -> List[str]:
    """The same week, read from its three places, must be ONE number: the
    Ongoing block's current WE column, the daily block's Totals row on its last
    filled day, and the delta box's week 'This week'. Plus each filled day of
    the daily Totals row against that day's 'This week' total in the delta box.

    They are hand-written formulas with their own rules, and they drifted more
    than once: 2026-09-21 the delta box counted a '-' day as 0 (SUMIF) while the
    Totals row carries the last known number — 457 vs 516 went out in the mail.
    Returns one line per disagreement; empty = all agree."""
    dl, og, dx = d.find_daily(g), d.find_ongoing(g), d.find_delta(g)
    out = []
    day_tot = [d._num(d._c(g, dl["totals"], k)) for k in dl["days"]]
    filled = [i for i, v in enumerate(day_tot) if v is not None]
    for i in filled:
        dv = d._num(d._c(g, dx["totals"], dx["this"][i]))
        if dv != day_tot[i]:
            out.append(f"{d.DAYS[i]}: daily Totals {day_tot[i]} vs delta box {dv}")
    if filled:
        last = day_tot[filled[-1]]
        ongoing = d._num(d._c(g, og["totals"], og["wcols"][0][0]))
        week = d._num(d._c(g, dx["totals"], dx["this"][0] - 3))
        if ongoing != last:
            out.append(f"week: Ongoing {og['wcols'][0][1]} {ongoing} vs daily Totals {last}")
        if week != last:
            out.append(f"week: delta box This week {week} vs daily Totals {last}")
    return out


def build_pngs(today: Optional[dt.date] = None,
               sandbox: bool = False) -> List[Tuple[Path, str]]:
    from automations.org_sales_board.screenshot_email import _export_png, _access_token
    ws = d.open_tab(sandbox)
    g = ws.get_all_values()
    bad = totals_mismatch(g)
    if bad:
        # Fail the run (orchestrator alerts) rather than mail numbers that
        # contradict each other on the same page.
        raise SystemExit("totals disagree, mail NOT sent:\n  " + "\n  ".join(bad))
    parts = [("board", board_range(g)), ("delta", delta_range(g, today))]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    token = _access_token()
    out = []
    for name, rng in parts:
        p = OUT_DIR / f"org_active_headcount_{name}.png"
        _export_png(ws.id, rng, p, token, spreadsheet_id=d.SHEET_ID)
        out.append((p, rng))
    return out


def _record_delivery(to: List[str], subject: str) -> None:
    """Write today's run manifest — the PROOF of delivery shared/delivery_check
    looks for (same pattern as the six reports in 4506e6d).

    2026-09-21: the first pass FAILED, the mail then went out to all four at
    10:30 (and an UPDATE at 12:08), and the ticket still sat open — "ran clean,
    but nothing can confirm it DELIVERED" — because this report wrote no
    manifest. Only a real send to the real list writes it (not dry run,
    --only, --sandbox or --today). Never raises."""
    try:
        from automations.shared import run_manifest
        note = f"emailed '{subject}' to {len(to)}"
        run_manifest.write_manifest(REPORT_ID, succeeded=list(to), note=note)
        print(f"  manifest: {note}")
    except Exception as e:                                      # noqa: BLE001
        print(f"  ⚠ couldn't write the run manifest ({type(e).__name__}: {e}) "
              "— the mail went out, but a failure ticket won't close itself")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="org_active_headcount.email_send")
    ap.add_argument("--post", action="store_true", help="send (default: dry run)")
    ap.add_argument("--only", default="",
                    help="comma-separated email(s) INSTEAD of the list (test)")
    ap.add_argument("--today", type=dt.date.fromisoformat, help="pretend today is this date")
    ap.add_argument("--sandbox", action="store_true",
                    help="shoot the SANDBOX copy of the tab instead of the live one")
    ap.add_argument("--update", action="store_true",
                    help="resend after a fix: subject starts with 'UPDATE'")
    a = ap.parse_args(argv)
    from automations.shared import report_email
    today = a.today or dt.date.today()
    to = [u.strip() for u in a.only.split(",") if u.strip()] or list(RECIPIENTS)
    shots = build_pngs(today, sandbox=a.sandbox)
    for p, rng in shots:
        print(f"screenshot {rng} -> {p} ({p.stat().st_size // 1024} KB)")
    yday = today - dt.timedelta(days=1)
    subject = f"{'UPDATE — ' if a.update else ''}{TITLE} — through {yday:%a %m/%d}"
    try:
        resp = report_email.send_boards(
            subject=subject,
            to=to, title=TITLE.upper(),
            blocks=[("Headcount", shots[0][0]), ("Delta vs last week", shots[1][0])],
            dry_run=not a.post)
    except Exception as e:                                         # noqa: BLE001
        # A failed send must fail the run, so the orchestrator alerts instead of
        # recording a mail nobody got.
        print(f"  FAILED — {type(e).__name__}: {e}")
        return 1
    print(f"  result: {resp}")
    if not resp.get("ok"):
        return 1
    if a.post and not (a.only or a.sandbox or a.today):
        _record_delivery(to, subject)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
