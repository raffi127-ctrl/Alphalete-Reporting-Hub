"""Warn the DAY BEFORE the Credico login runs out, so nothing fails.

    python -m automations.credico.login_watch            # check + alert/close
    python -m automations.credico.login_watch --dry-run  # print only

WHY (Megan 2026-10-18: "we should alert the day before the password expires so
that nothing fails"). Credico issues a 14-day token with no refresh
(session.py), and credico_fetch only runs on Thursdays. The fetch already
printed "RENEW NOW" a week ahead — into its own log, where nobody looked — so
every cycle the login died, one weekly Fee Report file was missed, and only
THEN did a ticket open (10/1, 10/15).

This runs every morning in Lucy 1's 4am flow and reads the saved state's
expiry (no browser, no Credico call):

  * expires within WARN_HOURS (or already gone) -> one post in
    #claudecorrections tagging Eve + Megan with the exact re-login steps;
    later mornings fold into the same thread.
  * otherwise -> closes that post if one is open (someone logged in again).

WARN_HOURS = 48 so the 4am pass the morning BEFORE the expiry day always
catches it, whatever hour of the day the token dies.
"""
from __future__ import annotations

import argparse
import sys
from datetime import timezone
from typing import Optional

from automations.credico import session as S

WARN_HOURS = 48
INCIDENT = "credico-login-expiring"
EVE = "U088E2KJEV8"
MEGAN = "U04G5HJBGFN"


def _central(exp) -> str:
    try:
        from zoneinfo import ZoneInfo
        local = exp.astimezone(ZoneInfo("America/Chicago"))
        return local.strftime("%a %-m/%-d %-I:%M %p CT") if sys.platform != "win32" \
            else local.strftime("%a %m/%d %I:%M %p CT")
    except Exception:  # noqa: BLE001
        return exp.strftime("%Y-%m-%d %H:%M UTC")


def lines_for(exp, days_left: Optional[float]) -> list:
    if exp is None:
        head = "*Credico login* — no saved login found on Lucy 1"
    elif days_left is not None and days_left < 0:
        head = "*Credico login* — ran out {}".format(_central(exp))
    else:
        head = "*Credico login* — runs out {}".format(_central(exp))
    return [
        head,
        "<@{}> <@{}> please log in again before then, or the Thursday Fee "
        "Report download fails. It takes about a minute, from any laptop:".format(
            EVE, MEGAN),
        "1. In the Hub folder, run `python -m automations.credico.session --login` "
        "and log in with Carlos's Credico account. Wait for the dashboard.",
        "2. Send it to Lucy 1: `lucy set_credico_state` with the contents of "
        "`automations/shared/.credico_storage_state.json` (or ask Claude to do "
        "both steps).",
        "Credico logins last 14 days and cannot renew themselves. This post "
        "closes on its own the morning after a new login lands.",
    ]


def check(dry_run: bool = False) -> int:
    exp, days = S.session_expiry()
    hours = None if days is None else days * 24
    print("credico login: {}".format(S._expiry_note(exp, days) if exp else
                                     "no saved state"), flush=True)
    from automations.shared import incident_thread as inc
    if exp is not None and hours is not None and hours > WARN_HOURS:
        print("  ok — more than {}h left; nothing to warn about".format(
            WARN_HOURS), flush=True)
        if not dry_run:
            inc.resolve_if_open(
                INCIDENT, what="*Credico login* renewed",
                detail="Good until {}.".format(_central(exp)))
        return 0
    lines = lines_for(exp, days)
    print("\n".join("  " + l for l in lines), flush=True)
    if dry_run:
        return 0
    inc.open_or_followup(key=INCIDENT, title=lines[0], body=lines[1:],
                         needs_human=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="credico.login_watch")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    return check(dry_run=a.dry_run)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
