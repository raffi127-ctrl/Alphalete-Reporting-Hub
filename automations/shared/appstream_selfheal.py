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
needs it, and waits for a live token.

IT HEALS THIS MACHINE AND ONLY THIS MACHINE (Megan 2026-09-02: "one machine
CANNOT depend on another, we don't want 1 taking them all down").

It used to run on Lucy 2 alone and push the result to all three. Two things were
wrong with that. The first is availability: Lucy 2 asleep, wedged, or simply
failing to mint meant all three met 4am with a dead token — one box taking the
whole fleet down, which is the arrangement being removed. The second is
identity: since the per-person migration each Lucy signs in as its OWN account,
so handing one machine's storage_state to another does not top up its session,
it REPLACES WHO THAT MACHINE IS, and every office lookup behind it silently
becomes the wrong account's.

So this is installed on ALL THREE Lucys and each heals itself. Three cheap
independent heals beat one shared heal with a single point of failure.

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
# 8 minutes was too short: on the first real run the holder was kickstarted at
# 21:14:26 and the wait expired at 21:22:28 with nothing yet exported. A restart
# re-seeds ownerville BEFORE it touches AppStream, so the export lands minutes
# later. At 3:15 this still finishes by ~3:35, leaving the batch 25 minutes.
RECOVER_WAIT_MIN = 20.0
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


# _push_fleet() DELETED 2026-09-02. It handed this machine's storage_state to
# every machine in APPSTREAM_FLEET_MACHINES (itself included, with no holder
# filter at all). With per-person logins that is an identity swap, not a favour —
# see the module docstring. Each Lucy runs this job and heals itself.


def _alert(reason: str) -> None:
    """Record the failure loudly and let the EXISTING watchers page.

    The first version called alert_thread.post_failure(), which does not exist —
    so the one path meant to say "a human is genuinely needed" raised
    AttributeError and said nothing (2026-08-31, caught on the first real run).

    Rather than invent an alerting path, this leans on the machinery that already
    works: a non-zero exit from a standalone agent is picked up by the didn't-
    run-clean watcher and posted to #claudecorrections-and-requests. That is
    demonstrated — the same watcher paged about this module's own probe minutes
    earlier. One alerting path, already proven, instead of a second one that has
    to be kept working."""
    _log("SELF-HEAL FAILED: %s" % reason)
    _log("exiting non-zero so the didn't-run-clean watcher raises this — a human "
         "is genuinely needed here.")


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
            # NO FLEET PUSH. This machine healed this machine; the others run
            # their own copy of this job on their own accounts. Pushing here
            # would overwrite their identity with ours (see the module docstring).
            _log("this machine can run the batch — no alert needed. The other "
                 "Lucys heal themselves; nothing is pushed from here.")
            return 0

    _alert("the holder restarted but no live token appeared within %.0f min "
           "(ownerville itself may need a human)" % RECOVER_WAIT_MIN)
    return 1


if __name__ == "__main__":
    sys.exit(main())
