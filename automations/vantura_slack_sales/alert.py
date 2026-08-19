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

# One thread PER KIND OF PROBLEM (Eve 2026-08-14). A crash, a wrong-week hold and
# a sale that landed on nobody's row are three different stories — sharing one
# thread would bury whichever is not today's. Each repeat replies in its own.
INC_FAILED = "vantura-sales-failed"
INC_HOLD = "vantura-sales-week-hold"
INC_UNKNOWN = "vantura-sales-unknown-poster"
INC_ROLL = "vantura-sales-roll-due"

# The run prints: The gold WE cell reads '7.26' but Monday 7/27's sales belong
# to week '8.2'. Pull both weeks so the alert can name them.
WANT_WEEK_RE = re.compile(r"belong to week '([^']+)'")
SHOWN_WEEK_RE = re.compile(r"gold WE cell reads '([^']+)'")
# run.py prints one "HELD DAY: 2026-08-18" line per day it refused to write.
HELD_DAY_RE = re.compile(r"^HELD DAY: (\d{4}-\d{2}-\d{2})", re.M)


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
        tail = _tail(log_path, 400)
        want = WANT_WEEK_RE.search(tail)
        wk = f"week {want.group(1)}" if want else "the new week"
        shown = SHOWN_WEEK_RE.search(tail)
        on = f"reads *{shown.group(1)}*" if shown else "is on an older week"
        head = [
            f":warning: *{REPORT_NAME}* is HOLDING — the board isn't on the "
            f"week being filled",
            "",
            f"The gold *WE* cell on the *Sales Board* tab {on}, so nothing was "
            f"written — filling now would overwrite that week's column.",
            "",
            f"*Set the board to {wk}* (cell `B2`).",
        ]
        # Days already in the past do NOT come back on their own: the 4-9pm
        # passes fill the day in progress and the 5:00am pass closes out the day
        # before it, so nobody ever returns to Tuesday once Wednesday started.
        # Saying "the next pass picks it up" there is how Tue 8/18 sat empty for
        # two days (Eve 2026-08-19).
        stale = [d for d in HELD_DAY_RE.findall(tail)
                 if d < dt.date.today().isoformat()]
        if stale:
            head += [
                "",
                ":exclamation: Rolling the board is *not enough* for "
                + ", ".join(stale)
                + " — no later pass returns to a day that is already past. "
                  "After the roll, run one per day:",
                "```",
                *[f'lucy rerun vantura_slack_sales --date {d} '
                  f'--machine "Lucy 2"' for d in stale],
                "```",
            ]
        else:
            head += ["", "The next hourly pass picks it up on its own — no "
                         "re-run needed."]
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


# Unknown-poster alerts dedupe on the SET of ids, once a day: the fill runs
# seven times a day and the same nameless rep would otherwise ping seven times.
# A NEW id appearing later the same day changes the set, so it still alerts.
UNKNOWN_STATE = Path(__file__).resolve().parents[2] / "output" / ".vslack_unknown_alert"


def build_unknown_message(unknown, scope_ok: bool, hints=None) -> list[str]:
    """The corrections post for sales that landed on no rep's row.

    `unknown` is [(slack id, campaign, count)] — the poster is real, they sold,
    and their board row reads 0 because nothing here can turn the id into a
    name. Every hour this stays unfixed is an hour of wrong daily standings.
    """
    total = sum(c for _u, _camp, c in unknown)
    lines = [
        f":warning: *{REPORT_NAME}* — {total} sale(s) landed on *no rep's row*",
        "",
        "Slack gave no name for these posters, so their sales are in the day's "
        "TOTAL but on nobody's line. The 5:10am board post will render them as "
        "zeros:",
        "",
    ]
    hints = hints or {}
    for uid, camp, count in unknown:
        lines += [f"  • `{uid}` — {count} {camp} sale(s)"]
        # The teammates already said who this is. Quote them, so nobody has to
        # go digging through the channel to name a rep.
        for h in hints.get(uid, []):
            lines.append(f"       ↳ thread says: _{h}_")
    lines += [
        "",
        "*To fix:* reply here with the rep's name (the thread lines above "
        "usually say it outright) — or add the id to `KNOWN_USERS` in "
        "`automations/vantura_slack_sales/run.py` yourself.",
    ]
    if not scope_ok:
        lines += [
            "",
            f":key: This keeps happening because the Slack token can't read the "
            f"user directory. Permanent fix: {SCOPE_FIX_HINT}",
        ]
    return lines + [
        "",
        "*PASTE TO CLAUDE*",
        "```",
        "Report: automations/vantura_slack_sales — unknown Slack posters",
        "Unnamed ids with sales: "
        + ", ".join(f"{u} ({c} {camp})" for u, camp, c in unknown),
        "```",
    ]


SCOPE_FIX_HINT = (
    "Slack app config -> OAuth & Permissions -> User Token Scopes -> add "
    "`users:read` -> Reinstall to Workspace -> re-save the token on Lucy 2."
)


def alert_unknown_posters(unknown, scope_ok: bool, hints=None,
                          state: Path = UNKNOWN_STATE) -> bool:
    """Post the unknown-poster warning, at most once a day per set of ids."""
    key = dt.date.today().isoformat() + "|" + ",".join(
        sorted(u for u, _c, _n in unknown))
    try:
        if state.read_text().strip() == key:
            print("[alert] same unknown posters already reported today",
                  flush=True)
            return False
    except Exception:  # noqa: BLE001 — no state file yet is normal
        pass
    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(key)
    except Exception:  # noqa: BLE001 — never block the alert on bookkeeping
        pass

    from automations.day_orchestrator import notify
    from automations.day_orchestrator.registry import load_config

    lines = build_unknown_message(unknown, scope_ok, hints)
    ts = notify.post_alert(
        lines[0], lines[1:], tag="vantura_slack_sales-unknown-poster",
        cfg=load_config(), incident=INC_UNKNOWN)
    print(f"[alert] unknown-poster post {'sent' if ts else 'SKIPPED/failed'}",
          flush=True)
    return bool(ts)


def resolve_all(*, dry_run: bool = False) -> None:
    """A clean EXIT closes the crash and week-hold threads.

    The wrapper only ever called alert.py on a NON-ZERO exit, so these alerts
    were write-only: the channel heard when the fill broke and never heard when
    it came back (Eve 2026-08-14). Free when nothing is open.

    Deliberately NOT the unknown-poster thread: a run can exit 0 and still have
    a sale on nobody's row, so closing that on the exit code would erase a live
    problem. run.py closes it when the unmatched list is actually empty."""
    from automations.shared import incident_thread as inc
    for key, what in ((INC_FAILED, "*{}*".format(REPORT_NAME)),
                      (INC_HOLD, "*{}* — the week hold cleared".format(REPORT_NAME))):
        inc.resolve_if_open(key, what=what, dry_run=dry_run)


# The Monday roll reminder fires from the 5:00am pass, at most once a day.
ROLL_STATE = Path(__file__).resolve().parents[2] / "output" / ".vslack_roll_alert"


def build_roll_message(shown: str, want: str) -> list[str]:
    """The Monday heads-up: the board still has to be rolled TODAY."""
    return [
        f":calendar: *{REPORT_NAME}* — the Sales Board still has to be rolled "
        f"to week {want} today",
        "",
        f"This morning's pass ran fine: it was closing out Sunday, which lives "
        f"on the week the board shows now (*{shown}*). But the *4:00pm* pass "
        f"fills MONDAY, and Monday's sales live on week *{want}*.",
        "",
        f"*Set cell `B2` on the Sales Board tab to {want}* before 4:00pm. "
        f"Careful with the picker — the previous weeks sit right under the one "
        f"you want, and a wrong pick reads exactly like a board that was never "
        f"rolled.",
        "",
        "Nothing is broken yet. If the board isn't up by 4:00pm the fill starts "
        "HOLDING instead, and each day it holds needs its own catch-up run.",
    ]


def remind_roll(shown: str, want: str, state: Path = ROLL_STATE) -> bool:
    """Post the Monday roll reminder, at most once a day."""
    today = dt.date.today().isoformat()
    try:
        if state.read_text().strip() == today:
            print("[alert] roll reminder already posted today", flush=True)
            return False
    except Exception:  # noqa: BLE001 — no state file yet is normal
        pass
    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(today)
    except Exception:  # noqa: BLE001 — never block the alert on bookkeeping
        pass

    from automations.day_orchestrator import notify
    from automations.day_orchestrator.registry import load_config

    lines = build_roll_message(shown, want)
    ts = notify.post_alert(lines[0], lines[1:], tag="vantura_slack_sales-roll-due",
                           cfg=load_config(), incident=INC_ROLL)
    print(f"[alert] roll reminder {'sent' if ts else 'SKIPPED/failed'}",
          flush=True)
    return bool(ts)


def resolve_roll(*, dry_run: bool = False) -> bool:
    """An afternoon pass wrote into a rolled board — the reminder is done."""
    from automations.shared import incident_thread as inc
    return inc.resolve_if_open(
        INC_ROLL, what="*{}* — the board is on the new week".format(REPORT_NAME),
        dry_run=dry_run)


def resolve_unknown(*, dry_run: bool = False) -> bool:
    """Every sale matched a rep — close the unknown-poster thread."""
    from automations.shared import incident_thread as inc
    return inc.resolve_if_open(
        INC_UNKNOWN,
        what="*{}* — every sale landed on a rep's row".format(REPORT_NAME),
        detail="_No unnamed posters this run._", dry_run=dry_run)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    log_path = argv[0] if argv else "(unknown)"
    exit_code = argv[1] if len(argv) > 1 else "?"

    # A clean run closes whatever this module left open and says nothing else —
    # the wrapper now hands us every exit, not just the bad ones.
    if str(exit_code) == "0":
        resolve_all()
        return 0

    today = dt.date.today().isoformat()
    if not should_alert(exit_code, today):
        print(f"[alert] hold already reported today ({today}) — staying quiet",
              flush=True)
        return 0

    from automations.day_orchestrator import notify
    from automations.day_orchestrator.registry import load_config

    cfg = load_config()
    lines = build_message(log_path, exit_code)
    ts = notify.post_alert(
        lines[0], lines[1:], tag="vantura_slack_sales-failed", cfg=cfg,
        incident=(INC_HOLD if str(exit_code) == HOLD_EXIT else INC_FAILED))
    # No channel configured, or Slack refused — say so in the log rather than
    # failing, since this is already the error path.
    print(f"[alert] corrections post {'sent' if ts else 'SKIPPED/failed'}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
