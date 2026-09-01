"""Re-capture the AppStream session BEFORE it dies, with no human.

    python -m automations.shared.appstream_autorenew            # renew + push
    python -m automations.shared.appstream_autorenew --check     # report only

WHY (Megan 2026-09-01, after her THIRD login of the day: "this CANNOT keep
happening"). The rqst token lives ~2h. Logins that day: 05:49, 08:01, 13:28 —
that cadence IS the token's lifetime, because nothing renewed it:

  * the holder's in-loop mint asks ownerville for a token and gets back the one
    it already has ("ownerville's warm page keeps handing back the token it
    already issued"), then re-keys the console with a dead token, so #searchMC
    never renders — every `mint FAILED` line in session_holder.out.log
  * the restart escape hatch, which minted on 8/29, failed twice on 9/1
    (03:35 and 07:59) — ownerville would not issue

THE MEASUREMENT THAT CHANGED THIS. `--appstream-login` re-run against a profile
whose session is STILL ALIVE completes unattended: "✅ Saved AppStream session
(10 cookies, 2 rqst token(s))" in under 55 seconds with nobody at the browser.
The human is only ever needed once the profile has gone COLD — and it goes cold
because we wait for the token to die before trying.

So stop waiting. Renew on a timer while the session is warm, and the login is a
once-in-a-while seed instead of a five-times-a-day interruption.

This does NOT replace the human seed: if the profile has gone cold it exits
non-zero and the existing watcher pages, exactly as before. It removes the
routine case, not the fallback.
"""
from __future__ import annotations  # Lucy 1 / mini run Python 3.9

import argparse
import datetime as dt
import json
import sys
import time

# Renew when the token has less than this left. Comfortably inside the ~2h TTL
# so a failed attempt still leaves room for the next tick AND for a human, and
# comfortably above the tick interval so we never thrash.
RENEW_UNDER_MIN = 75.0
# A token this fresh means someone/something just renewed — nothing to do.
HEALTHY_MIN = 90.0


def _log(msg: str) -> None:
    print("[%s] %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg),
          flush=True)


def token_minutes_left() -> float:
    """Minutes on the saved session's longest-lived rqst token. 0.0 = none.

    Reads the exported storage_state rather than opening a browser: this runs on
    a timer next to real reports, and a browser launch is both slow and a way to
    disturb the session being measured."""
    from automations.shared.tableau_patchright import APPSTREAM_STORAGE_STATE
    try:
        blob = json.loads(APPSTREAM_STORAGE_STATE.read_text())
    except Exception:  # noqa: BLE001 — missing/unreadable is simply "no session"
        return 0.0
    now = time.time()
    best = 0.0
    for c in blob.get("cookies", []):
        if not str(c.get("name") or "").startswith("rqst"):
            continue
        exp = c.get("expires")
        # A session cookie carries no expiry we can reason about. Treating it as
        # alive is how a dead token gets pushed to three machines.
        if not isinstance(exp, (int, float)) or exp <= 0:
            continue
        best = max(best, (exp - now) / 60.0)
    return max(0.0, best)


def _push_fleet() -> bool:
    """Hand the fresh session to every machine that runs AppStream reports."""
    from automations.shared.tableau_patchright import APPSTREAM_STORAGE_STATE
    from automations.shared.session_holder import APPSTREAM_FLEET_MACHINES
    from automations.day_orchestrator import mini_control as mc
    try:
        blob = APPSTREAM_STORAGE_STATE.read_text()
    except Exception as e:  # noqa: BLE001
        _log("cannot read the session to push: %s" % str(e)[:120])
        return False
    ok = True
    for machine in APPSTREAM_FLEET_MACHINES:
        try:
            mc.enqueue("set_appstream_state", blob, by="appstream-autorenew",
                       machine=machine)
            _log("queued session -> %s" % machine)
        except Exception as e:  # noqa: BLE001
            _log("could not queue to %s: %s" % (machine, str(e)[:120]))
            ok = False
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="report the token's remaining life and exit 0")
    ap.add_argument("--force", action="store_true",
                    help="re-capture even if the token looks healthy")
    ap.add_argument("--under", type=float, default=RENEW_UNDER_MIN,
                    help="renew when fewer than this many minutes remain")
    a = ap.parse_args(argv)

    left = token_minutes_left()
    _log("saved AppStream token: %.0f min left (renew under %.0f)"
         % (left, a.under))
    if a.check:
        # --check REPORTS; it does not judge. A low token is the normal state
        # this exists to observe, and exiting non-zero for it would post a red
        # incident about a probe that worked perfectly — the same crying-wolf
        # that appstream_selfheal --check had to have removed on 2026-08-31.
        return 0

    if left >= a.under and not a.force:
        _log("still healthy — nothing to do, staying silent")
        return 0

    _log("re-capturing while the profile session is still warm "
         "(this is the whole point: a cold profile is what needs a human)")
    from automations.shared.tableau_patchright import _capture_appstream_state
    try:
        ok = _capture_appstream_state(verbose=True)
    except Exception as e:  # noqa: BLE001 — never take the timer down
        _log("capture raised %s: %s" % (type(e).__name__, str(e)[:160]))
        ok = False

    after = token_minutes_left()
    if not ok or after <= left:
        _log("UNATTENDED RENEW FAILED (%.0f min on the token) — the profile has "
             "gone cold, so this one genuinely needs a human seed:" % after)
        _log("  PYTHONPATH=. .venv/bin/python -m "
             "automations.shared.tableau_patchright --appstream-login")
        return 1

    _log("renewed: %.0f min on the new token" % after)
    if not _push_fleet():
        _log("renewed but could not push to the whole fleet")
        return 1
    _log("fleet pushed — no human was needed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
