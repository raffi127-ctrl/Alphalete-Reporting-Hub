"""Say something when the Blue Ink session dies, instead of failing quietly.

Lucy 2's session expired some time after the 2026-09-07 07:30 send. Every
2-hourly sweep from then on opened a browser, found no session, and exited 2 in
eighteen seconds. That exit code was CORRECT and went nowhere: the sweep
deliberately doesn't publish to the Hub (seven fires a day would drown the
card's history and hide the Monday send), so a real, correctly-signalled
failure had no route to a human. Megan found it the next morning by noticing
checkboxes that hadn't been ticked, and had been ticking them by hand.

So a dead session now opens ONE post in #claudecorrections-and-requests naming
the machine and the exact command to fix it. Through incident_thread, not a
bare message, because:

  - it dedupes by key, so a fourteen-fires-a-day outage is one post, not
    fourteen; the repeats update a status line in the same thread.
  - it can be CLOSED. An alert posted directly can never get its ✅, because
    the tick is put on by the code when the thing next runs clean and only a
    post the machinery opened can be found again. [[project_corrections_slack_channel]]

The session cannot be renewed from here: the account is Google SSO and nothing
in this repo types a password. A human has to re-seed at the machine, which is
exactly why the alert has to reach one.
"""
from __future__ import annotations

import socket

KEY = "blueink_session"
WHAT = "*Blue Ink* session on Lucy 2"

# What a dead session actually looks like coming out of recent_ui / completed.
_DEAD_MARKERS = ("session on this machine has expired", "session is dead",
                 "/login")


def looks_dead(exc: BaseException) -> bool:
    """Is this exception a dead session, rather than some other fault?

    Only a session problem should raise this alarm -- a Blue Ink outage or a
    moved search box is a different problem with a different fix, and crying
    "re-seed the session" at those would train everyone to ignore the alert.
    """
    text = str(exc or "").lower()
    return any(m in text for m in _DEAD_MARKERS)


def _machine() -> str:
    try:
        from automations.day_orchestrator.mini_control import _machine_profile
        name = (_machine_profile() or "").strip()
        if name:
            return name
    except Exception:                      # noqa: BLE001
        pass
    return socket.gethostname()


def alert_dead(exc: BaseException, *, what_failed: str,
               dry_run: bool = False) -> None:
    """Open (or follow up) the one post that tells somebody to re-seed.

    Never raises -- an alert must not be able to break the run that earned it.
    """
    machine = _machine()
    try:
        from automations.shared import incident_thread
        incident_thread.open_or_followup(
            key=KEY,
            title="Blue Ink session on %s has expired" % machine,
            channel_line="*Blue Ink* — the session on %s expired" % machine,
            body=[
                "%s can't read Blue Ink, so **%s is doing nothing** and will "
                "keep doing nothing until somebody signs in again." % (
                    machine, what_failed),
                "Nobody is missing a packet because of this — the SEND refuses "
                "to run without a session rather than risk duplicates. What "
                "stops is the checkbox marking, so the sheet goes stale.",
            ],
            details=[
                "Fix it at *%s* — it needs a human, the account is Google SSO "
                "and nothing here types a password:" % machine,
                "```",
                "cd ~/recruiting-report && .venv/bin/python -m "
                "automations.blueink_docs.session --login",
                "```",
                "Sign in as alphaletemarketing@gmail.com. The next sweep then "
                "catches everyone up on its own.",
            ],
            label="Blue Ink New Start Docs",
            dry_run=dry_run)
    except Exception as e:                 # noqa: BLE001
        print("  ⚠ couldn't raise the Blue Ink session alert (%s: %s)"
              % (type(e).__name__, str(e)[:120]))


def clear(*, dry_run: bool = False) -> None:
    """The session works — close the alert if one is open. Free when none is."""
    try:
        from automations.shared import incident_thread
        incident_thread.resolve_if_open(
            KEY, what=WHAT,
            detail="Signed in again on %s; the checkboxes are being marked "
                   "off as normal." % _machine(),
            dry_run=dry_run)
    except Exception as e:                 # noqa: BLE001
        print("  ⚠ couldn't close the Blue Ink session alert (%s: %s)"
              % (type(e).__name__, str(e)[:120]))
