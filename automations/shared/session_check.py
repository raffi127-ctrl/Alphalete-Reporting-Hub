"""One-click session readiness check + reseed launcher — the mini's desktop button.

Double-click the "Session Check" button on the mini's Desktop to run this. It:
  1. Checks the ownerville/Tableau + AppStream rqst tokens.
  2. Prints a clear ✅ / ⚠️ summary (and whether each lasts to the next 4am batch).
  3. If a session WON'T survive (or is dead), it LAUNCHES the login you need:
       • AppStream  → opens the --appstream-login browser (sign in as
         alphaletereporting@gmail.com, clear the Cloudflare box).
       • Ownerville → restarts the session-holder so its ownerville login
         window comes up to log into.
  4. All sessions good → it just says so and exits.

Run on the mini:
    PYTHONPATH=. .venv/bin/python -m automations.shared.session_check
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys

from automations.shared.appstream_watch import (
    session_status, _next_4am, SURVIVAL_BUFFER_MIN,
)
from automations.shared.tableau_patchright import (
    APPSTREAM_STORAGE_STATE, OWNERVILLE_STORAGE_STATE,
)

SESSION_HOLDER_LABEL = "com.alphalete.session-holder"


def main() -> int:
    now = dt.datetime.now()
    threshold = _next_4am(now) + dt.timedelta(minutes=SURVIVAL_BUFFER_MIN)
    print("════════════════════════════════════════════════")
    print("   MINI SESSION CHECK")
    print(f"   {now:%a %b %-d  %-I:%M %p}   "
          f"(needs to last until {threshold:%-I:%M %p})")
    print("════════════════════════════════════════════════\n")

    need_appstream = need_ownerville = False
    for path, what in ((OWNERVILLE_STORAGE_STATE, "Ownerville / Tableau"),
                       (APPSTREAM_STORAGE_STATE, "AppStream (recruiting)")):
        s = session_status(path, what)
        survives = bool(s["ok"] and s["rqst_expiry"]
                        and s["rqst_expiry"] >= threshold)
        print(f"  {'✅' if survives else '⚠️ '} {what}")
        print(f"      {s['reason']}\n")
        if not survives:
            if "AppStream" in what:
                need_appstream = True
            else:
                need_ownerville = True

    if not (need_appstream or need_ownerville):
        print("✅  All sessions are good through tomorrow's 4am run.")
        print("    Nothing to do — you're set.\n")
        return 0

    print("──────────────────────────────────────────────────")
    print("  A session needs a fresh login — launching it now.")
    print("  Log in and clear any 'verify you're human' box.")
    print("──────────────────────────────────────────────────\n")

    if need_ownerville:
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

    if need_appstream:
        print(">> Opening the AppStream login "
              "(sign in as alphaletereporting@gmail.com)…\n")
        try:
            subprocess.run(
                [sys.executable, "-m",
                 "automations.shared.tableau_patchright", "--appstream-login"],
                check=False)
        except Exception as e:
            print(f"   (couldn't open the AppStream login: "
                  f"{type(e).__name__}: {e})\n")

    print("\n✅  Done. Re-run this check to confirm everything's green.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
