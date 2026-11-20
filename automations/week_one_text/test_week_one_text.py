import datetime as dt

from automations.week_one_text import config as C
from automations.week_one_text import run as R

HDR = ["", "Roll Call", "Status", "Day 0", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat",
       "Date Gone", "Prior Weeks", "Total Sales", "Trainer"]

# The live NDS Sales Board on 2026-11-19 (rows 54-82).
GRID = [[]] * 55 + [
    ["", "WEEK 1   ·   11/16 – 11/22   ·   5 reps"],          # 56
    HDR,
    ["", "Hung Quoc Nguyen", "New Start", "11/16", "Here", "Here", "Here", "Here"],
    ["", "Izanama Shinto Sullivan", "New Start", "11/16", "Here", "Here", "Here", "Here"],
    ["", "John Anthony Escobedo", "New Start", "11/16", "Here", "Here", "Here", "Here"],
    ["", "Rocco Dichiara", "New Start", "11/16", "Here", "Here", "Here", "Here"],
    ["", "Gustavo Morales", "Terminated", "11/17", "", "T"],                     # 62
    [],
    ["", "WEEK 2   ·   11/9 – 11/15   ·   2 reps"],             # 64
    HDR,
    ["", "Anairt Triana", "Active", "11/10"],
    ["", "Christopher Eduardo Cajabon Penagos", "Terminated", "11/10"],          # 67
    [],
    ["", "WEEK 3   ·   11/2 – 11/8   ·   4 reps"],              # 69
    HDR,
    ["", "Isadora Bazan Puga"], ["", "Angela Juliette Rizo"],
    ["", "Roseanna Jurado"], ["", "Stefany Zaldivar"],                           # 74
    [],
    ["", "WEEK 4   ·   10/26 – 11/1   ·   1 rep"],              # 76
    HDR,
    ["", "Elisa Diaz-Garcia", "Active", "10/27"],                                # 78
    [],
    ["", "TERMINATED   ·   4 weeks   ·   10 reps"],                   # 80
    ["", "Roll Call", "Days Lasted", "Total Orders", "Trainer"],
    ["", "Brianna Belen Contreras", "26", "2", "Nick Smedra"],
]


def test_thursday_crop_matches_carloss_picture():
    t, last, col, reps, title = R.find_week_one(GRID, dt.date(2026, 11, 19))
    assert (t, last, col, reps) == (56, 62, 8, 5)          # B56:H62
    assert R._letter(col) == "H"


def test_crop_ends_at_todays_column():
    assert R.find_week_one(GRID, dt.date(2026, 11, 20))[2] == 9   # Fri -> I
    assert R.find_week_one(GRID, dt.date(2026, 11, 16))[2] == 5   # Mon -> E


def test_weeks_shot_is_week_1_to_week_4_full_width():
    top, last, col, reps, title = R.find_weeks(GRID)
    assert (top, last, R._letter(col), reps) == (56, 78, "N", 5 + 2 + 4 + 1)   # B56:N78
    assert title.startswith("WEEK 1")


def test_weeks_shot_never_takes_terminated():
    tables = R.parse_tables(GRID)
    assert [t["num"] for t in tables] == [1, 2, 3, 4, 0]
    assert R.find_weeks(GRID)[1] < tables[-1]["title"]


def test_weeks_shot_with_fewer_tables():
    g = GRID[:68] + GRID[79:]          # WEEK 1, WEEK 2, then TERMINATED
    assert R.find_weeks(g)[1] == 67


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


def test_text_titles():
    d = dt.date(2026, 11, 20)
    assert R.text_title("nds", "week1", d) == "AT&T Week 1s — Friday 11/20"
    assert R.text_title("verizon", "weeks", d) == "Verizon Weeks 1–4 — Friday 11/20"


def test_monday_to_friday_only():
    assert C.WEEKDAYS == [0, 1, 2, 3, 4]
    assert R.main(["--date", "2026-11-21"]) == 0    # Saturday: nothing, no sheet read
    assert R.main(["--date", "2026-11-22", "--shot", "weeks"]) == 0


def test_once_per_day_per_shot_and_board():
    st = {"day": "2026-11-20", "sent": ["week1:nds", "weeks:verizon"]}
    d = dt.date(2026, 11, 20)
    assert R.already_sent(d, "week1", "nds", st)
    assert not R.already_sent(d, "week1", "verizon", st)
    assert R.already_sent(d, "weeks", "verizon", st)
    assert not R.already_sent(dt.date(2026, 11, 23), "week1", "nds", st)
    # the 11/19 state format (NDS week 1 only)
    old = {"sent_day": "2026-11-20"}
    assert R.already_sent(d, "week1", "nds", old)
    assert not R.already_sent(d, "week1", "verizon", old)


def test_every_board_and_shot_goes_to_new_a_players_only():
    from automations.b2b_dispositions import config as B
    assert set(C.ROUTES) == {(b, s) for b in C.BOARD_ORDER for s in C.SHOTS}
    for key in C.ROUTES.values():
        assert B.TEXT_ROUTES[key] == [B.TEXT_GROUP_ALL], key
