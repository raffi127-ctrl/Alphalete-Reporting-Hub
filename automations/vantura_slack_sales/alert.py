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
"""
from __future__ import annotations

import sys
from pathlib import Path

REPORT_NAME = "Sales Board Fill ← #alphalete-gp-sales"
RERUN = 'lucy rerun vantura_slack_sales --machine "Lucy 2"'
TAIL_LINES = 25


def _tail(log_path: str, n: int = TAIL_LINES) -> str:
    try:
        lines = Path(log_path).read_text(errors="replace").splitlines()
    except Exception:  # noqa: BLE001 — no log is itself worth reporting
        return "(no log file)"
    return "\n".join(lines[-n:]) or "(log empty)"


def build_message(log_path: str, exit_code: str) -> list[str]:
    """The corrections post. Carries a PASTE TO CLAUDE block so the failure can
    be worked in-thread the moment it lands."""
    return [
        f":rotating_light: *{REPORT_NAME}* failed — exit {exit_code}",
        "",
        "The Sales Board's Base / BOX / AT&T columns did NOT get filled. "
        "If this was the *5:00am* pass, the *5:10am* Sales Boards post will "
        "render an unfilled day.",
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


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    log_path = argv[0] if argv else "(unknown)"
    exit_code = argv[1] if len(argv) > 1 else "?"

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
