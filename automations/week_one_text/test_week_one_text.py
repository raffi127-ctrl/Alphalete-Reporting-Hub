import datetime as dt

from automations.week_one_text import config as C
from automations.week_one_text import run as R

HDR = ["", "Roll Call", "Status", "Day 0", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat",
       "Date Gone", "Prior Weeks", "Total Sales", "Trainer"]

# The live NDS Sales Board on 2026-11-19 (rows 54-66).
GRID = [[]] * 55 + [
    ["", "WEEK 1   ·   11/16 – 11/22   ·   5 reps"],
    HDR,
    ["", "Hung Quoc Nguyen", "New Start", "11/16", "Here", "Here", "Here", "Here"],
    ["", "Izanama Shinto Sullivan", "New Start", "11/16", "Here", "Here", "Here", "Here"],
    ["", "John Anthony Escobedo", "New Start", "11/16", "Here", "Here", "Here", "Here"],
    ["", "Rocco Dichiara", "New Start", "11/16", "Here", "Here", "Here", "Here"],
    ["", "Gustavo Morales", "Terminated", "11/17", "", "T"],
    [],
    ["", "WEEK 2   ·   11/9 – 11/15   ·   2 reps"],
    HDR,
    ["", "Anairt Triana", "Active", "11/10"],
]


def test_thursday_crop_matches_carloss_picture():
    t, last, col, reps, title = R.find_week_one(GRID, dt.date(2026, 11, 19))
    assert (t, last, col, reps) == (56, 62, 8, 5)          # B56:H62
    assert R._letter(col) == "H"


def test_crop_ends_at_todays_column():
    assert R.find_week_one(GRID, dt.date(2026, 11, 20))[2] == 9   # Fri -> I
    assert R.find_week_one(GRID, dt.date(2026, 11, 16))[2] == 5   # Mon -> E


def test_table_with_no_reps():
    g = [[]] * 55 + [["", "WEEK 1   ·   11/23 – 11/29   ·   0 reps"], HDR, [],
                     ["", "WEEK 2   ·   11/16 – 11/22"]]
    t, last, col, reps, _ = R.find_week_one(g, dt.date(2026, 11, 23))
    assert reps == 0 and last == t + 1


def test_next_title_ends_the_table_even_without_a_blank_row():
    g = [[]] * 55 + [["", "WEEK 1 · 11/16 – 11/22"], HDR, ["", "A B"],
                     ["", "WEEK 2 · 11/9 – 11/15"], HDR]
    assert R.find_week_one(g, dt.date(2026, 11, 19))[1] == 58


def test_week_10_is_not_week_1():
    g = [["", "WEEK 10 · 1/1 – 1/7"], HDR]
    try:
        R.find_week_one(g, dt.date(2026, 11, 19))
    except RuntimeError:
        return
    raise AssertionError("WEEK 10 matched as WEEK 1")


def test_title_must_cover_today():
    title = "WEEK 1   ·   11/16 – 11/22   ·   5 reps"
    assert R.title_covers(title, dt.date(2026, 11, 19))
    assert not R.title_covers(title, dt.date(2026, 11, 23))   # board left on last week
    assert R.title_covers("WEEK 1 · 12/28 – 1/3", dt.date(2027, 1, 1))
    assert R.title_covers("WEEK 1 · 12/28 – 1/3", dt.date(2026, 12, 29))
    assert not R.title_covers("WEEK 1", dt.date(2026, 11, 19))


def test_text_title():
    assert R.text_title(dt.date(2026, 11, 20)) == "NDS Week 1s — Friday 11/20"


def test_monday_to_friday_only():
    assert C.WEEKDAYS == [0, 1, 2, 3, 4]
    assert R.main(["--date", "2026-11-21"]) == 0    # Saturday: nothing, no sheet read


def test_once_per_day():
    assert R.already_sent(dt.date(2026, 11, 20), {"sent_day": "2026-11-20"})
    assert not R.already_sent(dt.date(2026, 11, 23), {"sent_day": "2026-11-20"})


def test_route_goes_to_new_a_players_only():
    from automations.b2b_dispositions import config as B
    assert B.TEXT_ROUTES[(C.CAMPAIGN_LABEL, C.KIND)] == [B.TEXT_GROUP_ALL]
