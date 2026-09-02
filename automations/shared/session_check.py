"""One-click session check — the mini's desktop button.

Double-click the "Session Check" button on the mini's Desktop to run this. It:
  1. Checks the ownerville/Tableau session (the one the holder keeps warm).
  2. Prints a clear ✅ / ⚠️ summary. Ownerville (24h token) is judged on whether
     it lasts to the next 4am batch; AppStream (~2h token, re-minted by the
     holder) is judged on whether it is live RIGHT NOW — asking it to cover
     tomorrow's batch is a question it can never answer yes to.
  3. If ownerville WON'T survive, it restarts the session-holder so its login
     window comes up for you to log into.
  4. Checks the AppStream recruiting session too. It does NOT self-heal:
     the form login went back behind an interactive check in the 2026-08-20
     release, so only a human re-seed mints a new token.

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
          f"(ownerville needs to last until {threshold:%-I:%M %p})")
    print("════════════════════════════════════════════════\n")

    # Ownerville / Tableau — the one session the holder keeps warm.
    s = session_status(OWNERVILLE_STORAGE_STATE, "Ownerville / Tableau")
    ov_survives = bool(s["ok"] and s["rqst_expiry"]
                       and s["rqst_expiry"] >= threshold)
    print(f"  {'✅' if ov_survives else '⚠️ '} Ownerville / Tableau")
    print(f"      {s['reason']}\n")

    # APPSTREAM SELF-HEALS AGAIN (2026-09-02) — the note that used to sit here
    # said it did not, and that was drawn from a premise since measured wrong.
    # The story: between 2026-06-30 and the 2026-08-20 release Cloudflare
    # auto-passed and each report drove its own login. The 8/20 release looked
    # like it had put an interactive check in front of the form, so this screen
    # was rewritten to say a human re-seed was the only way back. It had not.
    # The check clears itself given ~30s before submit; at the 3s pause we were
    # using, the submit landed mid-check and the login failed, which read as
    # "gated" instead of "too fast". Twelve days of believing that is why four
    # runs died on 8/24 with nobody able to do anything but wait for a person.
    # Reporting the session is still right — a button that reports a session it
    # never reads is worse than no button — but the remedy is no longer a human.
    # Judged in the PRESENT TENSE, unlike ownerville above. AppStream's rqst TTL
    # is ~2h, so it can NEVER reach `threshold` (next 4am + 90 min) — this button
    # asked an impossible question and answered "⚠️ needs a fresh login" every
    # single time, on a session the holder was re-minting fine. That is the same
    # bug appstream_watch was paging on; see false alarm #2 in its module
    # docstring. What carries the batch is the holder's re-hop, not the token
    # sitting on disk, so the honest question is "is it valid right now".
    ap = session_status(APPSTREAM_STORAGE_STATE, "AppStream (recruiting)")
    ap_survives = bool(ap["ok"])
    print(f"  {'✅' if ap_survives else '⚠️ '} AppStream (recruiting)")
    print(f"      {ap['reason']}")
    if ap_survives:
        print("      (the session-holder re-mints this every ~2h on its own — "
              "a short window here is normal, not a problem)")
    print()

    if ov_survives and ap_survives:
        print("✅  Ownerville is good through tomorrow's 4am run, and AppStream "
              "is live right now.")
        print("    You're set — nothing to do.\n")
        return 0
    if not ap_survives:
        print("──────────────────────────────────────────────────")
        print("  AppStream has no live token this minute. The session-holder")
        print("  normally re-mints one within a few minutes — check again")
        print("  before logging in by hand. If it stays empty, re-seed it:")
        print("  Run:  PYTHONPATH=. .venv/bin/python -m "
              "automations.shared.tableau_patchright --appstream-login")
        print("  and clear the 'verify you're human' box.")
        print("──────────────────────────────────────────────────\n")
    if ov_survives:
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
