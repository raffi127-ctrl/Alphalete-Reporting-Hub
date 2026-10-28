"""The Org Sales Board email waits for Verizon (Eve 2026-10-28: "podemos
setearlo para que espere a verizon antes de mandarse y si no llegó cerca de
9:30 que se envíe").

Verizon's only source is Credico's 'Wireless Only' scorecard PDF, which Carlos's
Gmail filter forwards ~9:31am CT. The board fills at ~5am, so the morning email
always showed Nico's yesterday blank — and on 2026-10-28 the visual check held
it for that. Now board_emails.auto_send asks pending() on every check pass
(every 5 minutes from 07:00) BEFORE judging the email:

  * yesterday's Verizon column is filled          -> None, judge as usual.
  * blank, today's PDF is in the inbox            -> top it off right here
    (Verizon section + the All Campaigns board, which sums it), then None —
    auto_send rebuilds the email once from the fresh board and sends it.
  * blank, no PDF yet, before DEADLINE            -> a reason: wait quietly.
  * past DEADLINE                                 -> None: send with what the
    board has (the visual check knows Verizon is DAY_BEHIND, so it won't hold).

Never raises: anything it can't read means "don't wait" — a broken Verizon
check must not cost the day's email.
"""
from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path
from typing import Optional

DEADLINE = dt.time(9, 45)      # Central. The PDF lands ~9:31; 15 min of slack.
SECTION = "Verizon"
_ROOT = Path(__file__).resolve().parents[2]


def _blank_yesterday(day: dt.date) -> bool:
    """Is the Verizon section's column for the day before `day` still blank?"""
    from automations.org_sales_board import data_gate as dg
    for s in dg.coverage(yday=day - dt.timedelta(days=1)):
        if s["name"].strip().lower().startswith(SECTION.lower()):
            return bool(s["col"] and s["expected"] and s["missing"])
    return False                       # no Verizon section: nothing to wait for


def _todays_pdf_in(day: dt.date) -> bool:
    from automations.org_sales_board import verizon_pull as vp
    pdf = vp.fetch(_ROOT / "output")
    d = vp.report_date(pdf) if pdf else None
    return bool(d and d >= day)


def _run(*args: str) -> int:
    cmd = [sys.executable, "-u", "-m", *args]
    print(f"  verizon wait: {' '.join(args)}", flush=True)
    return subprocess.run(cmd, cwd=str(_ROOT), timeout=900).returncode


def top_off() -> None:
    """Same shape as the BOX top-off (deploy/org_board_box_repull.sh):
    --no-manifest so a one-section re-pull never gives the day's verdict."""
    _run("automations.org_sales_board.run", "--step", "daily",
         "--skip-compare", "--no-manifest", "--sections", SECTION)
    _run("automations.all_campaigns_board.run", "--apply")


def pending(day: dt.date, now: Optional[dt.datetime] = None) -> Optional[str]:
    """A reason to keep waiting, or None to go ahead (see the module doc)."""
    now = now or dt.datetime.now(_central()).replace(tzinfo=None)
    if day != now.date() or now.time() >= DEADLINE:
        return None                    # a rerun of an old day, or past 9:45
    try:
        if not _blank_yesterday(day):
            return None
        if _todays_pdf_in(day):
            top_off()
            if not _blank_yesterday(day):
                return None
            return "Verizon PDF is in but the top-off left the day blank"
        return f"Verizon scorecard not in yet (sends anyway at {DEADLINE:%H:%M} CT)"
    except Exception as e:  # noqa: BLE001 — never cost the email over this
        print(f"  verizon wait: skipped ({type(e).__name__}: {e})", flush=True)
        return None


def _central():
    from automations.shared import weekend_release as wr
    return wr.CENTRAL
