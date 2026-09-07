"""`_day_already_posted` has to mirror the pass that is asking.

It exists so a board rolled forward AFTER the day posted holds QUIETLY instead
of filing "today's thread was not posted" (2026-08-24). The 2026-08-30
restructure then took BOX out of the 5:10 ladder — the ladder posts B2B only,
BOX rides vantura_revenue_board — but the checker kept demanding a BOX reply,
so a ladder pass could never reach "done" and the false alarm came back on
2026-09-07: B2B was in both rooms since 05:10, and 07:15 still opened an
incident whose fix line would have undone the morning's week roll.

Run:  python -m automations.sales_boards.test_posted_check
"""
from __future__ import annotations

import datetime as dt

import automations.sales_boards.run as R

DAY, YDAY = dt.date(2026, 9, 7), dt.date(2026, 9, 6)


class _Client:
    """Answers only what the checker asks: which needles are in which thread."""

    def __init__(self, replies):
        self.replies = replies


def _patch(monkey, *, posted, box_ts="box-ts", b2b_ts="b2b-ts"):
    """Stand in for Slack + b2b_quality's thread state. `posted` is the set of
    plain needles that made it into a thread."""
    import types

    bq = types.ModuleType("automations.b2b_quality.run")
    bq._load_state = lambda day, cid: {"thread_ts": b2b_ts} if b2b_ts else {}
    pkg = types.ModuleType("automations.b2b_quality")
    pkg.run = bq                       # `import a.b.c as x` reads the ATTRIBUTE
    smp = types.ModuleType("automations.shared.slack_metrics_post")
    smp._client = lambda: _Client(posted)

    monkey["sys"].modules["automations.b2b_quality"] = pkg
    monkey["sys"].modules["automations.b2b_quality.run"] = bq
    monkey["sys"].modules["automations.shared.slack_metrics_post"] = smp
    monkey["run"].box_thread_ts = lambda client, chan, day: box_ts
    monkey["run"]._already_replied = \
        lambda client, cid, ts, plain: plain in posted


def _run(posted, programs, *, corrected=False, box_ts="box-ts", b2b_ts="b2b-ts"):
    import sys

    saved = (R.box_thread_ts, R._already_replied,
             sys.modules.get("automations.b2b_quality.run"),
             sys.modules.get("automations.shared.slack_metrics_post"),
             sys.modules.get("automations.b2b_quality"))
    try:
        _patch({"sys": sys, "run": R}, posted=posted, box_ts=box_ts,
               b2b_ts=b2b_ts)
        return R._day_already_posted(DAY, YDAY, programs, corrected)
    finally:
        (R.box_thread_ts, R._already_replied, m1, m2, m3) = saved
        for name, mod in (("automations.b2b_quality.run", m1),
                          ("automations.shared.slack_metrics_post", m2),
                          ("automations.b2b_quality", m3)):
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


B2B_IN = {"B2B Sales Board 9.6"}
BOTH_IN = B2B_IN | {"BOX Sales Board 9.6"}


def test_ladder_pass_is_done_on_its_own_board():
    """The 5:10 ladder posts B2B only — a missing BOX reply is not its hold.
    This is 2026-09-07: without it the pass alerts three hours after posting."""
    assert _run(B2B_IN, ["B2B"]) is True


def test_ladder_pass_is_not_done_when_its_own_board_is_missing():
    assert _run(set(), ["B2B"]) is False


def test_box_pass_waits_for_the_box_reply():
    assert _run(B2B_IN, ["BOX"]) is False
    assert _run(BOTH_IN, ["BOX"]) is True


def test_box_pass_is_not_done_before_the_box_thread_exists():
    """box_order_log owns that thread; no thread means the images have nowhere
    to go, so the day really is unposted."""
    assert _run(BOTH_IN, ["BOX"], box_ts=None) is False


def test_corrected_pass_looks_for_the_name_it_will_write():
    """The re-post after the order log corrects the board carries a
    '(corrected)' suffix, so the morning's plain reply must not count as it."""
    assert _run(BOTH_IN, ["BOX"], corrected=True) is False
    assert _run(BOTH_IN | {"BOX Sales Board 9.6 (corrected)"}, ["BOX"],
                corrected=True) is True


def test_no_b2b_metrics_thread_yet_is_not_done():
    assert _run(B2B_IN, ["B2B"], b2b_ts=None) is False


def _main() -> int:
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("  ok   " + name)
            except AssertionError as e:
                fails += 1
                print("  FAIL " + name + ": " + str(e))
    print(("FAILED " + str(fails)) if fails else "all green")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(_main())
