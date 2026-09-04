"""Fri 1pm -> Sun 1pm is quiet for live pushes, and a quiet tick is a SKIP.

The window itself is only half the contract. On 2026-09-04 the refusal exited 1,
the wrapper counted three quiet ticks as a failure streak and published FAILED
for BOTH offices — so the exit code and the wrapper's handling of it are pinned
here too. Nothing in this file starts a push: window.py imports nothing but the stdlib.
"""
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from automations.applicant_push.window import QUIET_EXIT, quiet_window  # noqa: E402


def at(wd, hr):
    # 2026-09-07 is a Monday; add wd days to land on the weekday we want.
    return dt.datetime(2026, 9, 7 + wd, hr, 30)


assert not quiet_window(at(4, 12))   # Friday morning: on
assert quiet_window(at(4, 13))       # Friday 1pm: off
assert quiet_window(at(5, 9))        # Saturday: off
assert quiet_window(at(6, 12))       # Sunday morning: off
assert not quiet_window(at(6, 13))   # Sunday 1pm: back on
assert not quiet_window(at(0, 9))    # Monday: on

# A declined tick is the repo's HELD code (EX_TEMPFAIL), not the generic failure
# exit — and NOT 3, which resume_pushing uses for an Indeed wedge that has to keep
# counting toward the failure streak.
assert QUIET_EXIT == 75 and QUIET_EXIT not in (0, 1, 2, 3)

# The wrapper has to know that code, or the quiet window pages the channel again.
wrapper = (pathlib.Path(__file__).resolve().parents[2]
           / "deploy" / "applicant_push.sh").read_text(encoding="utf-8")
assert '[ "$ST" -eq 75 ]' in wrapper, "wrapper no longer special-cases exit 75"
assert 'elif [ "$ST" -ne 0 ]' in wrapper, "exit 75 must be checked before the fail streak"

print("ok: quiet window Fri13->Sun13, declines with exit 75 (held), wrapper skips it")
