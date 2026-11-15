"""Open Apex on the Roster and leave it open for a person to look at.

`--signin` checks the sign-in and exits, which closes the window again -- not
what somebody means by "open Apex for me" (2026-11-15).

This opens the browser, signs in from the saved session, clicks through to
Roster -> Employees the way a person would, and then WAITS. Nothing is typed,
nothing is clicked beyond the nav, and nothing is saved. Press Return in the
terminal when you are done and the window closes.

    PYTHONPATH=. .venv/bin/python -m automations.apex_new_starts.open_roster
"""
from __future__ import annotations

from automations.apex_new_starts import apex as AX
from automations.apex_new_starts import drive


def main() -> int:
    with AX.ApexSession(log=print, login_timeout_s=10 * 60) as s:
        page = s.page
        drive.guard_unsaved(page, log=print)
        s.require_login()
        page.wait_for_timeout(1500)
        got = False
        for _ in range(4):
            if drive.to_roster(page, log=print):
                got = True
                break
            page.wait_for_timeout(2500)
        print("")
        if got:
            print("  Apex is open on %s" % page.url)
            print("  Roster -> Employees. The tabs are Active / Pending /")
            print("  Terminated / All Employees. Type a surname into the Last")
            print("  Name filter and press Apply Filters -- the list shows")
            print("  nobody until you do.")
        else:
            print("  Apex is open, but the Roster link never appeared.")
            print("  Use the left-hand nav: ROSTER -> Employees.")
        print("")
        print("  Ignore the 'change your password' banner. It never needs")
        print("  actioning, and typing a URL from it bounces you back to it.")
        print("")
        try:
            input("  Press Return here when you are done (the window closes). ")
        except (EOFError, KeyboardInterrupt):
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
