"""How often an office's laptop sweeps -- and keeping its SCHEDULER saying so.

Megan 2026-09-14, on a hype line that landed three minutes after the rep had
already posted her own sale: "we can make it tighter."

THE CONSTANT IS THE EASY HALF. The hard half is that `dist/setup.py` writes the
LaunchAgent / scheduled task ONCE, at install time, and self-update replaces
code files only -- so lowering the number in setup.py would tighten new
installs and leave every office already running on the old cadence. Which is
the same shape as the bug self-update was written to kill: a fix that exists
and is running nowhere.

SO THIS RUNS AFTER A SUCCESSFUL SELF-UPDATE, once a day, and never on an
ordinary sweep. Rewriting a scheduler entry is the one thing on these machines
that can stop the agent rather than break it, so:

  * macOS rewrites ONLY the StartInterval integer, in place. The python path,
    the working directory and the log path were computed on the office's own
    disk at install time and this has no business guessing any of them.
  * Windows uses `schtasks /Create /F`, which OVERWRITES. setup.py deletes
    first and then creates; that leaves a window in which a failed create has
    removed the office's only trigger, on a machine nobody can reach.
  * It checks first and does nothing when the schedule already matches, so the
    usual day costs one file read.
  * It NEVER raises. A sweep must not be lost to a scheduler edit.

Python 3.9 on some offices' machines -- no runtime `X | Y`.
"""
from __future__ import annotations

import platform
import re
import subprocess
from pathlib import Path
from typing import Optional

# TWO, down from three (2026-09-14). The floor is the sweep itself: three
# SaraPlus report passes, ~30-60s against a warm profile. At one minute a slow
# sweep would still be running when the next tick fired, and these laptops are
# somebody's working machine, not ours -- a browser running back-to-back all
# day is a cost an office feels. Two leaves the duty cycle under half and takes
# the typical end-to-end lag to about a minute and a half with the poster's
# sixty-second tick behind it.
EVERY_MINUTES = 2

PLIST_LABEL = "com.alphalete.lucy-reports"   # setup.py's, and it must not move
TASK_NAME = "LucyReports"
BASE = Path.home() / ".lucy-reports"
_INTERVAL_RE = re.compile(
    r"(<key>StartInterval</key>\s*<integer>)(\d+)(</integer>)")


def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / ("%s.plist" % PLIST_LABEL)


def _q(path: str) -> str:
    """Quote a path for the reload shell. The app lives under a home folder
    whose name we do not choose."""
    import shlex
    return shlex.quote(path)


def _ensure_mac(log) -> bool:
    plist = _plist_path()
    if not plist.is_file():
        # Not an error worth reporting: a Windows office, or one whose install
        # predates the LaunchAgent. Either way there is nothing here to edit.
        return False
    text = plist.read_text()
    m = _INTERVAL_RE.search(text)
    if not m:
        log("cadence: no StartInterval in the LaunchAgent; leaving it alone")
        return False
    want = EVERY_MINUTES * 60
    if int(m.group(2)) == want:
        return False
    plist.write_text(text[:m.start(2)] + str(want) + text[m.end(2):])

    # THIS CODE IS RUNNING *AS* THE JOB IT IS ABOUT TO UNLOAD.
    #
    # `launchctl unload` terminates the job's running processes -- which is
    # this one. So the unload killed the sweep mid-flight and the load on the
    # next line NEVER RAN, leaving the agent unloaded with no error anywhere:
    # no traceback, no fault, nothing in the log after "self-update: updated
    # N file(s)". A desktop that simply stopped.
    #
    # It needed three things to line up, and on 2026-09-14 they did: an office
    # on an older cadence, a self-update that brought EVERY_MINUTES 3 -> 2,
    # and this running inside the job. Kash's iMac went silent at 21:31 that
    # evening and was still silent at noon two days later; Cyrus the same.
    #
    # SO THE RELOAD IS HANDED TO A PROCESS LAUNCHD IS NOT ABOUT TO KILL.
    # start_new_session detaches it from this job's session, and the sleep
    # lets this sweep finish and exit first. Both launchctl calls are in ONE
    # shell command so there is no window where a second process has to
    # survive between the unload and the load.
    #
    # AND IF THE HELPER NEVER RUNS, NOTHING IS BROKEN: the plist on disk is
    # already correct, so the new cadence takes effect at the next load --
    # login or boot -- and the machine keeps sweeping on the old one until
    # then. The failure mode is "slower than intended", not "stopped".
    try:
        subprocess.Popen(
            ["/bin/sh", "-c",
             "sleep 20; launchctl unload %s; launchctl load %s"
             % (_q(str(plist)), _q(str(plist)))],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
    except Exception as e:  # noqa: BLE001 — the plist is already right
        log("cadence: rewrote the schedule but could not reload it (%s); it "
            "takes effect next time this Mac starts" % type(e).__name__)
        return True
    log("cadence: sweep every %d min (was %s min)"
        % (EVERY_MINUTES, int(m.group(2)) // 60))
    return True


def _current_windows_minutes() -> Optional[int]:
    """The task's repetition interval, or None if it cannot be read.

    Unreadable means DO NOTHING. Re-creating a task we could not inspect would
    mean rewriting a working trigger on a guess.
    """
    try:
        out = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME, "/XML"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except Exception:  # noqa: BLE001
        return None
    if out.returncode != 0:
        return None
    xml = out.stdout.decode("utf-8", "replace")
    m = re.search(r"<Interval>PT(\d+)M</Interval>", xml)
    return int(m.group(1)) if m else None


def _ensure_windows(log) -> bool:
    bat = BASE / "run-agent.bat"
    if not bat.is_file():
        return False
    was = _current_windows_minutes()
    if was is None or was == EVERY_MINUTES:
        return False
    # /F OVERWRITES. No Delete first: a delete that succeeds and a create that
    # fails leaves an unreachable machine with no trigger at all.
    rc = subprocess.run(
        ["schtasks", "/Create", "/TN", TASK_NAME, "/TR", '"%s"' % bat,
         "/SC", "MINUTE", "/MO", str(EVERY_MINUTES), "/F"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    if rc != 0:
        log("cadence: could not retime the scheduled task (exit %d); it is "
            "still running every %d min" % (rc, was))
        return False
    log("cadence: sweep every %d min (was %d min)" % (EVERY_MINUTES, was))
    return True


def ensure(log=print) -> bool:
    """Make the machine's schedule match EVERY_MINUTES. True if it changed."""
    try:
        if platform.system() == "Windows":
            return _ensure_windows(log)
        return _ensure_mac(log)
    except Exception as e:  # noqa: BLE001 — never cost a sweep
        log("cadence: skipped (%s)" % type(e).__name__)
        return False
