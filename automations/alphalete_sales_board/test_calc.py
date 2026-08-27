"""The two things that would be wrong in silence: the column arithmetic and the
name match. Both are pure, so both are tested offline -- no SaraPlus, no Sheet.

Run: python -m automations.alphalete_sales_board.test_calc
"""
from __future__ import annotations

import datetime as dt

from automations.alphalete_sales_board import calc, notify as N, sara, state as S


def test_upgrades_come_out_of_internet():
    # SaraPlus "Internet Sales" is a TOTAL: 5 internet, of which 1 upgrade and
    # 1 AIA, is 3 new installs -- not 5, and not 7.
    m = calc.metrics_for({"internet_sales": 5, "internet_upgrades": 1,
                          "aia_sales": 1, "wireless_lines_sold": 2,
                          "dtv_streaming": 3})
    assert m == {"Int": 3, "Int Up": 2, "DTV": 3, "NL": 2}, m


def test_never_negative():
    m = calc.metrics_for({"internet_sales": 1, "internet_upgrades": 2,
                          "aia_sales": 1, "wireless_lines_sold": 0})
    assert m["Int"] == 0, m


def test_name_map_and_suffixes():
    names = ["Nathaniel (Nate) Martinez", "Annice Middleton", "Jaylen Walker (Wk 2)"]
    assert calc.match_name("NATHANIEL MARTINEZ", names)[0] == "Nathaniel (Nate) Martinez"
    assert calc.match_name("GLORIA SCOTT", names)[0] == "Annice Middleton"
    assert calc.match_name("JAYLEN WALKER", names)[0] == "Jaylen Walker (Wk 2)"


def test_ambiguous_last_name_refuses():
    names = ["Chris Martinez", "Nate Martinez"]
    who, note = calc.match_name("J MARTINEZ", names)
    assert who is None, who
    assert "martinez" in note.lower(), note


def test_unmatched_is_reported_not_dropped():
    rows, notes, _missing = calc.calculate(
        [{"name": "BRAND NEW", "internet_sales": 1, "internet_upgrades": 0,
          "aia_sales": 0, "wireless_lines_sold": 0, "dtv_streaming": 0}],
        ["Someone Else"])
    assert rows == [], rows
    assert notes and "BRAND NEW" in notes[0], notes


def test_excluded_rep_is_skipped_without_being_called_a_problem():
    # Joshua Mascorro sells in SaraPlus and is deliberately not on the board.
    # He must not come back as "add them to the roster" 150 times a day.
    rows, notes, _missing = calc.calculate(
        [{"name": "JOSHUA MASCORRO", "internet_sales": 2, "internet_upgrades": 0,
          "aia_sales": 0, "wireless_lines_sold": 1, "dtv_streaming": 0}],
        ["Someone Else"])
    assert rows == [], rows
    assert len(notes) == 1, notes
    assert "deliberately off the board" in notes[0], notes
    assert "add them to the roster" not in notes[0].lower(), notes


def test_a_genuinely_missing_rep_still_gets_flagged():
    # The exclusion must not quiet anybody else.
    rows, notes, _missing = calc.calculate(
        [{"name": "ANTONIO DAVIS", "internet_sales": 1, "internet_upgrades": 0,
          "aia_sales": 0, "wireless_lines_sold": 0, "dtv_streaming": 0}],
        ["Someone Else"])
    assert rows == [], rows
    assert any("ANTONIO DAVIS" in n and "roster" in n for n in notes), notes


def test_zero_reps_are_skipped():
    rows, _n, _m = calc.calculate(
        [{"name": "SOMEONE ELSE", "internet_sales": 0, "internet_upgrades": 0,
          "aia_sales": 0, "wireless_lines_sold": 0, "dtv_streaming": 0}],
        ["Someone Else"])
    assert rows == [], rows


def test_office_code_is_stripped_for_the_dtv_merge():
    assert sara.strip_office("JANE DOE (11580)- ALPHALETE") == "JANE DOE"
    agents = [{"name": "Jane Doe", "internet_sales": 1, "internet_upgrades": 0,
               "aia_sales": 0, "wireless_lines_sold": 0, "dtv_streaming": 0}]
    merged = sara.merge_dtv(agents, {"JANE DOE": 2})
    assert merged[0]["dtv_streaming"] == 2, merged


def test_wrong_row_marker_reads_nothing_rather_than_something_else():
    # The AT&T Internet grid uses 6_Agent. Parsed with the 5_Agent marker it
    # must come back EMPTY, never with group rows read as reps.
    rows = [["+", "6_Agent", "JANE DOE", "3"], ["+", "3_Group", "TEXAS", "99"]]
    assert sara.parse_records(rows) == {"JANE DOE": 3}
    assert sara.parse_att(rows) == []


def test_deltas_only_count_increases():
    day = dt.date(2026, 8, 26)
    data = {day.isoformat(): {"Jane Doe": {"Int": 2, "Int Up": 0, "DTV": 0, "NL": 1}}}
    up = S.deltas(data, day, {"Jane Doe": {"Int": 3, "Int Up": 0, "DTV": 0, "NL": 1}})
    assert up == {"Jane Doe": {"Int": 1}}, up
    # a DROP is not news, and it is not a reset either
    assert S.deltas(data, day, {"Jane Doe": {"Int": 1, "Int Up": 0, "DTV": 0, "NL": 0}}) == {}


def test_remember_never_moves_a_number_down():
    day = dt.date(2026, 8, 26)
    data = S.remember({}, day, {"Jane Doe": {"Int": 3, "Int Up": 0, "DTV": 0, "NL": 0}}, {})
    data = S.remember(data, day, {"Jane Doe": {"Int": 1, "Int Up": 0, "DTV": 0, "NL": 0}}, {})
    assert data[day.isoformat()]["Jane Doe"]["Int"] == 3, data
    # ...so the short export can't re-announce the sale on the next sweep
    assert S.deltas(data, day, {"Jane Doe": {"Int": 3, "Int Up": 0, "DTV": 0, "NL": 0}}) == {}


def test_a_missing_rep_is_named_in_the_text_and_counted():
    # Megan 2026-08-26: "if someone gets a sale and is missing from the board
    # the text update should say that". Listing them but leaving them out of
    # TOTALS would under-report the day, which is the same failure in reverse.
    rows, _n, missing = calc.calculate(
        [{"name": "ANTONIO DAVIS", "internet_sales": 1, "internet_upgrades": 0,
          "aia_sales": 0, "wireless_lines_sold": 2, "dtv_streaming": 0}],
        ["Someone Else"])
    assert rows == [] and len(missing) == 1, (rows, missing)
    text = N.leaderboard({"Jane Doe": {"Int": 1, "Int Up": 0, "DTV": 0, "NL": 0}},
                         [], None, missing)
    assert "ANTONIO DAVIS 3 (1 Int, 2 NL)" in text, text
    assert "TOTALS: 4" in text, text                   # 1 + (1 Int + 2 NL)
    assert "no row on this week's board" in text, text


def test_an_excluded_rep_never_reaches_the_text():
    rows, _n, missing = calc.calculate(
        [{"name": "JOSHUA MASCORRO", "internet_sales": 3, "internet_upgrades": 0,
          "aia_sales": 0, "wireless_lines_sold": 0, "dtv_streaming": 0}],
        ["Someone Else"])
    assert rows == [] and missing == [], (rows, missing)
    text = N.leaderboard({}, [], None, missing)
    assert "MASCORRO" not in text.upper(), text


def test_hype_tiers():
    assert N.tier({"Int": 1, "NL": 5}) == "super"
    assert N.tier({"Int": 1, "NL": 2}) == "large"
    assert N.tier({"Int": 0, "NL": 9}) == "regular"       # no Int, no matter the lines
    assert N.tier({"Int": 1, "NL": 0}) == "regular"


def test_hype_is_stable_across_a_rerun():
    day = dt.date(2026, 8, 26)
    m = {"Int": 1, "NL": 0}
    assert N.hype("Jane Doe", m, day) == N.hype("Jane Doe", m, day)


def test_leaderboard_matches_the_live_post():
    # Rebuilt from the message the existing system posted on 2026-08-26:
    # 'First L.' names, breakdown only when there's more than one kind of
    # sale, real emoji, upgrades INSIDE the totals, no goal line.
    today = {"Jane Doe": {"Int": 2, "Int Up": 1, "DTV": 1, "NL": 0},
             "Rex Ryan": {"Int": 2, "Int Up": 0, "DTV": 0, "NL": 0}}
    text = N.leaderboard(today, ["Jane Doe"])
    lines = text.splitlines()
    assert lines[0] == "Jane Doe 4 (2 Int, 1 Up, 1 DTV) \U0001F525", lines[0]
    assert lines[1] == "Rex Ryan 2 (2 Int)", lines[1]
    assert "Upgrades: 1" in text, text
    assert "\U0001F3C6 TOTALS: 6" in text, text       # 4 + 2, upgrades counted
    assert "GOAL FOR THE WEEK" in N.leaderboard(today, [], 42), "our layout keeps the goal"


def test_ties_keep_saraplus_order():
    today = {"Zoe Adams": {"Int": 1, "Int Up": 0, "DTV": 0, "NL": 0},
             "Al Baker": {"Int": 1, "Int Up": 0, "DTV": 0, "NL": 0}}
    assert N.leaderboard(today, []).splitlines()[:2] == ["Zoe Adams 1 (1 Int)",
                                                        "Al Baker 1 (1 Int)"]


def test_short_name_drops_week_suffixes():
    assert N.short_name("Jaylen (Ash) Walker (Wk 2)") == "Jaylen Walker"
    assert N.short_name("Cher") == "Cher"


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok  %s" % t.__name__)
    print("%d passed" % len(tests))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
