"""The NDS Sales Board fill from the SaraPlus relay -- fakes only, no network.

    python -m unittest automations.vantura_nds_sara.test_run -v

Carlos 2026-10-23: units are the real sales -- upgrades, tablets and
wearables never get added. The relay already keeps tablets, wearables and
upgrade lines out of NL (icd_alerts/relay._nds_lines); this module adds
Int + NL and nothing else, picks the newest relay row of the day, holds when
there is none, matches SaraPlus's caps names to the board's, keeps hand-typed
markers unless SaraPlus shows sales, and reuses Megan's overwrite rule.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import unittest
from unittest import mock

from automations.icd_alerts import post as P
from automations.vantura_nds_sara import run
from automations.vantura_slack_sales import run as R

DAY = dt.date(2026, 10, 23)                     # Friday, week ending 10.25
FRI = 9                                          # col I


def relay_row(office, sales, received, agent="icd_alerts/5", day=DAY):
    """One 'ICD Relay' row in post.py's column positions."""
    row = [""] * (P.COL_MACHINES + 1)
    row[P.COL_OFFICE] = office
    row[P.COL_DAY] = day.isoformat()
    row[P.COL_RECORDS] = json.dumps({r: 1 for r in sales})
    row[P.COL_RECEIVED] = received
    row[P.COL_LOCAL_TIME] = "2026-10-23T14:00:00"
    row[P.COL_AGENT] = agent
    row[P.COL_SALES] = json.dumps(sales)
    return row


def nds(int_=0, nl=0, up=0, dtv=0, air=0, **extra):
    m = {"Int": int_, "Int Up": up, "DTV": dtv, "NL": nl, "Air": air}
    m.update(extra)
    return m


def grid(cells, we="10.25"):
    """The NDS board: header row 4, reps from row 5, 'AT&T NDS' subtotal
    label ending the block. `cells` is {REP: Friday value}."""
    g = [[""] * 16 for _ in range(4 + len(cells) + 1)]
    g[1][1] = we                                           # B2, the gold cell
    g[3][1], g[3][11] = "REP", "Campaign"
    for i, d in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday",
                           "Friday", "Saturday", "Sunday"]):
        g[3][4 + i] = d
    for i, (name, val) in enumerate(cells.items()):
        r = 4 + i
        g[r][1], g[r][FRI - 1], g[r][11] = name, val, "NDS"
    g[4 + len(cells)][1] = R.TOTALS_TOP
    return g


LOOKUP = {"carlos": "b2b_box", "carlos-b2batt": "nds", "kash": "att",
          "carlos-nds": "nds"}


def lookup(key):
    return LOOKUP.get(key)


class UnitsRuleTest(unittest.TestCase):
    def test_units_are_int_plus_nl_plus_air(self):
        # Jacob at 11 lines on SaraPlus: 7 ported count, 4 upgrade lines do
        # not -- the relay already moved those into Int Up. One fiber and one
        # Internet Air count too (Carlos 2026-10-23: Air is a new internet
        # sale under NDS, not an upgrade).
        got = run.units_for({"JACOB ISAIAH ORTEGA": nds(int_=1, nl=7, up=4, dtv=2, air=1)})
        self.assertEqual(got["JACOB ISAIAH ORTEGA"]["units"], 9)

    def test_int_up_and_dtv_never_add(self):
        got = run.units_for({"ANA": nds(up=5, dtv=3, air=2)})
        self.assertEqual(got["ANA"]["units"], 2)        # only the Air
        self.assertEqual((got["ANA"]["Int Up"], got["ANA"]["DTV"], got["ANA"]["Air"]),
                         (5, 3, 2))                    # upgrades + DTV shown, not counted

    def test_garbage_and_negatives_read_as_zero(self):
        got = run.units_for({"X": {"Int": "-2", "NL": "abc", "DTV": None}})
        self.assertEqual(got["X"]["units"], 0)
        got = run.units_for({"Y": {"Int": "1", "NL": "2.0"}})
        self.assertEqual(got["Y"]["units"], 3)

    def test_credit_checks_ride_along_when_present(self):
        got = run.units_for({"Z": nds(nl=1, **{"Credit Checked": 3, "Credit Passed": 2})})
        self.assertEqual((got["Z"]["Credit Checked"], got["Z"]["Credit Passed"]), (3, 2))
        self.assertNotIn("Credit Checked", run.units_for({"Q": nds(nl=1)})["Q"])

    def test_empty_and_odd_shapes(self):
        self.assertEqual(run.units_for(None), {})
        self.assertEqual(run.units_for({"": nds(nl=1), "A": "junk"}),
                         {"A": {"Int": 0, "NL": 0, "Int Up": 0, "Air": 0,
                                "DTV": 0, "units": 0}})


class LatestSnapshotTest(unittest.TestCase):
    def rows(self):
        return [
            (2, relay_row("carlos-b2batt", {"A": nds(nl=1)}, "10/23/2026 11:02:10")),
            (3, relay_row("kash", {"K": nds(nl=9)}, "10/23/2026 20:00:00")),
            (4, relay_row("carlos-b2batt", {"A": nds(nl=3)}, "10/23/2026 14:30:00")),
            (5, relay_row("carlos-b2batt", {"A": nds(nl=2)}, "2026-10-23 12:00:00")),
        ]

    def test_newest_received_at_wins_whatever_the_format(self):
        snap = run.latest_snapshot(self.rows(), "carlos-b2batt")
        self.assertEqual(snap["rownum"], 4)
        self.assertEqual(snap["sales"]["A"]["NL"], 3)
        self.assertEqual(snap["received"], dt.datetime(2026, 10, 23, 14, 30))

    def test_other_offices_are_not_read(self):
        snap = run.latest_snapshot(self.rows(), "carlos-b2batt")
        self.assertNotIn("K", snap["sales"])
        self.assertIsNone(run.latest_snapshot(self.rows(), "carlos-nds"))

    def test_unparseable_stamp_loses_to_any_parsed_one(self):
        rows = [(2, relay_row("o", {"A": nds(nl=5)}, "yesterday-ish")),
                (3, relay_row("o", {"A": nds(nl=1)}, "10/23/2026 09:00:00"))]
        self.assertEqual(run.latest_snapshot(rows, "o")["rownum"], 3)
        only = [(7, relay_row("o", {"A": nds(nl=5)}, ""))]
        self.assertEqual(run.latest_snapshot(only, "o")["rownum"], 7)

    def test_key_match_is_case_and_space_insensitive(self):
        rows = [(2, relay_row(" Carlos-B2BATT ", {"A": nds(nl=1)}, "10/23/2026 11:00:00"))]
        self.assertIsNotNone(run.latest_snapshot(rows, "carlos-b2batt"))

    def test_no_rows_is_none(self):
        self.assertIsNone(run.latest_snapshot([], "carlos-b2batt"))


class PickOfficeTest(unittest.TestCase):
    def rows(self, *keys):
        return [(i + 2, relay_row(k, {}, "10/23/2026 11:00:00"))
                for i, k in enumerate(keys)]

    def test_the_one_carlos_nds_office_is_picked(self):
        key, why, seen = run.pick_office(self.rows("kash", "carlos", "carlos-b2batt"),
                                         lookup=lookup)
        self.assertEqual((key, why), ("carlos-b2batt", ""))
        self.assertEqual(seen["carlos"], "b2b_box")

    def test_box_and_att_enrolments_are_ignored(self):
        key, why, _ = run.pick_office(self.rows("carlos", "kash"), lookup=lookup)
        self.assertIsNone(key)
        self.assertIn("carlos (b2b_box)", why)
        key, why, _ = run.pick_office(self.rows("carlos-b2batt"),
                                      lookup=lambda k: "att")
        self.assertIsNone(key)
        self.assertIn("carlos-b2batt (att)", why)

    def test_nothing_relayed_says_so(self):
        key, why, _ = run.pick_office([], lookup=lookup)
        self.assertIsNone(key)
        self.assertIn("no carlos* office", why)

    def test_two_qualifying_offices_hold_for_a_person(self):
        key, why, _ = run.pick_office(self.rows("carlos-b2batt", "carlos-nds"),
                                      lookup=lookup)
        self.assertIsNone(key)
        self.assertIn("--office", why)

    def test_pinned_office_still_has_to_be_nds(self):
        rows = self.rows("carlos", "carlos-b2batt")
        self.assertEqual(run.pick_office(rows, "carlos-b2batt", lookup=lookup)[0],
                         "carlos-b2batt")
        key, why, _ = run.pick_office(rows, "carlos", lookup=lookup)
        self.assertIsNone(key)
        self.assertIn("'b2b_box'", why)
        key, why, _ = run.pick_office(rows, "nobody", lookup=lookup)
        self.assertIsNone(key)
        self.assertIn("has not relayed", why)

    def test_an_unknown_office_is_never_picked(self):
        key, why, _ = run.pick_office(self.rows("carlos-mystery"), lookup=lambda k: None)
        self.assertIsNone(key)
        self.assertIn("not enrolled", why)


BOARD = grid({"Yahir Uriel Lopez": "0", "Nick Smedra": "2", "Aaron De La Torre": "",
              "Andrew De La Torre": "1", "Diego Borres": "4", "Jacob Ortega": "X",
              "Sebastian Avellaneda": "F", "Nico Murrugarra": "", "Will Bautista": "",
              "Jose Manuel Pimentel Lugo": "3"})
ROWS = R.campaign_rows(BOARD, "B2B")


class NameMatchingTest(unittest.TestCase):
    def test_caps_legal_names_reach_the_board_rows(self):
        for sara, want in [("JACOB ISAIAH ORTEGA", "jacob ortega"),
                           ("DIEGO JAVIER DEL POZO BORRES", "diego borres"),
                           ("YAHIR URIEL LOPEZ", "yahir uriel lopez"),
                           ("JOSE MANUEL PIMENTEL LUGO", "jose manuel pimentel lugo"),
                           ("Sebastian Avellaneda", "sebastian avellaneda")]:
            self.assertEqual(run.board_key(sara, ROWS), want, sara)

    def test_aliases_for_the_names_the_rule_cannot_reach(self):
        self.assertEqual(run.board_key("NICHOLAS SMEDRA", ROWS), "nick smedra")
        self.assertEqual(run.board_key("NICOLAS MURRUGARRA", ROWS), "nico murrugarra")
        self.assertEqual(run.candidates("NICOLAS MURRUGARRA")[0], "Nico Murrugarra")

    def test_legal_first_name_map_is_the_last_resort(self):
        # Not in ALIASES; the order-log fill's william -> will does it.
        self.assertEqual(run.board_key("WILLIAM BAUTISTA", ROWS), "will bautista")

    def test_the_two_de_la_torres_stay_apart(self):
        self.assertEqual(run.board_key("AARON DE LA TORRE", ROWS), "aaron de la torre")
        self.assertEqual(run.board_key("ANDREW DE LA TORRE", ROWS), "andrew de la torre")

    def test_unknown_names_are_none_not_guessed(self):
        self.assertIsNone(run.board_key("GHOST REP", ROWS))
        self.assertIsNone(run.board_key("JOSE PIMENTEL", ROWS))   # last token differs
        self.assertIsNone(run.board_key("", ROWS))


class PlanTest(unittest.TestCase):
    def plan(self, per):
        return run.plan(BOARD, FRI, ROWS, {k: dict(nds(**v), units=v.get("int_", 0) + v.get("nl", 0))
                                           for k, v in per.items()})

    def cells(self, plan_rows):
        return {name: (cur, new, note.strip()) for name, _a1, cur, new, note in plan_rows}

    def test_marker_kept_when_saraplus_shows_no_sales(self):
        plan_rows, flags = self.plan({"JACOB ISAIAH ORTEGA": dict(up=3)})
        self.assertEqual(plan_rows, [])
        self.assertEqual([f for f in flags if "Jacob" in f], [])

    def test_marker_replaced_when_saraplus_shows_sales(self):
        plan_rows, _ = self.plan({"JACOB ISAIAH ORTEGA": dict(nl=2)})
        self.assertEqual(self.cells(plan_rows)["Jacob Ortega"],
                         ("X", "2", "(replaces marker 'X')"))

    def test_set_up_and_down_and_cleared(self):
        plan_rows, _ = self.plan({"NICHOLAS SMEDRA": dict(nl=4),            # 2 -> 4
                                  "DIEGO JAVIER DEL POZO BORRES": dict(int_=1, nl=1),  # 4 -> 2
                                  "JOSE MANUEL PIMENTEL LUGO": dict(up=2)})  # 3 -> blank
        got = self.cells(plan_rows)
        self.assertEqual(got["Nick Smedra"], ("2", "4", ""))
        self.assertEqual(got["Diego Borres"], ("4", "2", "(LOWERED to SaraPlus)"))
        self.assertEqual(got["Jose Manuel Pimentel Lugo"],
                         ("3", "(blank)", "(cleared -- SaraPlus shows 0 units)"))

    def test_zero_is_blank_and_blank_is_zero(self):
        plan_rows, _ = self.plan({"YAHIR URIEL LOPEZ": dict(),         # "0" stays
                                  "AARON DE LA TORRE": dict()})         # "" stays
        self.assertEqual(plan_rows, [])
        plan_rows, _ = self.plan({"AARON DE LA TORRE": dict(nl=1)})
        self.assertEqual(self.cells(plan_rows)["Aaron De La Torre"], ("(blank)", "1", ""))

    def test_board_rep_absent_from_saraplus_is_left_and_flagged(self):
        plan_rows, flags = self.plan({"NICHOLAS SMEDRA": dict(nl=2)})
        self.assertEqual(plan_rows, [])                   # already 2
        self.assertTrue(any("Diego Borres has 4" in f and "LEFT" in f for f in flags))
        self.assertFalse(any("Aaron" in f for f in flags))   # blank rows are not news

    def test_saraplus_rep_on_no_row_is_flagged_never_written(self):
        plan_rows, flags = self.plan({"GHOST REP": dict(nl=3)})
        self.assertEqual(plan_rows, [])
        self.assertTrue(any("GHOST REP" in f and "(3)" in f for f in flags))

    def test_saraplus_rep_on_no_row_with_no_units_is_silent(self):
        # Upgrades and DTV only, no row: nothing lost, so not a hole to flag.
        # (The board reps absent from SaraPlus are still flagged, as always.)
        plan_rows, flags = self.plan({"GHOST REP": dict(up=2, dtv=1)})
        self.assertEqual(plan_rows, [])
        self.assertFalse(any("GHOST" in f for f in flags))
        self.assertTrue(any("LEFT as-is" in f for f in flags))

    def test_two_spellings_on_one_row_are_summed(self):
        plan_rows, flags = self.plan({"NICHOLAS SMEDRA": dict(nl=1),
                                      "Nick Smedra": dict(int_=2)})
        self.assertEqual(self.cells(plan_rows)["Nick Smedra"], ("2", "3", ""))
        self.assertTrue(any("summed" in f and "NICHOLAS SMEDRA" in f for f in flags))

    def test_batch_values_write_numbers_and_blanks(self):
        plan_rows = [("A", "I5", "2", "4", ""), ("B", "I6", "3", "(blank)", "")]
        self.assertEqual(run.batch_values(plan_rows),
                         [{"range": "I5", "values": [[4]]},
                          {"range": "I6", "values": [[""]]}])

    def test_board_rules_reuse_plan_overwrite_shape(self):
        writes = [("A", "I5", "(blank)", 0), ("B", "I6", "T", 0), ("C", "I7", "T", 2),
                  ("D", "I8", "5", 0), ("E", "I9", "5", 5), ("F", "I10", "1", 3)]
        got = {n: (c, v, note.strip()) for n, _a, c, v, note in run.board_rules(writes)}
        self.assertEqual(sorted(got), ["C", "D", "F"])
        self.assertEqual(got["C"], ("T", "2", "(replaces marker 'T')"))
        self.assertEqual(got["D"], ("5", "(blank)", "(cleared -- SaraPlus shows 0 units)"))
        self.assertEqual(got["F"], ("1", "3", ""))


class TargetDayTest(unittest.TestCase):
    def test_before_ten_closes_yesterday_after_ten_fills_today(self):
        tz = run.TZ
        self.assertEqual(run.target_day(dt.datetime(2026, 10, 23, 5, 0, tzinfo=tz)),
                         dt.date(2026, 10, 22))
        self.assertEqual(run.target_day(dt.datetime(2026, 10, 23, 9, 59, tzinfo=tz)),
                         dt.date(2026, 10, 22))
        self.assertEqual(run.target_day(dt.datetime(2026, 10, 23, 10, 0, tzinfo=tz)),
                         dt.date(2026, 10, 23))
        self.assertEqual(run.target_day(dt.datetime(2026, 10, 23, 21, 0, tzinfo=tz)),
                         dt.date(2026, 10, 23))


class _Ws:
    title = "NDS Sales Board"

    def __init__(self):
        self.updates = []

    def batch_update(self, body):
        self.updates.append(body)


class MainTest(unittest.TestCase):
    """End to end on fakes: the relay reader, the office lookup and the board
    reader are the only seams, and each is a module function."""

    SALES = {"NICHOLAS SMEDRA": nds(nl=4), "JACOB ISAIAH ORTEGA": nds(nl=2, up=4),
             "GHOST REP": nds(nl=1), "DIEGO JAVIER DEL POZO BORRES": nds(dtv=2)}

    def _run(self, argv, rows, board=None):
        ws = _Ws()
        g = board if board is not None else [list(r) for r in BOARD]
        out = io.StringIO()
        with mock.patch.object(run, "relay_rows", return_value=rows), \
             mock.patch.object(run, "office_campaign", side_effect=lookup), \
             mock.patch.object(run, "load_board", return_value=(ws, g)), \
             contextlib.redirect_stdout(out):
            rc = run.main(argv)
        return rc, out.getvalue(), ws

    def rows(self):
        return [(2, relay_row("carlos", {"X": nds(nl=9)}, "10/23/2026 15:00:00")),
                (3, relay_row("carlos-b2batt", {"NICHOLAS SMEDRA": nds(nl=1)},
                              "10/23/2026 11:00:00")),
                (4, relay_row("carlos-b2batt", self.SALES, "10/23/2026 15:10:00"))]

    def test_no_relay_holds_75_with_the_mini_line(self):
        rc, out, ws = self._run(["--date", "2026-10-23", "--fill", "--yes"], [])
        self.assertEqual(rc, 75)
        self.assertIn("no relay for 2026-10-23 -- the office mini may be off", out)
        self.assertEqual(ws.updates, [])

    def test_probe_never_writes_and_never_holds(self):
        rc, out, ws = self._run(["--date", "2026-10-23", "--probe", "--fill", "--yes"],
                                self.rows())
        self.assertEqual(rc, 0)
        self.assertEqual(ws.updates, [])
        self.assertIn("relayed at 10/23 15:10:00", out)       # the newest row
        self.assertIn("carlos (b2b_box)", out)                 # who else relayed
        self.assertIn("NICHOLAS SMEDRA", out)
        self.assertIn("Up 4", out)                             # Jacob's upgrades, shown
        self.assertIn("DTV 2", out)                            # Diego's DTV, shown
        self.assertIn("board column for Friday 10/23", out)
        self.assertIn("PROBE -- nothing written", out)
        rc, out, ws = self._run(["--date", "2026-10-23", "--probe"], [])
        self.assertEqual(rc, 0)
        self.assertIn("mini may be off", out)

    def test_dry_report_writes_nothing(self):
        rc, out, ws = self._run(["--date", "2026-10-23"], self.rows())
        self.assertEqual(rc, 0)
        self.assertEqual(ws.updates, [])
        self.assertIn("DRY REPORT", out)

    def test_fill_plans_and_yes_writes(self):
        rc, out, ws = self._run(["--date", "2026-10-23", "--fill"], self.rows())
        self.assertEqual((rc, ws.updates), (0, []))
        self.assertIn("DRY RUN", out)
        rc, out, ws = self._run(["--date", "2026-10-23", "--fill", "--yes"], self.rows())
        self.assertEqual(rc, 0)
        self.assertEqual(ws.updates, [[
            {"range": "I9", "values": [[""]]},     # Diego 4 -> blank (DTV only)
            {"range": "I10", "values": [[2]]},     # Jacob X -> 2
            {"range": "I6", "values": [[4]]},      # Nick 2 -> 4
        ]])
        self.assertIn("GHOST REP (1) but no B2B row", out)
        self.assertIn("wrote 3 cell(s)", out)

    def test_dry_flag_beats_fill_yes(self):
        rc, out, ws = self._run(["--date", "2026-10-23", "--fill", "--yes", "--dry"],
                                self.rows())
        self.assertEqual((rc, ws.updates), (0, []))

    def test_wrong_week_holds(self):
        g = grid({"Nick Smedra": "2"}, we="10.18")
        rc, out, ws = self._run(["--date", "2026-10-23", "--fill", "--yes"],
                                self.rows(), board=g)
        self.assertEqual(rc, 75)
        self.assertIn("WRONG WEEK", out)
        self.assertIn("HELD DAY: 2026-10-23", out)
        self.assertEqual(ws.updates, [])

    def test_a_day_with_no_column_holds(self):
        g = grid({"Nick Smedra": "2"})
        g[3][FRI - 1] = ""                                 # Friday header gone
        rc, out, ws = self._run(["--date", "2026-10-23", "--fill", "--yes"],
                                self.rows(), board=g)
        self.assertEqual(rc, 75)
        self.assertIn("no column for Friday", out)

    def test_pinned_office_of_the_wrong_campaign_holds(self):
        rc, out, ws = self._run(["--date", "2026-10-23", "--office", "carlos", "--fill",
                                 "--yes"], self.rows())
        self.assertEqual(rc, 75)
        self.assertIn("'b2b_box'", out)
        self.assertEqual(ws.updates, [])


if __name__ == "__main__":
    unittest.main()
