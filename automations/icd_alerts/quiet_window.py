"""A real browser window that nobody sees.

Megan, 2026-11-13: "let's make it so everything runs in the background ... they
almost don't even know that Lucy is running on their machine."

Most of Lucy ECO already runs in a hidden browser. A few sites will not finish
for one -- OwnerVille's security check on the password step is the first --
so those get a REAL window. This is how that window stays out of the owner's
way: the app is hidden the instant it comes forward and whatever the owner
was using is put back in front, for as long as the guard is held. It is the
treatment resume pushing has had since 2026-10-21 (`resume_push._FocusGuard`,
measured there: hidden, Chrome still runs its timers and takes clicks at full
speed with the three flags below), made usable for any browser profile.

MAC ONLY for now, and A TRIAL: `TRIAL_OFFICES` says whose computer uses it.
One office first, because the thing being changed is a sign-in, and a sign-in
that stops clearing would cost that office its knocks board.

IT PROVES ITSELF OR STEPS ASIDE. The first time a hidden sign-in does not get
in, `note_failed` leaves a note on that computer and every later sign-in
there opens the window in view exactly as before. Both outcomes are filed as
a `probe-ov-quiet` note, so the answer can be read from here.
"""
from __future__ import annotations

import datetime as dt
import platform
import subprocess
import threading
import time
from pathlib import Path
from typing import List, Optional

from automations.icd_alerts import config as C

# Chrome slows timers and rendering in a window it thinks nobody can see.
# These keep a hidden window running as if it were in front.
FLAGS = [
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-background-timer-throttling",
]

# Whose computer signs in to OwnerVille in a hidden window. Megan 2026-11-13:
# "yes build it with raf first".
TRIAL_OFFICES = ("raf",)
STAGE = "probe-ov-quiet"
_FAILED_NOTE = "quiet-window-failed.txt"


def _note_path() -> Path:
    return C.STATE_PATH.parent / _FAILED_NOTE


def failed_before() -> bool:
    try:
        return _note_path().is_file()
    except OSError:
        return False


def note_failed(why: str = "") -> None:
    """A hidden sign-in did not get in: this computer goes back to the window
    in view. Never raises."""
    try:
        C.app_dir()
        _note_path().write_text("%s  %s\n" % (
            dt.datetime.now().isoformat(timespec="seconds"), str(why)[:300]))
    except Exception:  # noqa: BLE001
        pass


def on_trial() -> bool:
    try:
        keys = {str(r.get("office_key") or "").strip().lower()
                for r in C.enrollments()}
    except Exception:  # noqa: BLE001
        return False
    return bool(keys & set(TRIAL_OFFICES))


def use_quiet() -> bool:
    """Should this computer's next real window be a hidden one?"""
    return (platform.system() == "Darwin" and on_trial()
            and not failed_before())


def _pids(profile_dir) -> List[int]:
    try:
        out = subprocess.run(["pgrep", "-f", "user-data-dir=%s" % profile_dir],
                             capture_output=True, text=True).stdout
        return [int(x) for x in out.split()]
    except Exception:  # noqa: BLE001
        return []


class Guard:
    """Hide the browser on `profile_dir` every time it comes to the front, and
    put back what the owner was using. Held from start() until stop().

    Does nothing off a Mac, and nothing at all if the pieces it borrows from
    resume_push cannot be loaded -- a window in view is the old behaviour,
    not a failure.
    """
    FAST_SECONDS = 20.0      # a launching browser comes forward more than once
    FAST_POLL = 0.1
    HELD_POLL = 0.25         # each poll runs lsappinfo twice; keep it light

    def __init__(self, profile_dir):
        self.profile_dir = str(profile_dir)
        self.hidden = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._started = 0.0

    def start(self) -> "Guard":
        if platform.system() != "Darwin":
            return self
        try:
            from automations.icd_alerts import resume_push as RP
            self._front, self._hide, self._activate = (
                RP._front_pid, RP._hide_app, RP._activate_app)
        except Exception:  # noqa: BLE001
            return self
        self._started = time.time()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        theirs = 0
        while not self._stop.is_set():
            try:
                pid = self._front()
                if pid and pid in _pids(self.profile_dir):
                    # Hide first, then hand back -- the order resume_push
                    # measured as the shortest time in front (2026-10-05).
                    self._hide(pid)
                    if theirs:
                        self._activate(theirs)
                    self.hidden += 1
                elif pid:
                    theirs = pid
            except Exception:  # noqa: BLE001 -- never cost the sign-in
                pass
            fast = time.time() - self._started < self.FAST_SECONDS
            self._stop.wait(self.FAST_POLL if fast else self.HELD_POLL)


def report(worked: bool, hidden: int, why: str = "", release: str = "") -> None:
    """File how the hidden sign-in went. Best effort; never raises."""
    try:
        from automations.icd_alerts import relay as R
        if worked:
            summary = ("OwnerVille signed in again in the background: worked "
                       "(window hidden %d time(s)) (release %s)" % (hidden, release))
        else:
            summary = ("OwnerVille signed in again in the background: DID NOT "
                       "get in -- this computer goes back to the window in "
                       "view (release %s)" % release)
        R.report_fault(STAGE, summary, detail=str(why)[:1200])
    except Exception:  # noqa: BLE001
        pass
