"""The selling-day fence and the previous-day catch-up bookkeeping.

Rafael 2026-09-22: apps keyed into SaraPlus after the old 21:30 stop never
reached the board. Megan the same day: "every day should be 12-12 not just
weekdays". So: noon to midnight, seven days, and the first live tick of a day
re-reads the previous day once.
"""
from __future__ import annotations

import datetime as dt

from automations.alphalete_sales_board import config as C, state as S


def test_noon_to_midnight_on_a_weekday():
    tue = dt.datetime(2026, 9, 22)                       # a Tuesday
    assert not C.in_selling_window(tue.replace(hour=11, minute=59))
    assert C.in_selling_window(tue.replace(hour=12, minute=0))
    assert C.in_selling_window(tue.replace(hour=21, minute=45))   # the old cliff
    assert C.in_selling_window(tue.replace(hour=23, minute=58))
    # A tick at midnight belongs to the NEXT day, which is empty in SaraPlus.
    assert not C.in_selling_window(dt.datetime(2026, 9, 23, 0, 1))


def test_saturday_and_sunday_run_the_same_hours():
    sat, sun = dt.datetime(2026, 9, 26), dt.datetime(2026, 9, 27)
    assert (sat.weekday(), sun.weekday()) == (5, 6)
    for day in (sat, sun):
        assert not C.in_selling_window(day.replace(hour=11, minute=30))
        assert C.in_selling_window(day.replace(hour=17, minute=30))   # old Sat stop
        assert C.in_selling_window(day.replace(hour=23, minute=30))


def test_previous_selling_day_is_yesterday_every_day():
    mon = dt.date(2026, 9, 21)
    assert C.previous_selling_day(mon) == dt.date(2026, 9, 20)      # Sunday
    assert C.previous_selling_day(dt.date(2026, 9, 22)) == mon


def test_catchup_gives_up_after_three_failures_and_finishes_on_success():
    day = dt.date(2026, 9, 21)
    data = {}
    assert not S.catchup_done(data, day)
    for _ in range(S.CATCHUP_MAX_TRIES - 1):
        data = S.mark_catchup(data, day, ok=False)
        assert not S.catchup_done(data, day)
    data = S.mark_catchup(data, day, ok=False)
    assert S.catchup_done(data, day)
    fresh = S.mark_catchup({}, day, ok=True)
    assert S.catchup_done(fresh, day)


def test_catchup_marker_survives_prune():
    day = dt.date(2026, 9, 21)
    data = S.prune(S.mark_catchup({}, day, ok=True))
    assert S.catchup_done(data, day)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok  %s" % t.__name__)
    print("%d passed" % len(tests))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
