"""The selling-day fence and the previous-day catch-up bookkeeping.

Rafael 2026-09-22: apps keyed into SaraPlus after the old 21:30 stop never
reached the board. Megan the same day: "every day should be 12-12 not just
weekdays". So: noon to midnight, seven days, and the first live tick of a day
re-reads the previous day once.
"""
from __future__ import annotations

import datetime as dt
import re
import subprocess
from pathlib import Path

from automations.alphalete_sales_board import config as C, state as S


def test_noon_to_midnight_on_a_weekday():
    tue = dt.datetime(2026, 9, 22)                       # a Tuesday
    assert not C.in_selling_window(tue.replace(hour=11, minute=59))
    assert C.in_selling_window(tue.replace(hour=12, minute=0))
    assert C.in_selling_window(tue.replace(hour=21, minute=45))   # the old cliff
    assert C.in_selling_window(tue.replace(hour=23, minute=58))
    # A tick at midnight belongs to the NEXT day, which is empty in SaraPlus.
    assert not C.in_selling_window(dt.datetime(2026, 9, 23, 0, 1))


def test_sunday_runs_noon_to_midnight():
    sun = dt.datetime(2026, 9, 27)
    assert sun.weekday() == 6
    assert not C.in_selling_window(sun.replace(hour=11, minute=30))
    assert C.in_selling_window(sun.replace(hour=12, minute=0))
    assert C.in_selling_window(sun.replace(hour=23, minute=30))


def test_saturday_starts_at_1030():
    # Raf 2026-10-10: "Start it at 10:30 on Saturday."
    sat = dt.datetime(2026, 10, 17)
    assert sat.weekday() == 5
    assert C.day_start(5) == (10, 30)
    assert not C.in_selling_window(sat.replace(hour=10, minute=29))
    assert C.in_selling_window(sat.replace(hour=10, minute=30))
    assert C.in_selling_window(sat.replace(hour=11, minute=30))
    assert C.in_selling_window(sat.replace(hour=17, minute=30))   # old Sat stop
    assert C.in_selling_window(sat.replace(hour=23, minute=30))


def test_only_saturday_moved():
    for wd in (0, 1, 2, 3, 4, 6):
        assert C.day_start(wd) == (12, 0) == C.DAY_START_HHMM


# --- the bash wrapper's gate must say the same thing as config -------------
WRAPPER = Path(__file__).resolve().parents[2] / "deploy" / "alphalete_sales_board_5min.sh"


def _wrapper_gate(stamp: dt.datetime) -> bool:
    """Run ONLY the wrapper's gate lines under a faked `date`; True = it would
    go on to start the sweep. Never reaches the python call."""
    lines = WRAPPER.read_text().splitlines()
    first = next(i for i, l in enumerate(lines) if l.startswith("HOUR=$(date"))
    last = next(i for i, l in enumerate(lines) if l.startswith('if [ "$HOUR" -eq 2 ]'))
    fake = ('date() { case "$1" in +%%H) echo %s;; +%%H%%M) echo %s;; '
            '+%%u) echo %d;; esac; }' % (stamp.strftime("%H"), stamp.strftime("%H%M"),
                                         stamp.isoweekday()))
    script = "\n".join([fake] + lines[first:last + 1] + ["echo RUN"])
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    return "RUN" in out.stdout


def test_wrapper_numbers_match_config():
    text = WRAPPER.read_text()
    start = re.search(r"^START=(\d{4})$", text, re.M).group(1)
    sat = re.search(r"^SAT_START=(\d{4})$", text, re.M).group(1)
    assert start == "%02d%02d" % C.DAY_START_HHMM
    assert sat == "%02d%02d" % C.day_start(5)


def test_wrapper_gate_agrees_with_config():
    sat, tue, sun = (dt.datetime(2026, 10, 17), dt.datetime(2026, 10, 13),
                     dt.datetime(2026, 10, 18))
    cases = [(sat, 9, 59), (sat, 10, 25), (sat, 10, 30), (sat, 10, 35),
             (sat, 11, 55), (sat, 12, 0), (tue, 10, 30), (tue, 11, 55),
             (tue, 12, 0), (tue, 18, 0), (sun, 10, 30), (sun, 12, 5)]
    for day, h, m in cases:
        now = day.replace(hour=h, minute=m)
        assert _wrapper_gate(now) == C.in_selling_window(now), now
    assert _wrapper_gate(sat.replace(hour=10, minute=30))
    assert not _wrapper_gate(sat.replace(hour=10, minute=25))
    assert not _wrapper_gate(tue.replace(hour=10, minute=30))
    # 2am still runs (as the refresh), on any day.
    assert _wrapper_gate(tue.replace(hour=2, minute=5))


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
