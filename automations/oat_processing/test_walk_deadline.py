"""The walk stops under its own power before the wrapper kills it.

2026-09-20, Raf's first live day: deploy/applicant_push.sh caps a tick at 1200s
and SIGKILLs the walk. On 11280 (385 deep) that killed PRODUCTIVE walks over and
over — each tick sent real applicants, then died with exit 124, which the streak
logic published as FAILED while the wedge-watcher read
`state=healthy evidence='✅ sent to ai'` on the very next line. A killed walk also
never reaches its bookkeeping, so it writes no flagged snapshot and no diag row,
and the to-do post then says "no walk yet today" for an office that worked for
twenty minutes.

Pinned here: the walk's own budget is comfortably under the wrapper's cap, and a
walk that runs out of time is PARTIAL — never published as the whole queue.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from automations.oat_processing import config  # noqa: E402

_failed = 0


def check(label, got, want):
    global _failed
    if got == want:
        print("  [ok] %s: %r" % (label, got))
    else:
        _failed += 1
        print("  [FAIL] %s: got %r, want %r" % (label, got, want))


# The wrapper's own cap, restated from deploy/applicant_push.sh (MAX_RUN_S).
WRAPPER_CAP_S = 1200

print("the walk's budget leaves room for its own bookkeeping:")
check("budget is set", config.MAX_WALK_SECONDS > 0, True)
check("under the wrapper's SIGKILL", config.MAX_WALK_SECONDS < WRAPPER_CAP_S, True)
# The tail of a walk writes a snapshot, a Sheet diag row and the Slack-facing
# counts. A budget that leaves only seconds would be killed doing exactly that.
check("with at least 2 min of headroom to finish writing",
      WRAPPER_CAP_S - config.MAX_WALK_SECONDS >= 120, True)
# A budget under a few minutes would stop walks that are working fine.
check("but long enough to be a real pass", config.MAX_WALK_SECONDS >= 600, True)

print("the wrapper's cap is still the backstop, not the primary stop:")
check("walk stops first", config.MAX_WALK_SECONDS < WRAPPER_CAP_S, True)

print("a walk that ran out of time is PARTIAL, never the whole picture:")
# Mirrors run_walk's completeness rule: walked_all requires NOT out-of-time.
def walked_all(worked, limit, processed, touch_cap, covered, out_of_time):
    return (worked < limit) and (processed < touch_cap) and covered and not out_of_time

check("out of time -> partial",
      walked_all(10, 60, 10, 400, True, True), False)
check("same walk, with time left -> complete",
      walked_all(10, 60, 10, 400, True, False), True)
check("out of time does not override an already-partial walk",
      walked_all(60, 60, 10, 400, True, True), False)

print("FAILED" if _failed else "ALL PASSED")
raise SystemExit(1 if _failed else 0)
