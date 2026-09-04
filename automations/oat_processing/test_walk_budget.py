"""The per-run cap counts WORK, not page-turns.

THE BUG THIS PINS (2026-09-03). `MAX_PER_RUN` (60) was charged for every
applicant the walk READ, including ones already settled that day — resume
already opened and it carried no number, or no reachable SMS thread. Those cost
a cache hit and a Next click; the handler logs "already checked today … skip
re-read" and returns without opening a resume, a widget, or making a mutation.

Measured in Atef's office (23467) that day: queue 104, seventy-four walks, and
EVERY walk stopped at exactly 60 — of which ~44 were "already checked (no resume
number)" and ~6 "blocked, retrying". So ~50 of the 60 slots went to re-confirming
the same dead ends every ten minutes, and applicants 61-104 were never read once,
all day. Carlos's office (46-49 in queue) fit under the cap, so it looked fine —
which is why this only appeared once a second, bigger office was added.

Run:  PYTHONPATH=. .venv/bin/python -m automations.oat_processing.test_walk_budget
"""
from __future__ import annotations  # Lucy 2 runs Python 3.9

from automations.oat_processing import config, run

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


def walk(queue, settled, limit=60, touch_cap=300):
    """The loop's accounting, run over a queue of `queue` applicants of which the
    first `settled` are settled skips. Returns (read, worked)."""
    read = worked = 0
    while worked < limit and read < touch_cap and read < queue:
        was_settled = read < settled
        read += 1
        if not was_settled:
            worked += 1
    return read, worked


def old_walk(queue, settled, limit=60):
    """What it did before: every read spent a slot."""
    read = 0
    while read < limit and read < queue:
        read += 1
    return read, read


print("Atef 23467 on 2026-09-03 — queue 104, ~50 settled at the front:")
check("OLD: read only 60 of 104", old_walk(104, 50)[0], 60)
check("NEW: reads all 104", walk(104, 50)[0], 104)
check("NEW: spends 54 real slots, not 104", walk(104, 50)[1], 54)
check("NEW: under the cap, so the walk is not truncated", walk(104, 50)[1] < 60, True)

print("Carlos 11580 the same day — queue 47, ~23 settled — unchanged either way:")
check("OLD read all 47", old_walk(47, 23)[0], 47)
check("NEW reads all 47", walk(47, 23)[0], 47)

print("the cap still bites when the work is real:")
check("100 applicants, none settled -> stops at the cap", walk(100, 0), (60, 60))
check("a settled front does not let unlimited work through",
      walk(400, 100)[1], 60)

print("the touch backstop bounds free paging:")
check("everything settled, huge queue -> stops at the touch cap",
      walk(5000, 5000, touch_cap=300), (300, 0))
check("touch cap never sits below the per-run cap",
      max(90, getattr(config, "MAX_TOUCH_PER_RUN", 300)) >= 90, True)

print("--limit still means what the caller asked (a controlled test):")
check("--limit 1 with a settled front works exactly one person",
      walk(104, 50, limit=1)[1], 1)

print("the two settled paths are the single source of truth for 'settled':")
# Both must bump the counter run_walk reads, or their applicants silently go back
# to costing a slot and the reach regression returns unnoticed.
src = open(run.__file__.replace(".pyc", ".py"), encoding="utf-8").read()
check("no-number cache bumps _SETTLED_SKIPS",
      "_SETTLED_SKIPS += 1" in src.split("already checked today")[0][-400:], True)
check("no-thread cache bumps _SETTLED_SKIPS",
      "_SETTLED_SKIPS += 1" in src.split("no reachable thread (settled earlier")[0][-400:],
      True)
check("the cap is charged to `worked`, never to reads",
      "while worked < limit and processed < touch_cap:" in src, True)

print("%d/%d passed" % (_passed, _passed + _failed))
raise SystemExit(1 if _failed else 0)
