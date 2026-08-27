"""Say something when the sweep STOPS running.

The failure-streak alert in run.py only fires when a sweep runs and fails. It
cannot see the worse case: the LaunchAgent not firing at all. A job that never
runs writes no log, publishes no Hub row, and posts no incident -- it is
silent in exactly the way a healthy quiet evening is silent, and the only
signal is a person noticing the board stopped moving.
[[reference_never_run_reports_invisible]]

That case is not hypothetical here. On the first night live the agent logged 2
sweeps between 19:19 and 20:00 where the 5-minute timer should have produced
eight, and nobody could tell from the outside -- the 8pm scoreboard only went
out because it was fired by hand.

So: every 20 minutes during selling hours, check how long ago the sweep log was
last written. Older than STALE_MINUTES and it DMs Raf, once, with a cooldown.

READ-ONLY apart from the alert: it reads a file's mtime and sends a message.
It never runs the sweep, never touches the board.

    python -m automations.alphalete_sales_board.watchdog --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from automations.alphalete_sales_board import config as C

STALE_MINUTES = 20          # 4 missed ticks
COOLDOWN_HOURS = 2

# WHERE THIS GOES: #claudecorrections-and-requests, the channel every other
# report's failures land in, with Megan @-mentioned. The first version DM'd Raf
# -- lifted wholesale from bg_check_sync's watchdog, whose owner IS Raf. He
# never asked for this report and would have got its alerts (Megan caught it,
# 2026-08-26). A DM also hides the fault from everyone else working the
# channel; a post in the corrections channel is where somebody is already
# looking. [[project_corrections_slack_channel]]
CHANNEL = "C0BK5PRG259"     # #claudecorrections-and-requests
MEGAN = "U04G5HJBGFN"       # Megan Hidalgo
_LAST_ALERT = Path.home() / ".config" / "recruiting-report" / "alphalete_sales_board_watchdog.txt"


def log_path(day: dt.date = None) -> Path:
    day = day or dt.date.today()
    return (C.REPO_ROOT / "output" / "logs"
            / ("alphalete-sales-board-%s.log" % day.isoformat()))


def minutes_since_last_sweep(now: dt.datetime = None) -> float:
    """Age of today's sweep log in minutes; a very large number if absent."""
    now = now or dt.datetime.now()
    p = log_path(now.date())
    if not p.exists():
        return float("inf")
    return (now.timestamp() - p.stat().st_mtime) / 60.0


def _cooldown_active(now: dt.datetime) -> bool:
    try:
        last = dt.datetime.fromisoformat(_LAST_ALERT.read_text().strip())
    except (OSError, ValueError):
        return False
    return (now - last).total_seconds() / 3600.0 < COOLDOWN_HOURS


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    now = dt.datetime.now()

    if not C.in_selling_window(now):
        print("[watchdog] outside selling hours — nothing to check")
        return 0
    # Don't cry at 10:01 because the first sweep of the day hasn't landed yet.
    start = now.replace(hour=C.DAY_START_HHMM[0], minute=C.DAY_START_HHMM[1],
                        second=0, microsecond=0)
    if (now - start).total_seconds() / 60.0 < STALE_MINUTES:
        print("[watchdog] day just started — too early to judge")
        return 0

    age = minutes_since_last_sweep(now)
    if age <= STALE_MINUTES:
        print("[watchdog] OK — last sweep %.1f min ago" % age)
        return 0

    age_txt = "never today" if age == float("inf") else "%.0f minutes ago" % age
    msg = ("<@%s> :warning: *Alphalete Sales Board sweep has gone quiet* — last run "
           "%s, during selling hours. The board is not updating and the chats "
           "will get nothing. Check the agent is loaded: `lucy rerun "
           "list_agents --machine \"Lucy 1\"`, then `lucy rerun "
           "install_alphalete_sales_board_agent --machine \"Lucy 1\"` to "
           "reload it. Catch the day up with `lucy rerun alphalete_sales_board "
           "--apply --send` (SaraPlus is cumulative, so nothing is lost)."
           % (MEGAN, age_txt))

    if args.dry_run:
        print("[watchdog] STALE (%s) — would post to #claudecorrections:\n%s"
              % (age_txt, msg))
        return 0
    if _cooldown_active(now):
        print("[watchdog] stale (%s) but already alerted inside the cooldown" % age_txt)
        return 0
    try:
        from automations.shared import slack_metrics_post as smp
        client = smp._client()
        client.chat_postMessage(channel=CHANNEL, text=msg)
        _LAST_ALERT.parent.mkdir(parents=True, exist_ok=True)
        _LAST_ALERT.write_text(now.isoformat())
        print("[watchdog] ALERTED — sweep stale (%s)" % age_txt)
    except Exception as e:  # noqa: BLE001 — a watchdog must never crash
        print("[watchdog] alert FAILED (%s: %s)" % (type(e).__name__, str(e)[:120]))
        return 1
    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
