"""Post a failed Sales Board Fill to the corrections Slack channel.

WHY THIS EXISTS: this report runs on its own LaunchAgent, NOT inside the 4am
day-orchestrator batch — so the orchestrator's failure alerting never sees it.
Left alone, a failure is silent: nobody reads the log, the Hub card is the only
tell, and the 5:10am board post will cheerfully render an unfilled day. This
routes a failure to the same place every other report's failures go
(#claudecorrections-and-requests, `settings.corrections_slack_channel`).

Posts ONLY on a non-zero exit. A run that finds nothing to change is a success
and stays quiet — the evening passes are mostly no-ops by design.

Called from deploy/vantura_slack_sales.sh; not meant to be run by hand.

  python -m automations.vantura_slack_sales.alert <log_path> <exit_code>

Exit 75 is the wrong-week HOLD; anything else non-zero is a failure.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

REPORT_NAME = "Sales Board Fill ← #alphalete-gp-sales"
RERUN = 'lucy rerun vantura_slack_sales --machine "Lucy 2"'
TAIL_LINES = 25

# A wrong-week HOLD alerts ONCE A DAY. The first hold is the one that matters —
# Monday's 4:00pm pass, which leaves an hour to get the new board up before the
# 5:00pm pass fills it — but the board stays un-rolled until a human acts, so
# every later pass that day would repeat the same alert (six on a Monday
# evening). A real FAILURE is never deduped; those are rare and always
# actionable.
HOLD_STATE = Path(__file__).resolve().parents[2] / "output" / ".vslack_hold_alert"
HOLD_EXIT = "75"

# The run prints: The gold WE cell reads '7.26' but Monday 7/27's sales belong
# to week '8.2'. Pull the week it wants so the alert can name it.
WANT_WEEK_RE = re.compile(r"belong to week '([^']+)'")


def _tail(log_path: str, n: int = TAIL_LINES) -> str:
    try:
        lines = Path(log_path).read_text(errors="replace").splitlines()
    except Exception:  # noqa: BLE001 — no log is itself worth reporting
        return "(no log file)"
    return "\n".join(lines[-n:]) or "(log empty)"


def build_message(log_path: str, exit_code: str) -> list[str]:
    """The corrections post. Carries a PASTE TO CLAUDE block so the failure can
    be worked in-thread the moment it lands."""
    if str(exit_code) == HOLD_EXIT:
        # Wrong-week hold — a person has to put the new board up; no amount of
        # retrying fixes it, so say exactly what to do and by when.
        # Nested bold ("*week *8.2**") renders as literal asterisks in Slack —
        # the week goes INSIDE the one bold span, not in its own.
        want = WANT_WEEK_RE.search(_tail(log_path, 400))
        wk = f"week {want.group(1)}" if want else "the new week"
        head = [
            f":warning: *{REPORT_NAME}* is HOLDING — the new week's board "
            f"isn't up yet",
            "",
            f"The gold *WE* cell on the *Sales Board* tab is still on last "
            f"week, so nothing was written — filling now would overwrite last "
            f"week's column.",
            "",
            f"*Set the board to {wk}* (cell `B2`). The "
            f"next hourly pass picks it up on its own — no re-run needed.",
        ]
    else:
        head = [
            f":rotating_light: *{REPORT_NAME}* failed — exit {exit_code}",
            "",
            "The Sales Board's Base / BOX / AT&T columns did NOT get filled. "
            "If this was the *5:00am* pass, the *5:10am* Sales Boards post will "
            "render an unfilled day.",
        ]
    return head + [
        "",
        f"Re-run:  `{RERUN}`",
        "",
        "*PASTE TO CLAUDE*",
        "```",
        f"Report: automations/vantura_slack_sales (runs on Lucy 2, own LaunchAgent "
        f"com.alphalete.vantura-slack-sales)",
        f"Exit code: {exit_code}",
        f"Log: {log_path}",
        "",
        _tail(log_path),
        "```",
    ]


def should_alert(exit_code: str, today: str, state: Path = HOLD_STATE) -> bool:
    """A failure always alerts. A wrong-week hold alerts once a day — see
    HOLD_STATE. Marks the day as alerted as a side effect."""
    if str(exit_code) != HOLD_EXIT:
        return True
    try:
        if state.read_text().strip() == today:
            return False
    except Exception:  # noqa: BLE001 — no state file yet is normal
        pass
    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(today)
    except Exception:  # noqa: BLE001 — never block the alert on bookkeeping
        pass
    return True


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    log_path = argv[0] if argv else "(unknown)"
    exit_code = argv[1] if len(argv) > 1 else "?"

    today = dt.date.today().isoformat()
    if not should_alert(exit_code, today):
        print(f"[alert] hold already reported today ({today}) — staying quiet",
              flush=True)
        return 0

    from automations.day_orchestrator import notify
    from automations.day_orchestrator.registry import load_config

    cfg = load_config()
    ts = notify._post_corrections(
        cfg, None, build_message(log_path, exit_code),
        dry_run=False, tag="vantura_slack_sales-failed")
    # No channel configured, or Slack refused — say so in the log rather than
    # failing, since this is already the error path.
    print(f"[alert] corrections post {'sent' if ts else 'SKIPPED/failed'}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
