"""Time every sweep, and never let one run forever.

Megan, 2026-09-18: "I want the ICDs to enroll and then be 100% hands off."

WHAT THIS IS FOR. Roshan's brand-new iMac went quiet twice in one day -- 50
minutes in the morning, 20 in the evening -- while every other office checked
in every two minutes. It reports never_sleeps, it is on power, and it raised
NO faults either time. Wifi was the first guess and it was wrong: a machine
that cannot reach us also cannot report, but a machine that is still WORKING
looks identical from here, and nothing anywhere recorded how long a run took.

THE JOB FIRES EVERY TWO MINUTES and launchd will not start a second copy while
one is still going. So a sweep that takes twenty minutes produces exactly what
we saw: a twenty-minute hole, no errors, then everything arriving at once --
which is what an office experiences as "she's super delay today".

TWO THINGS, and the second is the one that makes it hands-off:

  * a run that takes longer than SLOW_SECONDS reports itself, so a slow office
    is a number we can read rather than a gap somebody notices hours later
  * a run that passes DEADLINE_SECONDS is ABANDONED, so the next tick starts
    clean instead of queueing behind a hang nobody can see

GIVING UP IS THE POINT. A sweep that cannot finish has already lost the
office its alerts; holding the slot as well costs it every tick behind it.
The numbers are cumulative, so nothing is lost by stopping -- the next run
reads the same totals.

SIGALRM, where there is one. It raises inside the main thread, so contexts
close and the browser goes with them. On Windows there is none, and the
timing still reports -- the deadline is simply not enforced there. No ICD
machine is a PC today; every one reports Darwin.
"""
from __future__ import annotations

import datetime as dt
import os
import platform
import signal
import subprocess
import threading
import time
from typing import Callable, List, Optional

# Longer than any healthy sweep and shorter than anybody's patience. A clean
# Box read is seconds; the slowest AT&T office is well under a minute.
SLOW_SECONDS = 180

# When to stop trying. Two and a half ticks: long enough that a genuinely slow
# office is not cut off mid-read, short enough that a hang costs one gap
# rather than an afternoon.
DEADLINE_SECONDS = 300


class SweepTimeout(RuntimeError):
    """This run was abandoned, so the next one can start clean."""


class _Deadline:
    """Raise SweepTimeout if the body outlives `seconds`."""

    def __init__(self, seconds: int = DEADLINE_SECONDS, log=print):
        self.seconds, self.log, self._armed = seconds, log, False

    def __enter__(self):
        if platform.system() == "Windows" or not hasattr(signal, "SIGALRM"):
            return self
        try:
            signal.signal(signal.SIGALRM, self._fire)
            signal.alarm(self.seconds)
            self._armed = True
        except (ValueError, OSError):
            # Not the main thread, or no alarm to be had. The timing still
            # reports; only the cut-off is missing.
            self._armed = False
        return self

    def _fire(self, *_a):
        raise SweepTimeout(
            "this run passed %d seconds and was abandoned so the next tick "
            "could start clean. Nothing is lost -- these numbers are a "
            "running total and the next run reads the same ones."
            % self.seconds)

    def __exit__(self, *_exc):
        if self._armed:
            try:
                signal.alarm(0)
            except (ValueError, OSError):
                pass
        return False


def timed(stage: str, fn: Callable, *, log=print, report=None,
          office_key: str = "", seconds: int = DEADLINE_SECONDS):
    """Run `fn`, bounded and timed. Returns whatever it returns.

    `report` is run.py's _report, passed in rather than imported so this stays
    testable without a relay.
    """
    started = time.time()
    try:
        with _Deadline(seconds, log=log):
            return fn()
    except SweepTimeout as e:
        took = time.time() - started
        log("%s ABANDONED after %.0fs" % (stage, took))
        if report:
            try:
                report("%s-timeout" % stage, e, office_key=office_key)
            except Exception:  # noqa: BLE001 — reporting must not re-raise
                pass
        raise
    finally:
        took = time.time() - started
        log("%s took %.1fs" % (stage, took))
        if report and took >= SLOW_SECONDS:
            try:
                # WHERE IT WENT, when the stage can say. "this read took 208
                # seconds" named the office and nothing else, so the 2026-09-24
                # diagnosis had to infer the retried pass from arithmetic --
                # these laptops cannot be reached to read their own logs. The
                # breakdown rides the fault into the 'ICD Faults' tab instead.
                detail = ""
                try:
                    from automations.shared import saraplus as _S
                    detail = _S.pass_timings_summary()
                except Exception:  # noqa: BLE001 — a missing breakdown must
                    detail = ""    # not cost the fault itself
                report("%s-slow" % stage,
                       RuntimeError(
                           "this read took %.0f seconds. Healthy is a few. "
                           "The office sees this as alerts arriving late and "
                           "then all at once, because the job cannot start "
                           "again until it finishes.%s"
                           % (took, ("  Where it went: %s" % detail)
                              if detail else "")),
                       office_key=office_key)
            except Exception:  # noqa: BLE001
                pass


# THE WHOLE RUN, NOT ONE STAGE. Kash's iMac, 2026-10-02 ~09:20: the 2am sales
# catch-up hung on the third SaraPlus attempt and the process never exited.
# launchd will not start a second copy while one is alive, so the office went
# dark for three days -- no check-ins, no knocks, and NO fault, because the
# only thing that could have filed one was the stuck process. The friday fix
# for the very bug that started it never reached him either: self-update runs
# at the top of a sweep, and no sweep ever started again.
#
# Why the stage deadline above did not save it: SIGALRM is one-shot and
# arrives as an ordinary exception, so it can be caught by a retry loop's
# `except Exception` (saraplus._run_report retries ANY failure), and anything
# that blocks after it -- closing a Chrome that stopped answering -- has no
# deadline at all. A timer THREAD does not depend on the main thread
# cooperating: it fires while the main thread sits in a blocked call.
#
# Twenty minutes: three stages at DEADLINE_SECONDS each plus the update check
# and both close-outs. A healthy run is two or three minutes.
HARD_CEILING_SECONDS = 20 * 60


def _descendants(pid: int) -> List[int]:
    """Every process under `pid` -- Chrome and its helpers. Mac/Linux only;
    no ICD machine is a PC."""
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid="],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:  # noqa: BLE001
        return []
    kids: dict = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            kids.setdefault(int(parts[1]), []).append(int(parts[0]))
    found, todo = [], [pid]
    while todo:
        for child in kids.get(todo.pop(), []):
            if child not in found:
                found.append(child)
                todo.append(child)
    return found


def _kill_descendants() -> None:
    if platform.system() == "Windows":
        return
    for pid in _descendants(os.getpid()):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def arm_hard_ceiling(seconds: int = HARD_CEILING_SECONDS, *, log=print,
                     report=None, _exit=os._exit) -> threading.Timer:
    """End THIS PROCESS if it is still alive after `seconds`, whatever it is
    doing. Arm once, at the top of a scheduled run; it dies with the process.

    Reports first (bounded -- a relay that hangs too must not keep us alive),
    then kills the browsers this run started, then exits. The next tick starts
    clean and picks up any pending update on its way in.
    """
    def _fire():
        msg = ("this whole run was still going after %d minutes, so it was "
               "ended to let the next one start. Nothing is lost -- the "
               "numbers are a running total." % (seconds // 60))
        try:
            log("HARD STOP: %s" % msg)
        except Exception:  # noqa: BLE001
            pass
        if report:
            t = threading.Thread(
                target=lambda: report("run-timeout", SweepTimeout(msg)),
                daemon=True)
            t.start()
            t.join(30)
        _kill_descendants()
        _exit(3)

    timer = threading.Timer(seconds, _fire)
    timer.daemon = True
    timer.start()
    return timer
