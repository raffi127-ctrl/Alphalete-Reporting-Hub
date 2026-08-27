"""Times of Sales -- the parts a live run can't prove.

    python -m pytest automations/alphalete_sales_board/test_times_of_sales.py

READ-ONLY AND OFFLINE. Nothing here opens a Sheet, logs into SaraPlus or
addresses a chat: the grid is a list of lists and the only thing under test is
arithmetic and geometry. [[feedback_no_blind_test_sweeps]]

The grid fixture is a cut-down copy of the LIVE tab's shape, read off it on
2026-08-27: row 1 time labels, row 2 the three sub-headers, dates from row 3.
"""
from __future__ import annotations

import datetime as dt

from automations.alphalete_sales_board import times_of_sales as T

SUBS = ["New Internet", "Total Units", "Delta to the day Prior prior"]


def _grid(rows):
    """Header rows + the given date rows, in the live tab's shape."""
    labels, subs = [""], [""]
    for lab in ("1:00 PM", "1:30 PM", "2:00 PM", "2:30 PM", "3:00 PM"):
        labels += [lab, "", ""]
        subs += SUBS
    return [labels, subs] + rows


def _row(date_label, *vals):
    return [date_label] + list(vals)


# --- checkpoints ------------------------------------------------------------
def test_weekday_slots_run_one_to_nine():
    slots = T.slots_for(3)          # Thursday
    assert slots[0] == "1:00 PM" and slots[-1] == "9:00 PM"
    assert len(slots) == 17         # matches the 51 cells a live weekday row has


def test_saturday_stops_at_630_and_starts_at_noon():
    slots = T.slots_for(5)
    assert slots[0] == "12:00 PM" and slots[-1] == "6:30 PM"
    assert len(slots) == 14         # 12 with columns + the two text-only noons


def test_sunday_has_no_slots():
    assert T.slots_for(6) == []


def test_due_claims_a_slot_on_an_unaligned_tick():
    """THE REGRESSION THIS EXISTS FOR. The LaunchAgent is StartInterval 300,
    which never lands on :00 or :30 -- an exact-minute check fired on no tick
    of any day, and an empty column looks exactly like a quiet afternoon."""
    assert T.due(dt.datetime(2026, 8, 27, 16, 2), sent=[]) == "4:00 PM"
    assert T.due(dt.datetime(2026, 8, 27, 16, 17), sent=[]) == "4:00 PM"
    assert T.due(dt.datetime(2026, 8, 27, 16, 32), sent=[]) == "4:30 PM"


def test_due_fires_on_an_aligned_tick_too():
    assert T.due(dt.datetime(2026, 8, 27, 16, 0), sent=[]) == "4:00 PM"


def test_due_returns_nothing_once_the_slot_is_stamped():
    """The marker, not the window, is what makes it once."""
    assert T.due(dt.datetime(2026, 8, 27, 16, 7), sent=["4:00 PM"]) is None
    assert T.due(dt.datetime(2026, 8, 27, 16, 22), sent=["4:00 PM"]) is None


def test_due_will_not_stamp_a_stale_slot():
    """At 4:29 the 4:00 column would get a 4:29 reading -- refuse."""
    assert T.due(dt.datetime(2026, 8, 27, 16, 29), sent=[]) is None


def test_due_claims_only_the_latest_after_an_outage():
    """Runner down 1:00-4:07: claim 4:00 and leave the rest to back-fill,
    rather than texting the room six updates in a row."""
    assert T.due(dt.datetime(2026, 8, 27, 16, 7), sent=[]) == "4:00 PM"


def test_due_respects_the_window():
    # Inside the SWEEP window but before Times of Sales starts.
    assert T.due(dt.datetime(2026, 8, 27, 10, 0), sent=[]) is None
    # 9:30 PM has a column on the tab but is not a weekday slot.
    assert T.due(dt.datetime(2026, 8, 27, 21, 32), sent=["9:00 PM"]) is None
    # Saturday evening: past the board's 17:00 cutoff, still due.
    assert T.due(dt.datetime(2026, 8, 29, 18, 33), sent=[]) == "6:30 PM"
    assert T.due(dt.datetime(2026, 8, 30, 16, 2), sent=[]) is None   # Sunday


def test_due_before_the_first_slot_is_none():
    assert T.due(dt.datetime(2026, 8, 27, 12, 59), sent=[]) is None


def test_hhmm_round_trips_every_label():
    for wd in range(0, 6):
        for label in T.slots_for(wd):
            assert T._label(*T._hhmm(label)) == label


def test_label_is_portable():
    """No '%-I' anywhere -- this file has to import on Windows."""
    assert T._label(13, 0) == "1:00 PM"
    assert T._label(12, 30) == "12:30 PM"
    assert T._label(9, 0) == "9:00 AM"


# --- the numbers ------------------------------------------------------------
def test_totals_match_the_live_reading():
    """2026-08-26, 7:00 PM: the tab read 19 / 21 while the leaderboard read
    INT 19, Upgrades 2, DTV 2, NL 0. Upgrades are OUT of both columns."""
    agents = [
        {"internet_sales": 21, "internet_upgrades": 2, "aia_sales": 0,
         "dtv_streaming": 2, "wireless_lines_sold": 0},
    ]
    got = T.totals(agents)
    assert got["new_internet"] == 19
    assert got["dtv"] == 2
    assert got["total_units"] == 21


def test_totals_floor_at_zero_and_sum_the_team():
    agents = [
        {"internet_sales": 3, "internet_upgrades": 1, "aia_sales": 0,
         "dtv_streaming": 1, "wireless_lines_sold": 2},
        {"internet_sales": 1, "internet_upgrades": 5, "aia_sales": 0,
         "dtv_streaming": 0, "wireless_lines_sold": 0},   # a mid-day revision
    ]
    got = T.totals(agents)
    assert got["new_internet"] == 2          # 2 + max(1-5, 0)
    assert got["total_units"] == 5           # 2 + 1 + 2


def test_totals_count_reps_with_no_board_row():
    """An org time-series counts the sale; the roster problem is elsewhere."""
    agents = [{"internet_sales": 1, "internet_upgrades": 0, "aia_sales": 0,
               "dtv_streaming": 0, "wireless_lines_sold": 0, "name": "NOBODY"}]
    assert T.totals(agents)["total_units"] == 1


# --- geometry ---------------------------------------------------------------
def test_columns_are_found_by_header():
    cols = T.slot_columns(_grid([]))
    assert cols["1:00 PM"] == {"new internet": 2, "total units": 3, "delta": 4}
    assert cols["3:00 PM"]["new internet"] == 14


def test_date_label_matches_col_a():
    assert T.date_label(dt.date(2026, 8, 27)) == "Thursday, August 27, 26"
    assert T.date_label(dt.date(2026, 6, 1)) == "Monday, June 1, 26"


def test_find_row():
    grid = _grid([_row("Wednesday, August 26, 26"),
                  _row("Thursday, August 27, 26")])
    assert T.find_row(grid, dt.date(2026, 8, 27)) == 4
    assert T.find_row(grid, dt.date(2026, 9, 30)) is None


def test_read_slot_returns_none_for_blanks():
    grid = _grid([_row("Thursday, August 27, 26", "5", "", "")])
    cols = T.slot_columns(grid)["1:00 PM"]
    got = T.read_slot(grid, 3, cols)
    assert got["new_internet"] == 5 and got["total_units"] is None


# --- back-fill --------------------------------------------------------------
def test_backfill_fills_the_gap_and_stops_at_real_data():
    # 1:00 recorded, 1:30 / 2:00 missed, now writing 2:30.
    grid = _grid([_row("Thursday, August 27, 26",
                       "4", "5", "", "", "", "", "", "", "", "", "", "")])
    cols = T.slot_columns(grid)
    plan = T.backfill_plan(grid, 3, cols, T.slots_for(3), "2:30 PM",
                           {"new_internet": 9, "total_units": 12})
    assert [u["range"] for u in plan] == ["H3", "I3", "E3", "F3"]
    assert all(u["values"][0][0] in (9, 12) for u in plan)


def test_backfill_never_paints_over_a_recorded_slot():
    grid = _grid([_row("Thursday, August 27, 26",
                       "4", "5", "", "6", "7", "", "8", "9", "", "", "", "")])
    plan = T.backfill_plan(grid, 3, T.slot_columns(grid), T.slots_for(3),
                           "2:30 PM", {"new_internet": 9, "total_units": 12})
    assert plan == []


def test_backfill_never_writes_a_delta():
    grid = _grid([_row("Thursday, August 27, 26", "", "", "", "", "", "",
                       "", "", "", "", "", "")])
    plan = T.backfill_plan(grid, 3, T.slot_columns(grid), T.slots_for(3),
                           "2:30 PM", {"new_internet": 9, "total_units": 12})
    deltas = {"D3", "G3", "J3", "M3"}
    assert not deltas.intersection(u["range"] for u in plan)


def test_last_week_close_reads_the_last_filled_slot():
    grid = _grid([_row("Thursday, August 20, 26",
                       "1", "2", "", "3", "4", "", "21", "29", "", "", "", ""),
                  _row("Thursday, August 27, 26")])
    got = T.last_week_close(grid, dt.date(2026, 8, 27), T.slot_columns(grid),
                            T.slots_for(3))
    assert got == {"new_internet": 21, "total_units": 29}


def test_last_week_close_is_none_when_the_row_is_empty():
    grid = _grid([_row("Thursday, August 20, 26"),
                  _row("Thursday, August 27, 26")])
    assert T.last_week_close(grid, dt.date(2026, 8, 27), T.slot_columns(grid),
                             T.slots_for(3)) is None


# --- the message ------------------------------------------------------------
def test_message_matches_the_live_shape():
    """The 2026-08-11 4:00 PM message, line for line (Megan's screenshot)."""
    body = T.message("4:00 PM",
                     {"new_internet": 2, "dtv": 1, "total_units": 3},
                     {"new_internet": 3, "total_units": 3},
                     {"new_internet": 21, "total_units": 29},
                     dt.date(2026, 8, 11))
    assert body.splitlines() == [
        "\U0001F4CA Sales Update - 4:00 PM",
        "",
        "\U0001F310 New Internet",
        "Today: 2",
        "Yesterday at 4:00 PM: 3",
        "Difference: \U0001F534 -1",
        "",
        "\U0001F4FA DTV Streaming: 1",
        "",
        "\U0001F4E6 Total Units",
        "Today: 3",
        "Yesterday at 4:00 PM: 3",
        "Difference: 0",
        "",
        "Last Tuesday's Sales:",
        "\U0001F310 New Internet: 21",
        "\U0001F4E6 Total Units: 29",
    ]


def test_message_drops_the_comparison_when_yesterday_is_blank():
    body = T.message("1:00 PM", {"new_internet": 4, "dtv": 0, "total_units": 5},
                     {"new_internet": None, "total_units": None}, None,
                     dt.date(2026, 8, 27))
    assert "Yesterday" not in body and "Difference" not in body
    assert "Last" not in body
    assert "Today: 4" in body and "Today: 5" in body


def test_message_marks_a_gain_green():
    body = T.message("2:00 PM", {"new_internet": 9, "dtv": 0, "total_units": 11},
                     {"new_internet": 4, "total_units": 6}, None,
                     dt.date(2026, 8, 27))
    assert "Difference: \U0001F7E2 +5" in body


def test_message_uses_real_emoji_not_shortcodes():
    body = T.message("2:00 PM", {"new_internet": 1, "dtv": 0, "total_units": 1},
                     {"new_internet": None, "total_units": None}, None,
                     dt.date(2026, 8, 27))
    assert ":bar_chart:" not in body and ":globe" not in body


# --- the Hub pill -----------------------------------------------------------
def test_prune_keeps_the_hub_markers():
    """prune() rebuilds the file from scratch, so an unlisted section is
    DELETED on the next save. '_hub' was missing, which is why the sweep
    re-published its Hub row on every pass -- 30 rows on 2026-08-26."""
    from automations.alphalete_sales_board import state as S
    data = {"2026-08-27": {"Rep": {"Int": 1}},
            "_hub": {"2026-08-27": True},
            "_hub_times": {"2026-08-27": True}}
    out = S.prune(data)
    assert out.get("_hub") == {"2026-08-27": True}
    assert out.get("_hub_times") == {"2026-08-27": True}


def test_times_sent_marker_round_trips_through_prune():
    from automations.alphalete_sales_board import state as S
    day = dt.date(2026, 8, 27)
    data = S.mark_times_sent({}, day, "4:00 PM")
    data = S.mark_times_sent(data, day, "4:30 PM")
    assert S.times_sent(S.prune(data), day) == ["4:00 PM", "4:30 PM"]


def test_mark_times_sent_does_not_duplicate():
    from automations.alphalete_sales_board import state as S
    day = dt.date(2026, 8, 27)
    data = S.mark_times_sent(S.mark_times_sent({}, day, "4:00 PM"),
                             day, "4:00 PM")
    assert S.times_sent(data, day) == ["4:00 PM"]


def test_a_stamped_slot_is_never_claimed_twice():
    """The marker and due() together: the full once-per-slot guarantee."""
    from automations.alphalete_sales_board import state as S
    day = dt.date(2026, 8, 27)
    data, fired = {}, []
    tick = dt.datetime(2026, 8, 27, 15, 57)
    while tick < dt.datetime(2026, 8, 27, 17, 30):
        label = T.due(tick, sent=S.times_sent(data, day))
        if label:
            fired.append(label)
            data = S.mark_times_sent(data, day, label)
        tick += dt.timedelta(minutes=5)
    assert fired == ["4:00 PM", "4:30 PM", "5:00 PM"]


def test_latest_slot_is_what_a_hub_click_means():
    assert T.latest_slot(dt.datetime(2026, 8, 27, 16, 12)) == "4:00 PM"
    assert T.latest_slot(dt.datetime(2026, 8, 27, 9, 15)) == "1:00 PM"
    assert T.latest_slot(dt.datetime(2026, 8, 30, 14, 0)) is None   # Sunday


def test_the_hub_card_is_wired_to_this_module():
    """The card's buttons must resolve to a real slot, on any machine."""
    from automations import hub_cards as H
    card = [c for c in H.AUTOMATED_REPORTS if c["id"] == "times-of-sales"][0]
    assert card["run_machine"] == "Lucy 1"
    # NOT [] -- an empty weekday list reads as "never scheduled" and the
    # didn't-run watcher would never notice this card go quiet.
    assert card["schedule"]["weekdays"] == [0, 1, 2, 3, 4, 5]
    # Against EVERY day's slots, not Monday's: latest_slot() reads the real
    # clock, and Saturday carries 12:00/12:30 which no weekday has -- checking
    # against slots_for(0) would fail this test only on a Saturday lunchtime.
    every = {s for wd in range(0, 6) for s in T.slots_for(wd)}
    for action in card["actions"]:
        args = action["args_fn"]()
        assert "--times-slot" in args
        assert args[args.index("--times-slot") + 1] in every
