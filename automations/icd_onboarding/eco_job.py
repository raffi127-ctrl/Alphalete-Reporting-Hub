"""Run this office's onboarding board on the office's OWN computer, on a clock.

Megan, 2026-11-24: *"we need to build an installer now like we have for Lucy
Eco to run on the ICDs machine to fully launch all of these steps on an eco
machine."* This is the CLOCK half of that; `icd_alerts.onboarding_setup` is the
installer half.

WHY A TICK AND NOT A LAUNCHAGENT. On the Lucys the board is
`com.alphalete.icd-onboarding`, an hourly LaunchAgent (deploy/icd_onboarding.sh).
An office machine has no such thing and must not grow one: everything on an ECO
box hangs off the ONE agent it already has (`com.alphalete.lucy-reports`), which
ticks every couple of minutes and calls each feature's `maybe_run`. A second
LaunchAgent is a second thing to install, a second thing to notice has stopped,
and a second thing that needs the Mac's password to put there.

IT RUNS IN ITS OWN PROCESS AND THE TICK DOES NOT WAIT. A board pass walks
ApplicantStream and OwnerVille and takes minutes; the next tick's credit-check
read waits for nobody (`icd_alerts.run.knocks_in_background`, and Colten's
"Lucy is lagging" on 2026-11-06, which was exactly this). So a due pass is
started detached and `maybe_run` returns at once.

NOTHING IS VISIBLE. The pass is a scheduled read on somebody's office computer,
so it opens no window and brings nothing forward
([[feedback_eco_runs_in_background]]). It is not in
`icd_alerts.visible_windows` and must never be: the only windows on an ECO box
are the ones a PERSON has to act in, which here means the installer's sign-ins,
not this.

OFF UNTIL SOMEBODY SWITCHES IT ON. `switch_on()` writes the marker and nothing
runs without it ([[feedback_onboarding_nothing_live_till_built]]). An installed
machine with the marker absent is CORRECT, not broken: the whole onboarding
chain stays off until Megan says the build is done, and the installer says so
in its summary rather than quietly arming forty computers.

    python -m automations.icd_onboarding.eco_job --status
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Optional

# HOW OFTEN IS `cadence`, NOT A NUMBER HERE. Megan, 2026-11-24: 15 minutes from
# 8 to noon, 30 from noon to 3, hourly the rest of the day. One definition, so
# an office's own machine and the Lucys cannot end up on two clocks
# (icd_onboarding.cadence says why the day is banded).
#
# ALL DAY NOW, not 6:30am to 8:30pm. The old window existed because every pass
# cost the same; banded, an overnight pass is one hourly read, and the first
# fast pass of the morning is ready at 8 instead of waiting for the half hour.

# The no-shows walk keeps its own daily slot, for the reason its schedule entry
# gives: it is the SEVEN-page calendar walk, the answer only changes when a
# recruiter marks a radio, and 21:15 is after the office closes and before the
# next morning's Blue Ink send at 7:30. :15 and not :30, because :30 is the
# board run's own minute and the two drive the same ApplicantStream profile.
NO_SHOWS_HOUR = 21
NO_SHOWS_MINUTE = 15

# A pass that has been going this long is a crash's leftover, not a run. The
# Lucys' wrapper bounds the same thing with `pgrep`; a lock with a time in it
# also survives a kill -9, which pgrep cannot tell from "never started".
STALE_LOCK_MINUTES = 90


def _app_dir() -> Path:
    from automations.icd_alerts import config as C
    return C.APP_DIR


def state_path() -> Path:
    return _app_dir() / "onboarding-board.json"


def on_path() -> Path:
    """The switch. Absent = this machine does not run the board yet."""
    return _app_dir() / "onboarding-board.on"


def log_path() -> Path:
    return _app_dir() / "onboarding-board.log"


def lock_path() -> Path:
    return _app_dir() / "onboarding-board.lock"


def switched_on() -> bool:
    try:
        return on_path().exists()
    except Exception:       # noqa: BLE001 -- unreadable is not on
        return False


def switch_on(why: str = "") -> None:
    """Arm the board on this machine. Deliberately a separate call from the
    installer's setup, so getting a machine READY and turning it ON are two
    decisions and not one."""
    p = on_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("%s %s\n" % (dt.datetime.now().isoformat(timespec="seconds"),
                              why), encoding="utf-8")


def switch_off() -> None:
    try:
        on_path().unlink()
    except OSError:
        pass


def _load() -> Dict:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except Exception:       # noqa: BLE001
        return {}


def _save(s: Dict) -> None:
    try:
        p = state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(s), encoding="utf-8")
    except Exception:       # noqa: BLE001 -- only costs an extra pass
        pass


def _lock_held(now: Optional[float] = None) -> bool:
    """Is a pass running? A lock older than STALE_LOCK_MINUTES is not."""
    now = time.time() if now is None else now
    try:
        started = float(lock_path().read_text(encoding="utf-8").strip())
    except Exception:       # noqa: BLE001 -- no lock, or an unreadable one
        return False
    return (now - started) < STALE_LOCK_MINUTES * 60


def _take_lock() -> None:
    p = lock_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("%.0f" % time.time(), encoding="utf-8")


def offices() -> list:
    """The offices this machine works.

    ASKED OF `eco_steps`, which SHIPS, not of `icd_onboarding.run`, which
    cannot: that module is the Hub's runner and reaches OwnerVille and gspread
    through its siblings. Both answer off the same enrolment through
    `config.base_office_key`, so there is one answer to whose board this is.
    """
    try:
        from automations.icd_onboarding import eco_steps as ES
        return list(ES.offices())
    except Exception:       # noqa: BLE001 -- not an enrolled machine
        return []


def steps_here() -> list:
    """The step names this machine can do for itself, newest first in the list
    they are added to. Empty means there is nothing to run, which is the
    correct answer on a box whose copy is older than the step."""
    try:
        from automations.icd_onboarding import eco_steps as ES
        return [n for n, _ in ES.STEPS]
    except Exception:       # noqa: BLE001
        return []


def board_due(now: Optional[dt.datetime] = None,
              state: Optional[Dict] = None) -> bool:
    """Is a board pass due, on this hour's band (`cadence`)?"""
    from automations.icd_onboarding import cadence as CAD
    now = now or dt.datetime.now()
    last = float((state if state is not None else _load()).get("board", 0) or 0)
    when = dt.datetime.fromtimestamp(last) if last else None
    return CAD.due(when, now)


def no_shows_due(now: Optional[dt.datetime] = None,
                 state: Optional[Dict] = None) -> bool:
    """Once on a given day, at or after its slot.

    AT OR AFTER, not 'in that minute'. A tick is every couple of minutes, a
    machine can be asleep at 21:15, and a walk that only fires inside one
    minute is the shape that shipped at 19:30 and never ran once.
    """
    now = now or dt.datetime.now()
    if (now.hour, now.minute) < (NO_SHOWS_HOUR, NO_SHOWS_MINUTE):
        return False
    said = str((state if state is not None else _load()).get("no_shows_day", ""))
    return said != now.date().isoformat()


def _start(args: list, log) -> bool:
    """Run the board module detached, with nothing on screen."""
    root = Path(__file__).resolve().parents[2]
    kw: Dict = {"cwd": str(root), "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        # Out of sight AND out of the console: an office owner should not see a
        # window appear, and launchd/Task Scheduler must not kill what is left
        # in the tick's group when the tick exits.
        kw["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0x8)
                               | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP",
                                         0x200)
                               | getattr(subprocess, "CREATE_NO_WINDOW", 0x8000000))
    else:
        kw["start_new_session"] = True
    try:
        p = log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        out = open(p, "a", encoding="utf-8")
        out.write("\n[%s] %s\n" % (dt.datetime.now().isoformat(timespec="seconds"),
                                   " ".join(args)))
        out.flush()
        # `eco_steps`, not `icd_onboarding.run`: the second is the Hub's
        # runner and its steps reach Google Sheets and the Hub's OwnerVille
        # session. This machine runs the steps that reach their source the
        # ECO way, with its own logins, and writes through the relay.
        subprocess.Popen([sys.executable, "-u", "-m",
                          "automations.icd_onboarding.eco_steps"] + args,
                         stdout=out, stderr=subprocess.STDOUT, **kw)
    except Exception as e:  # noqa: BLE001 -- never lose a tick to this
        log("onboarding board could not start: %s" % type(e).__name__)
        return False
    return True


def maybe_run(log=print, now: Optional[dt.datetime] = None) -> bool:
    """Called from every agent tick. Cheap when nothing is due.

    Returns True when a pass was STARTED, not when one finished -- it is
    detached on purpose and its answer lands in the board, not here.

    `now` is for the tests, and it is a PARAMETER rather than a patched clock
    because the two slots here are the whole behaviour: which of them wins
    when both are due cannot be checked at all if the answer depends on what
    time it happens to be when the suite runs.
    """
    if os.environ.get("LUCY_NO_ONBOARDING_BOARD"):
        return False
    if not switched_on():
        return False
    if not offices():
        # Enrolled for nothing: not an error, and not worth a line every tick.
        return False
    now = now or dt.datetime.now()
    state = _load()
    if _lock_held():
        return False

    # THE NO-SHOWS WALK GOES FIRST when both are due, and only one of the two
    # starts per tick. They drive the SAME ApplicantStream profile, and the
    # walk is the one with a deadline on it: the Blue Ink send at 7:30 the next
    # morning is what must not mail documents to somebody who did not come.
    #
    # ONLY IF THIS MACHINE HAS THAT STEP. The walk is a seven-page
    # ApplicantStream read and its ECO reader is not built yet, so asking for
    # it here would start a pass with nothing to do every night and mark the
    # day done. A step this copy does not have is simply not run.
    can = steps_here()
    if "no_shows" in can and no_shows_due(now, state):
        if not _start(["--only", "no_shows", "--write"], log):
            return False
        state["no_shows_day"] = now.date().isoformat()
        _save(state)
        _take_lock()
        log("onboarding: no-shows walk started in the background")
        return True

    if not can or not board_due(now, state):
        return False
    if not _start(["--write"], log):
        return False
    state["board"] = time.time()
    _save(state)
    _take_lock()
    log("onboarding board started in the background")
    return True


def status() -> str:
    state = _load()
    last = float(state.get("board", 0) or 0)
    return "\n".join([
        "switched on : %s" % ("yes" if switched_on() else "NO (nothing runs)"),
        "offices     : %s" % (", ".join(offices()) or "none on this machine"),
        "last pass   : %s" % (dt.datetime.fromtimestamp(last)
                              .isoformat(timespec="seconds") if last else "never"),
        "no-shows    : %s" % (state.get("no_shows_day") or "never"),
        "a pass now  : %s" % ("yes" if _lock_held() else "no"),
        "log         : %s" % log_path(),
    ])


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--status", action="store_true", help="say where this stands")
    ap.add_argument("--on", action="store_true",
                    help="arm the board on this machine")
    ap.add_argument("--off", action="store_true", help="disarm it")
    a = ap.parse_args(argv)
    if a.on:
        switch_on("by hand")
        print("the onboarding board is ON on this machine.")
    if a.off:
        switch_off()
        print("the onboarding board is OFF on this machine.")
    print(status())
    return 0


if __name__ == "__main__":
    sys.exit(main())
