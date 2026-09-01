"""Get the fleet a live AppStream session before the 4am batch, with no human.

WHY (Megan 2026-08-31: "I'm not up at 3:30 which is why this can't be a manual
thing all the dang time"). The rqst SSO token lives ~2h. Nothing between
midnight and 4am uses the console, and the holder's in-loop mint has been
failing since 8/29 — it re-reads the SAME token off ownerville's warm page
(43A275AE on 8/29, 66F074FE on 8/31, each re-keyed twice and rejected) rather
than obtaining a new one. So the token simply dies overnight and the 4am batch
meets a dead session.

What DOES mint is a holder RESTART: it builds a fresh browser context instead of
re-reading a cached page. Recorded on Lucy 1 on 8/29 — token counted down to
`1m left` at 08:04, the holder restarted on a code change at 08:10, and at 08:11
it was handing a fresh token to the fleet: "the restart minted what four re-hop
cycles could not."

So this runs BEFORE the batch, restarts the holder only if the session actually
needs it, waits for a live token, and pushes it to all three machines. Lucy 2 is
the sole holder (APPSTREAM_HOLD_MACHINES) and donates to Lucy 1 and Lucy 3, so
one heal here covers the fleet.

It alerts ONLY if it could not recover. A run that heals is silent — that is the
point: the alert should mean "a human is genuinely needed", not "3am happened".

    python -m automations.shared.appstream_selfheal            # heal if needed
    python -m automations.shared.appstream_selfheal --check     # report, change nothing
    python -m automations.shared.appstream_selfheal --force     # restart even if live
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time

# A token with less than this left will not survive the batch, so it is treated
# as dead NOW rather than dying halfway through the 4am reports.
MIN_MINUTES_FOR_BATCH = 90.0
# How long to give the holder to come back with a live token after a restart.
RECOVER_WAIT_MIN = 8.0
POLL_SECONDS = 20


def _log(msg: str) -> None:
    print("[%s] %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg),
          flush=True)


def token_minutes_left() -> float:
    """Minutes until the saved session's rqst token expires. 0.0 = none/dead.

    Reads the exported storage_state rather than opening a browser: this runs at
    3am on a machine doing nothing else, and a browser launch is both slow and a
    way to disturb the very session being measured."""
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
        # -1 (session cookie) carries no expiry we can reason about. Treat it as
        # unknown-but-present rather than infinite: claiming a session cookie is
        # alive is how a dead token gets pushed to three machines.
        if not isinstance(exp, (int, float)) or exp <= 0:
            continue
        best = max(best, (exp - now) / 60.0)
    return max(0.0, best)


def _restart_holder() -> bool:
    """Kickstart the session holder so it builds a FRESH context."""
    for label in ("gui/%d/com.alphalete.session-holder" % _uid(),
                  "com.alphalete.session-holder"):
        try:
            r = subprocess.run(["launchctl", "kickstart", "-k", label],
                               capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                _log("holder kickstarted (%s)" % label)
                return True
        except Exception as e:  # noqa: BLE001
            _log("kickstart %s failed: %s" % (label, str(e)[:100]))
    _log("could NOT kickstart the session holder")
    return False


def _uid() -> int:
    import os
    return os.getuid()


def _push_fleet() -> bool:
    """Hand the freshly-minted session to every machine that runs AppStream."""
    from automations.shared.tableau_patchright import APPSTREAM_STORAGE_STATE
    try:
        blob = APPSTREAM_STORAGE_STATE.read_text()
    except Exception as e:  # noqa: BLE001
        _log("cannot read the session to push: %s" % str(e)[:100])
        return False
    from automations.day_orchestrator import mini_control as mc
    from automations.shared.session_holder import APPSTREAM_FLEET_MACHINES
    ok = True
    for machine in APPSTREAM_FLEET_MACHINES:
        try:
            mc.enqueue("set_appstream_state", blob, by="appstream-selfheal",
                       machine=machine)
            _log("queued session -> %s" % machine)
        except Exception as e:  # noqa: BLE001
            _log("could not queue to %s: %s" % (machine, str(e)[:100]))
            ok = False
    return ok


def _alert(reason: str) -> None:
    """Only ever called when the heal FAILED and a person is actually needed."""
    try:
        from automations.shared import alert_thread
        alert_thread.post_failure(
            report_id="appstream_selfheal",
            summary=("AppStream self-heal could not get a live session before "
                     "the 4am batch: %s" % reason))
        _log("alerted: %s" % reason)
    except Exception as e:  # noqa: BLE001 — never let alerting mask the result
        _log("ALERT FAILED (%s) — original problem: %s" % (str(e)[:80], reason))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="report the token's remaining life and exit")
    ap.add_argument("--force", action="store_true",
                    help="restart the holder even if the session looks healthy")
    ap.add_argument("--min-minutes", type=float, default=MIN_MINUTES_FOR_BATCH)
    a = ap.parse_args(argv)

    left = token_minutes_left()
    _log("saved AppStream token: %.0f min left (need %.0f to clear the batch)"
         % (left, a.min_minutes))
    if a.check:
        # ALWAYS 0. --check reports; it does not judge. It is wired to a registry
        # entry, and the run wrapper reads any non-zero exit as a FAILED report —
        # so returning 1 for "the token is low" posted a red incident to
        # #claudecorrections-and-requests about a probe that worked perfectly
        # (2026-08-31). A low token is the normal state this exists to observe,
        # and paging about it is the crying-wolf we are trying to remove.
        _log("check only — nothing changed. The 3:15am agent is what heals.")
        return 0

    if left >= a.min_minutes and not a.force:
        _log("session is healthy — nothing to do, staying silent")
        return 0

    _log("session will not survive the batch — restarting the holder to mint")
    if not _restart_holder():
        _alert("the session holder could not be restarted")
        return 1

    deadline = time.time() + RECOVER_WAIT_MIN * 60
    while time.time() < deadline:
        time.sleep(POLL_SECONDS)
        left = token_minutes_left()
        if left >= a.min_minutes:
            _log("recovered: %.0f min on the new token" % left)
            if not _push_fleet():
                _alert("minted a session but could not push it to the fleet")
                return 1
            _log("fleet pushed — 4am can run, no alert needed")
            return 0

    _alert("the holder restarted but no live token appeared within %.0f min "
           "(ownerville itself may need a human)" % RECOVER_WAIT_MIN)
    return 1


if __name__ == "__main__":
    sys.exit(main())
