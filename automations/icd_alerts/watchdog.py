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
import platform
import signal
import time
from typing import Callable, Optional

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
