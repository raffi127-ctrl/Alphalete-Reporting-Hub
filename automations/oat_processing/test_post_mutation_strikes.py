"""A send re-renders the list; the blank reads that follow are not an empty queue.

THE BUG THIS PINS (2026-09-04). Once the walks finally covered whole queues, the
small-queue case exposed the end-of-queue guard. Seven walks in Carlos's office
(11580) logged "no fresh applicants (4 blank/seen reads) — end of queue after 1
processed" against a queue of EIGHT: the walk sent one person, the ATS re-rendered
its list, the current-applicant read came back blank/already-seen, and three
strikes was not enough room for that. Eleven of the day's twenty-nine walks did
1-4 people instead of 8. The pager was never the problem — zero "no next control"
lines all day, so this is the READ side, not the paging side.

Not fatal (the next tick ten minutes later picked up the rest, which is why the
queue still drained) but most of a pass was wasted each time.

The budget widens ONLY after a mutation. A genuinely empty queue must still end
quickly, and the allowlist case needs a far bigger budget for its own reason:
Rafael's office fronts a 777-email queue with nameless AD-receipt records.

Run:  PYTHONPATH=. .venv/bin/python -m automations.oat_processing.test_post_mutation_strikes
"""
from __future__ import annotations  # Lucy 2 runs Python 3.9

from automations.oat_processing import config

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


def strikes(only_names, after_mutation):
    """The budget as run.py picks it."""
    if only_names is not None:
        return 40
    if after_mutation:
        return getattr(config, "POST_MUTATION_STRIKES", 8)
    return getattr(config, "END_OF_QUEUE_STRIKES", 3)


def walk(queue, blanks_after_send, budget=strikes):
    """Walk a queue where each send is followed by `blanks_after_send` blank reads
    before the next applicant surfaces. Returns how many got processed.

    `budget` is the strike rule under test, so the OLD behaviour can be replayed
    against the same queue rather than asserted from memory.
    """
    processed = no_progress = 0
    after_mutation = False
    pending_blanks = 0
    while processed < 60:
        if pending_blanks > 0:                       # a blank/seen read
            pending_blanks -= 1
            no_progress += 1
            if no_progress > budget(None, after_mutation):
                break                                # called it end-of-queue
            continue
        if processed >= queue:                       # really out of applicants
            no_progress += 1
            if no_progress > budget(None, after_mutation):
                break
            continue
        no_progress = 0
        after_mutation = False
        processed += 1
        after_mutation = True                        # every one of these is a send
        pending_blanks = blanks_after_send
    return processed


def old_strikes(only_names, _after_mutation):
    """What run.py did before 2026-09-04: a flat 3, mutation or not."""
    return 40 if only_names is not None else 3


print("Carlos's office on 2026-09-04 — queue 8, ~4 blank reads after each send:")
check("OLD flat 3-strike budget stopped after ONE person",
      walk(8, 4, budget=old_strikes), 1)
check("NEW budget walks the whole queue", walk(8, 4), 8)

print("the re-render window we actually measured (4 blanks) fits with room spare:")
check("4 blanks is under the post-mutation budget",
      4 <= strikes(None, True), True)
check("and over the plain budget — which is why it broke",
      4 > strikes(None, False), True)

print("a genuinely empty queue still ends promptly, it does not spin:")
# Nothing left to hand back: the walk must stop, just with the wider budget.
check("empty queue ends", walk(0, 0), 0)
check("queue of 3 ends after 3", walk(3, 2), 3)

print("the budgets stay ordered — plain < post-mutation < allowlist:")
check("plain is the tightest", strikes(None, False) < strikes(None, True), True)
check("allowlist is the widest (Rafael's AD-receipt front)",
      strikes(set(), False) > strikes(None, True), True)
check("plain default unchanged at 3", strikes(None, False), 3)

print("a slower re-render than we have ever seen still recovers:")
check("7 blank reads after a send", walk(8, 7), 8)
check("but a run of blanks past the budget still ends the walk", walk(8, 40) < 8, True)

print("%d/%d passed" % (_passed, _passed + _failed))
raise SystemExit(1 if _failed else 0)
