"""The banded clock for the board's OwnerVille scan.

    python -m pytest automations/icd_onboarding/test_cadence.py -q
"""
import datetime as dt

import pytest

from automations.icd_onboarding import cadence as C


def at(hour, minute=0):
    return dt.datetime(2026, 11, 24, hour, minute)


@pytest.mark.parametrize("hour,minutes", [
    (7, 60), (8, 15), (9, 15), (11, 15),        # 8 to noon: every 15
    (12, 30), (13, 30), (14, 30),               # noon to 3: every 30
    (15, 60), (19, 60), (23, 60),               # 3pm on: hourly
    (0, 60), (3, 60), (6, 60),                  # overnight: hourly
])
def test_the_bands_are_megans(hour, minutes):
    """15 minutes 8am-noon, 30 noon-3pm, hourly the rest (2026-11-24)."""
    assert C.every_minutes(at(hour)) == minutes


def test_every_hour_of_the_day_has_a_band():
    """An hour with no band must never mean "run constantly"."""
    for hour in range(24):
        assert C.every_minutes(at(hour)) in (15, 30, 60)


def test_nothing_run_yet_is_due():
    assert C.due(None, at(3)) is True


def test_a_pass_inside_the_gap_is_not_due():
    assert C.due(at(9, 0), at(9, 10)) is False      # 15-min band
    assert C.due(at(13, 0), at(13, 20)) is False    # 30-min band
    assert C.due(at(18, 0), at(18, 40)) is False    # hourly


def test_a_pass_past_the_gap_is_due():
    assert C.due(at(9, 0), at(9, 16)) is True
    assert C.due(at(13, 0), at(13, 31)) is True
    assert C.due(at(18, 0), at(19, 1)) is True


def test_the_band_of_NOW_decides_not_the_band_of_the_last_run():
    """A scan that last went at 7:50 is due at 8:05, because 8 o'clock is a
    15-minute hour. Reading the earlier run's band would hold the morning's
    first fast pass back to 8:50 -- the hour it matters most."""
    assert C.due(at(7, 50), at(8, 5)) is True


def test_a_clock_that_went_backwards_does_not_lock_it_out():
    """A laptop waking, or a DST shift. A negative gap must not mean "never
    again until it goes positive"."""
    assert C.due(at(10, 0), at(9, 0)) is True


def test_the_agent_fires_at_least_as_often_as_every_band_needs():
    """launchd has no "every N minutes between these hours", so the agent fires
    on the band's own minutes and the module decides. A band whose minutes are
    missing from the plist is a band that silently never runs."""
    rows = set(C.plist_minutes())
    for start, until, minutes in C.BANDS:
        for hour in range(start, until):
            for minute in range(0, 60, minutes):
                assert (hour, minute) in rows, (hour, minute)


def test_the_plist_is_generated_from_the_bands_not_typed():
    """The committed agent has to match, or the bands are a comment."""
    import pathlib
    import re
    text = (pathlib.Path(__file__).resolve().parents[2] / "deploy"
            / "com.alphalete.icd-onboarding.plist").read_text()
    found = set()
    for h, m in re.findall(
            r"<key>Hour</key><integer>(\d+)</integer>"
            r"<key>Minute</key><integer>(\d+)</integer>", text):
        found.add((int(h), int(m)))
    assert found == set(C.plist_minutes()), \
        "re-generate with `python -m automations.icd_onboarding.cadence --plist`"


def test_the_stamp_survives_a_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "stamp_path", lambda: tmp_path / "nope.txt")
    assert C.last_run() is None
    assert C.due(C.last_run(), at(9)) is True


def test_the_stamp_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "stamp_path", lambda: tmp_path / "last.txt")
    C.mark_run(at(9, 0))
    assert C.last_run() == at(9, 0)
    assert C.due(C.last_run(), at(9, 10)) is False
    assert C.due(C.last_run(), at(9, 20)) is True
