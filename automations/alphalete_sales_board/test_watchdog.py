"""The watchdog must be quiet when it should be, and loud when it matters."""
from __future__ import annotations

import datetime as dt

from automations.alphalete_sales_board import config as C, watchdog as W


def test_quiet_outside_selling_hours():
    assert W.main(["--dry-run"]) == 0     # smoke: never raises
    assert not C.in_selling_window(dt.datetime(2026, 8, 26, 6, 0))


def test_too_early_in_the_day_is_not_a_fault():
    # 10:05 — the first sweep of the day may legitimately not have landed.
    now = dt.datetime(2026, 8, 26, 10, 5)
    start = now.replace(hour=C.DAY_START_HHMM[0], minute=C.DAY_START_HHMM[1])
    assert (now - start).total_seconds() / 60.0 < W.STALE_MINUTES


def test_a_missing_log_reads_as_infinitely_stale():
    assert W.minutes_since_last_sweep(
        dt.datetime(1999, 1, 1, 12, 0)) == float("inf")


def test_stale_threshold_is_more_than_one_missed_tick():
    # 20 minutes = four missed 5-minute ticks. One slow sweep must not alert.
    assert W.STALE_MINUTES >= 15, W.STALE_MINUTES


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok  %s" % t.__name__)
    print("%d passed" % len(tests))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
