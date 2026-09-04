"""When the push is allowed to run — and what a refusal costs.

Its own module, with NO imports beyond the stdlib, for two reasons: the test can
pin every edge of the window without importing run.py (which pulls patchright
and a warm-Chrome stack), and nothing in the test can ever reach a live push.
"""
from __future__ import annotations

# Exit code for "declined on purpose, nothing ran, nothing is broken". The
# wrapper (deploy/applicant_push.sh) treats it as a healthy skip; any OTHER
# non-zero is still a bad pass that counts toward the failure streak.
QUIET_EXIT = 3


def quiet_window(now) -> bool:
    """Is `now` inside the weekend quiet window? Fri 1:00 PM -> Sun 1:00 PM,
    machine-local (Lucy 2 runs Central). Carlos, 2026-09-04 — supersedes the
    plain Saturday block of 2026-08-31."""
    wd, hr = now.weekday(), now.hour
    return (wd == 4 and hr >= 13) or wd == 5 or (wd == 6 and hr < 13)
