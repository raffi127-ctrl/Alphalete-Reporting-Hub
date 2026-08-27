"""When may a walk publish its flagged list as the CURRENT picture?

THE BUG THIS PINS (2026-08-27): completeness was `processed < limit`, which only
rules out hitting the per-run cap. Every other early exit — the pager control
going missing, the no-progress guard, an error mid-queue — also satisfies it, so
those walks called themselves complete and overwrote the snapshot with just the
applicants they reached. Real walks that day: 21-in-queue/11-touched, 22/15,
23/15, and Carlos at 13/2 and 13/3. Megan caught it from the outside — "you have
follow up need for 6 on atef but his inbox is 23, that doesn't line up" — and the
consequence was that the twice-daily to-do post UNDERSTATED the backlog while the
people deeper in the queue were invisible rather than handled.

Run:  PYTHONPATH=. .venv/bin/python -m automations.oat_processing.test_walk_coverage
"""
from __future__ import annotations  # Lucy 2 runs Python 3.9

_passed = 0
_failed = 0


def check(label, got, want):
    global _passed, _failed
    if got == want:
        _passed += 1
        print("  [ok] %s: %r" % (label, got))
    else:
        _failed += 1
        print("  [FAIL] %s: got %r, want %r" % (label, got, want))


def walked_all(processed, limit, start_total):
    """The decision as run.py makes it."""
    covered = start_total is None or processed >= start_total
    return (processed < limit) and covered


LIMIT = 60

print("the real partial walks from 8/27 must NOT publish:")
for start, touched, who in ((21, 11, "Atef 15:45"), (22, 15, "Atef 16:40"),
                            (23, 15, "Atef 17:10"), (13, 2, "Carlos 16:31"),
                            (13, 3, "Carlos 16:46")):
    check("%s (%d of %d) is partial" % (who, touched, start),
          walked_all(touched, LIMIT, start), False)

print("a walk that really covered the queue still publishes:")
check("23 of 23", walked_all(23, LIMIT, 23), True)
check("touched more than the start (queue shrank as we sent)",
      walked_all(24, LIMIT, 22), True)
check("empty queue", walked_all(0, LIMIT, 0), True)

print("hitting the per-run cap is still partial (unchanged):")
check("capped at the limit", walked_all(LIMIT, LIMIT, LIMIT), False)
check("capped, queue bigger than the cap", walked_all(60, 60, 200), False)

print("no start count from the ATS — keep the old behaviour, don't freeze:")
# The ATS returns None for this often. Freezing the snapshot all day would trade
# an understated list for a stale one, which is no better.
check("unknown start, under the cap -> publishes", walked_all(15, LIMIT, None), True)
check("unknown start, at the cap -> still partial",
      walked_all(LIMIT, LIMIT, None), False)

print("the OLD rule wrongly called every one of those partials complete:")


def old_rule(processed, limit, _start):
    return processed < limit


for start, touched in ((21, 11), (13, 2), (23, 15)):
    check("old rule said %d-of-%d was complete" % (touched, start),
          old_rule(touched, LIMIT, start), True)
    check("new rule does not", walked_all(touched, LIMIT, start), False)

print("%d/%d passed" % (_passed, _passed + _failed))
raise SystemExit(1 if _failed else 0)
