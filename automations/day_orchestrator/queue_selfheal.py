"""A Lucy restarts its OWN queue reader when it has gone silent.

WHY (2026-10-20). Lucy 1's Mini Control queue stopped taking work at 17:56.
Lucy 3's watcher saw it and opened a ticket whose fix was "someone at Lucy 1:
run launchctl kickstart" -- the queue that would carry that fix was the thing
that was dead, and nobody was at the office. Machines heal themselves
([[feedback_machines_never_depend_on_each_other]]), so this runs ON the Lucy,
from a job that is already scheduled there and pulls its own code
(deploy/ad_photo_threads.sh, every 30 min), and kicks its own poller.

Evidence = the shared heartbeat the read lane stamps every 10 min
(silent_job_watch, mini_control_<machine>). Conservative on purpose:
  * an unreadable heartbeat sheet (Sheets throttling) is "don't know" -> no kick;
  * only a beat older than STALE_MIN counts as silent;
  * at most one kick per KICK_EVERY_MIN, so a beat that can't land can't loop it;
  * only on a machine where the mini-control agent is installed.
Never raises.
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
from pathlib import Path
from typing import Callable, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
STAMP = REPO_ROOT / "output" / "state" / "queue_selfheal.stamp"
LABELS = ("com.alphalete.mini-control", "com.alphalete.mini-control-read",
          "com.alphalete.mini-control-text")
STALE_MIN = 25
KICK_EVERY_MIN = 30


def _installed(label: str) -> bool:
    try:
        r = subprocess.run(["launchctl", "print", "gui/%d/%s" % (os.getuid(), label)],
                           capture_output=True, timeout=20)
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _last_beat(job_id: str) -> Optional[dt.datetime]:
    from automations.shared import silent_job_watch as sjw
    return (sjw.read_beats().get(job_id) or {}).get("last_seen")


def should_kick(last_seen: Optional[dt.datetime], last_kick: Optional[dt.datetime],
                now: dt.datetime) -> bool:
    if last_seen is None:
        return False                      # can't read it -> don't guess
    if now - last_seen < dt.timedelta(minutes=STALE_MIN):
        return False
    if last_kick and now - last_kick < dt.timedelta(minutes=KICK_EVERY_MIN):
        return False
    return True


def kick_if_stale(*, log: Callable[[str], None] = print,
                  now: Optional[dt.datetime] = None) -> bool:
    """True if it restarted this machine's queue reader."""
    try:
        if not _installed(LABELS[0]):
            return False
        from automations.shared import silent_job_watch as sjw
        now = now or dt.datetime.now()
        seen = _last_beat(sjw.job_id_for_machine("mini_control"))
        try:
            last_kick = dt.datetime.fromtimestamp(STAMP.stat().st_mtime)
        except OSError:
            last_kick = None
        if not should_kick(seen, last_kick, now):
            return False
        STAMP.parent.mkdir(parents=True, exist_ok=True)
        STAMP.write_text(now.isoformat(timespec="seconds"), encoding="utf-8")
        for label in LABELS:
            if _installed(label):
                subprocess.run(["launchctl", "kickstart", "-k",
                                "gui/%d/%s" % (os.getuid(), label)],
                               capture_output=True, timeout=30)
        log("[queue-selfheal] queue reader silent since %s -- restarted %s"
            % (seen.isoformat(timespec="minutes"), ", ".join(LABELS)))
        return True
    except Exception as e:  # noqa: BLE001 — a self-heal must never break its host job
        log("[queue-selfheal] skipped (%s)" % type(e).__name__)
        return False


if __name__ == "__main__":
    kick_if_stale()
