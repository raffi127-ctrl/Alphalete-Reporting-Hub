"""One-click session check — the mini's desktop button.

Double-click the "Session Check" button on the mini's Desktop to run this. It:
  1. Checks the ownerville/Tableau session (the one the holder keeps warm).
  2. Prints a clear ✅ / ⚠️ summary (does it last to the next 4am batch?).
  3. If ownerville WON'T survive, it restarts the session-holder so its login
     window comes up for you to log into.
  4. AppStream needs nothing — each report self-heals by driving its own
     rcaptain login at run time (Cloudflare auto-passes again, 2026-06-30).

Run on the mini:
    PYTHONPATH=. .venv/bin/python -m automations.shared.session_check
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess

from automations.shared.appstream_watch import (
    session_status, _next_4am, SURVIVAL_BUFFER_MIN,
)
from automations.shared.tableau_patchright import OWNERVILLE_STORAGE_STATE

SESSION_HOLDER_LABEL = "com.alphalete.session-holder"


def main() -> int:
    now = dt.datetime.now()
    threshold = _next_4am(now) + dt.timedelta(minutes=SURVIVAL_BUFFER_MIN)
    print("════════════════════════════════════════════════")
    print("   MINI SESSION CHECK")
    print(f"   {now:%a %b %-d  %-I:%M %p}   "
          f"(needs to last until {threshold:%-I:%M %p})")
    print("════════════════════════════════════════════════\n")

    # Ownerville / Tableau — the one session the holder keeps warm.
    s = session_status(OWNERVILLE_STORAGE_STATE, "Ownerville / Tableau")
    ov_survives = bool(s["ok"] and s["rqst_expiry"]
                       and s["rqst_expiry"] >= threshold)
    print(f"  {'✅' if ov_survives else '⚠️ '} Ownerville / Tableau")
    print(f"      {s['reason']}\n")

    # AppStream self-heals inside each report now (drives the rcaptain login at
    # run time), so there's nothing to reseed here anymore.
    print("  ✅ AppStream (recruiting)")
    print("      Self-heals at run time — each report logs itself in. "
          "Nothing to do.\n")

    if ov_survives:
        print("✅  Ownerville is good through tomorrow's 4am run.")
        print("    AppStream handles itself. You're set — nothing to do.\n")
        return 0

    print("──────────────────────────────────────────────────")
    print("  Ownerville needs a fresh login — opening it now.")
    print("  Log in and clear any 'verify you're human' box.")
    print("──────────────────────────────────────────────────\n")
    print(">> Restarting the session-holder so its ownerville window opens…")
    try:
        subprocess.run(
            ["launchctl", "kickstart", "-k",
             f"gui/{os.getuid()}/{SESSION_HOLDER_LABEL}"],
            check=False)
        print("   → Log into ownerville in the holder's Chrome window, "
              "then re-run this check.\n")
    except Exception as e:
        print(f"   (couldn't restart the holder: {type(e).__name__}: {e})\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
