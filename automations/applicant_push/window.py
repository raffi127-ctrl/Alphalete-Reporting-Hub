"""When the push is allowed to run — and what a refusal costs.

Its own module, with NO imports beyond the stdlib, for two reasons: the test can
pin every edge of the window without importing run.py (which pulls patchright
and a warm-Chrome stack), and nothing in the test can ever reach a live push.
"""
from __future__ import annotations

# Exit code for "declined on purpose, nothing ran, nothing is broken" — 75,
# EX_TEMPFAIL, which is already this repo's word for HELD (sales_boards,
# rep_sales_fill, vantura_*, and post_watch's "exit 75 = held, a no-post is
# legit"). The wrapper (deploy/applicant_push.sh) treats it as a healthy skip;
# any OTHER non-zero is still a bad pass that counts toward the failure streak.
#
# NOT 3, which this first shipped as: rc=3 is already spoken for in this exact
# family — resume_pushing exits 3 for an Indeed/Turnstile extractor wedge
# ("exiting rc=3 so the next pass self-heals and the fail-streak notifier can
# fire"), and oat_processing returns 3 for an AppStream-busy session. Today
# applicant_push.run() swallows both (it always returns 0), so nothing collided
# yet — but a wrapper that reads 3 as "healthy skip" is a loaded gun pointed at
# the day someone propagates a stage's rc, and it would mute exactly the wedge
# alert Lucy 2 depends on.
QUIET_EXIT = 75


def quiet_window(now) -> bool:
    """Is `now` inside the weekend quiet window? Fri 1:00 PM -> Sun 1:00 PM,
    machine-local (Lucy 2 runs Central). Carlos, 2026-09-04 — supersedes the
    plain Saturday block of 2026-08-31."""
    wd, hr = now.weekday(), now.hour
    return (wd == 4 and hr >= 13) or wd == 5 or (wd == 6 and hr < 13)
