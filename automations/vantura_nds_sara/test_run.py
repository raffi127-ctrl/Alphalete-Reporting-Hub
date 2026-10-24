"""The NDS Sales Board fill from SaraPlus -- relay or direct -- fakes only,
no network, no browser.

    python -m unittest automations.vantura_nds_sara.test_run -v

Carlos 2026-10-23: units are the real sales -- upgrades, tablets and
wearables never get added. The relay already keeps tablets, wearables and
upgrade lines out of NL (icd_alerts/relay._nds_lines); the direct read
derives the same dict off the two grids itself (metrics_from_grids). This
module adds Int + NL + Air and nothing else, picks the newest relay row of
the day, falls to the direct read when no nds enrolment relayed, holds when
neither source is there (naming both) or the Wireless labels are missing,
matches SaraPlus's caps names to the board's, keeps hand-typed markers unless
SaraPlus shows sales, and reuses Megan's overwrite rule.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import post as P
from automations.shared import saraplus as SP
from automations.vantura_nds_sara import config as CFG
from automations.vantura_nds_sara import run
from automations.vantura_slack_sales import run as R

DAY = dt.date(2026, 10, 23)                     # Friday, week ending 10.25
FRI = 9                                          # col I

# The Wireless grid's frozen-header labels (the 10/21 probe), as
# icd_alerts/test_nds_lines pins them: leading cells blank, measures right.
W_HEADERS = ["", "", "", "Records", "Credit Checked", "Credit Passed", "Sales",
             "Line Count", "New Lines", "Port Lines", "Upgrade Lines", "BYOD Lines",
             "Phones", "Tablets", "Wearables"]


def w_row(name, new=0, port=0, upg=0, tablets=0, wear=0, byod=0):
    """One Wireless-grid agent row, cells as the page gives them."""
    phones = new + port + upg - tablets - wear
    return ["", "5_Agent", name, "1", "1", "1", "1", str(new + port + upg), str(new),
            str(port), str(upg), str(byod), str(phones), str(tablets), str(wear)]


def att_row(name, internet=0, upgrades=0, aia=0, lines=0, marker="5_Agent"):
    """One AT&T-grid row at shared.saraplus.COL_ATT's fixed indices."""
    r = [""] * 16
    r[SP.COL_ROWTYPE] = marker
    r[SP.COL_ATT["name"]] = name
    r[SP.COL_ATT["internet_sales"]] = str(internet)
    r[SP.COL_ATT["internet_upgrades"]] = str(upgrades)
    r[SP.COL_ATT["aia_sales"]] = str(aia)
    r[SP.COL_ATT["wireless_lines_sold"]] = str(lines)
    return r


def agent(name, internet=0, upgrades=0, aia=0, lines=0):
    """A parse_att dict."""
    return {"name": name, "internet_sales": internet, "internet_upgrades": upgrades,
            "aia_sales": aia, "wireless_lines_sold": lines, "dtv_streaming": 0}


def lines_of(**reps):
    """{NAME: parse_lines dict} from name=(new, port, upg, tablets, wear)."""
    out = {}
    for name, (new, port, upg, tab, wear) in reps.items():
        out[name.replace("_", " ")] = {"New Lines": new, "Port Lines": port,
                                       "Upgrade Lines": upg, "Tablets": tab,
                                       "Wearables": wear}
    return out


def sara_read(att=(), lines=None, headers=W_HEADERS, shape_problem="", **kw):
    """What run.read_sara returns, minus the browser."""
    d = {"att": list(att), "lines": lines, "wireless_headers": list(headers),
         "att_rows": len(att) + 3, "wireless_rows": (len(lines) if lines else 0) + 3,
         "shape_problem": shape_problem,
         "read_at": dt.datetime(2026, 10, 23, 16, 2, 11, tzinfo=run.TZ),
         "timings": "AT&T 41s | Wireless 35s"}
    d.update(kw)
    return d


CREDS = {"email": "nds@example.com", "password": "s3cret-Pw-9"}
HAVE_CREDS = (CREDS, "creds file /nowhere/saraplus-nds-creds.json for nds@example.com", True)
NO_CREDS = (None, "no creds file at /nowhere/saraplus-nds-creds.json (and no "
                  "SARAPLUS_NDS_EMAIL / SARAPLUS_NDS_PASSWORD in the environment)", False)
BAD_CREDS = (None, "/nowhere/saraplus-nds-creds.json is not readable JSON (JSONDecodeError)", True)


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
    """End to end on fakes: the relay reader, the office lookup, the board
    reader, the login lookup and the browser read are the only seams, and
    each is a module function. The default fakes have NO login on the box, so
    every pre-existing relay test still runs the relay path alone."""

    SALES = {"NICHOLAS SMEDRA": nds(nl=4), "JACOB ISAIAH ORTEGA": nds(nl=2, up=4),
             "GHOST REP": nds(nl=1), "DIEGO JAVIER DEL POZO BORRES": nds(dtv=2)}

    def _run(self, argv, rows, board=None, creds=NO_CREDS, read=None, read_exc=None,
             enrolment=lookup):
        ws = _Ws()
        g = board if board is not None else [list(r) for r in BOARD]
        out = io.StringIO()
        self.relay_mock = mock.Mock(return_value=rows)
        self.read_mock = mock.Mock(side_effect=read_exc) if read_exc \
            else mock.Mock(return_value=read if read is not None else sara_read())
        with mock.patch.object(run, "relay_rows", self.relay_mock), \
             mock.patch.object(run, "office_campaign", side_effect=enrolment), \
             mock.patch.object(run, "load_board", return_value=(ws, g)), \
             mock.patch.object(CFG, "creds_status", return_value=creds), \
             mock.patch.object(run, "read_sara", self.read_mock), \
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
        # auto with no login either: the hold names BOTH missing sources.
        self.assertIn("no nds relay for the day", out)
        self.assertIn("no creds file at /nowhere/saraplus-nds-creds.json", out)
        self.assertEqual(ws.updates, [])
        self.assertEqual(self.read_mock.call_count, 0)

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

    # ---------------------------------------------------- the direct source --
    # The real situation of 2026-10-23: the mini relays as carlos-b2batt,
    # enrolled b2b_att, so there is no nds relay -- and the login is on the box.
    def att_relay(self):
        return [(2, relay_row("carlos-b2batt", {"NICHOLAS SMEDRA": nds(nl=6)},
                              "10/23/2026 15:10:00"))]

    READ = sara_read(
        att=[agent("NICHOLAS SMEDRA", lines=4),
             agent("JACOB ISAIAH ORTEGA", lines=11),
             agent("GHOST REP", lines=1),
             agent("DIEGO JAVIER DEL POZO BORRES")],
        lines=lines_of(NICHOLAS_SMEDRA=(4, 0, 0, 0, 0),
                       JACOB_ISAIAH_ORTEGA=(0, 7, 4, 0, 0),
                       GHOST_REP=(1, 0, 0, 0, 0)))

    def test_auto_uses_the_direct_read_when_no_nds_office_relayed(self):
        rc, out, ws = self._run(["--date", "2026-10-23", "--fill", "--yes"],
                                self.att_relay(), creds=HAVE_CREDS, read=self.READ,
                                enrolment=lambda k: "b2b_att")
        self.assertEqual(rc, 0)
        self.assertIn("no relay for 2026-10-23 -- the office mini may be off", out)
        self.assertIn("relayed: carlos-b2batt (b2b_att)", out)      # why not the relay
        self.assertIn("source: direct SaraPlus read", out)
        self.read_mock.assert_called_once_with(DAY, CREDS)
        self.assertEqual(ws.updates, [[
            {"range": "I9", "values": [[""]]},     # Diego on the grid with nothing -> blank
            {"range": "I10", "values": [[7]]},     # Jacob X -> 7 ported; 4 upgrade lines not
            {"range": "I6", "values": [[4]]},      # Nick 2 -> 4 new lines (NOT the relay's 6)
        ]])
        self.assertIn("GHOST REP (1) but no B2B row", out)
        self.assertIn("wrote 3 cell(s)", out)

    def test_auto_prefers_the_relay_when_an_nds_office_relayed(self):
        rc, out, ws = self._run(["--date", "2026-10-23", "--fill", "--yes"], self.rows(),
                                creds=HAVE_CREDS, read=self.READ)
        self.assertEqual(rc, 0)
        self.assertIn("source: relay -- carlos-b2batt relayed as 'nds'", out)
        self.assertEqual(self.read_mock.call_count, 0)
        self.assertEqual(ws.updates[0][2], {"range": "I6", "values": [[4]]})

    def test_direct_read_without_the_wireless_labels_holds(self):
        read = sara_read(att=[agent("NICHOLAS SMEDRA", internet=2, lines=9)], lines=None,
                         headers=["", "", "", "Records", "Line Count"])
        rc, out, ws = self._run(["--date", "2026-10-23", "--source", "sara", "--fill",
                                 "--yes"], [], creds=HAVE_CREDS, read=read)
        self.assertEqual(rc, 75)
        self.assertIn("HOLDING -- the Wireless grid has no New Lines / Port Lines", out)
        self.assertIn("raw line count would put the tablets", out)
        self.assertEqual(ws.updates, [])
        self.assertNotIn("Int 2", out)              # nothing derived, nothing described

    def test_direct_read_with_an_unreadable_sales_grid_holds(self):
        read = sara_read(att=[], lines={}, shape_problem="the sales grid is fully drawn "
                         "-- 1_Company, 2_Location -- but nothing is marked '5_Agent'.")
        rc, out, ws = self._run(["--date", "2026-10-23", "--source", "sara", "--fill",
                                 "--yes"], [], creds=HAVE_CREDS, read=read)
        self.assertEqual(rc, 75)
        self.assertIn("could not be read as rep rows, twice", out)
        self.assertEqual(ws.updates, [])

    def test_direct_read_failure_is_red_not_amber(self):
        rc, out, ws = self._run(["--date", "2026-10-23", "--source", "sara", "--fill",
                                 "--yes"], [], creds=HAVE_CREDS,
                                read_exc=SP.SaraError("SaraPlus login failed -- still on the login page"))
        self.assertEqual(rc, 1)
        self.assertIn("SaraPlus read FAILED -- SaraPlus login failed", out)
        self.assertIn("nothing written", out)
        self.assertEqual(ws.updates, [])

    def test_source_relay_pinned_never_reads_saraplus(self):
        rc, out, ws = self._run(["--date", "2026-10-23", "--source", "relay", "--fill",
                                 "--yes"], [], creds=HAVE_CREDS, read=self.READ)
        self.assertEqual(rc, 75)
        self.assertIn("--source relay never reads SaraPlus directly", out)
        self.assertEqual(self.read_mock.call_count, 0)
        self.assertEqual(ws.updates, [])

    def test_source_sara_pinned_never_reads_the_relay(self):
        rc, out, ws = self._run(["--date", "2026-10-23", "--source", "sara", "--fill",
                                 "--yes"], self.rows(), creds=HAVE_CREDS, read=self.READ)
        self.assertEqual(rc, 0)
        self.assertEqual(self.relay_mock.call_count, 0)
        self.assertNotIn("relayed as", out)
        self.assertIn("wrote 3 cell(s)", out)

    def test_source_sara_pinned_without_a_login_holds(self):
        rc, out, ws = self._run(["--date", "2026-10-23", "--source", "sara", "--fill",
                                 "--yes"], [], creds=NO_CREDS)
        self.assertEqual(rc, 75)
        self.assertIn("no creds file at /nowhere/saraplus-nds-creds.json", out)
        self.assertIn("--source sara never reads the relay", out)
        self.assertEqual(self.read_mock.call_count, 0)

    def test_an_unusable_login_file_fails_instead_of_holding(self):
        rc, out, ws = self._run(["--date", "2026-10-23", "--fill", "--yes"], [],
                                creds=BAD_CREDS)
        self.assertEqual(rc, 1)
        self.assertIn("login file is unusable", out)
        self.assertIn("not readable JSON", out)
        self.assertEqual(self.read_mock.call_count, 0)

    def test_probe_says_which_source_and_shows_both_grids_raw(self):
        rc, out, ws = self._run(["--date", "2026-10-23", "--source", "sara", "--probe",
                                 "--fill", "--yes"], [], creds=HAVE_CREDS, read=self.READ)
        self.assertEqual(rc, 0)
        self.assertEqual(ws.updates, [])
        self.assertIn("source: direct SaraPlus read -- creds file", out)
        self.assertIn("SaraPlus direct read for Friday 10/23 at 10/23 16:02:11", out)
        self.assertIn("AT&T grid (raw)", out)
        self.assertIn("Wireless grid (raw)", out)
        self.assertRegex(out, r"JACOB ISAIAH ORTEGA\s+0\s+0\s+0\s+11")   # raw AT&T row
        self.assertRegex(out, r"JACOB ISAIAH ORTEGA\s+0\s+7\s+4\s+0\s+0")  # raw Wireless row
        self.assertIn("Int 0 + NL 7   Up 4", out)                       # derived
        self.assertIn("passes: AT&T 41s | Wireless 35s", out)
        self.assertIn("board column for Friday 10/23", out)
        self.assertIn("PROBE -- nothing written", out)
        self.assertNotIn(CREDS["password"], out)

    def test_probe_on_a_held_direct_read_still_dumps_the_board(self):
        read = sara_read(att=[agent("NICHOLAS SMEDRA", lines=9)], lines=None, headers=[])
        rc, out, ws = self._run(["--date", "2026-10-23", "--source", "sara", "--probe"],
                                [], creds=HAVE_CREDS, read=read)
        self.assertEqual(rc, 0)
        self.assertIn("HOLDING -- the Wireless grid has no", out)
        self.assertIn("board column for Friday 10/23", out)
        self.assertEqual(ws.updates, [])

    def test_preflight_wins_over_everything_and_touches_nothing(self):
        with mock.patch.object(run, "preflight", return_value=1) as pf:
            rc, out, ws = self._run(["--preflight", "--fill", "--yes", "--date", "2026-10-23"],
                                    self.rows(), creds=HAVE_CREDS)
        self.assertEqual(rc, 1)
        pf.assert_called_once_with()
        self.assertEqual(self.relay_mock.call_count, 0)
        self.assertEqual(self.read_mock.call_count, 0)
        self.assertEqual(ws.updates, [])


class MetricsFromGridsTest(unittest.TestCase):
    """The direct read's per-rep dict must be the one the relay would send
    for an nds office -- same keys, same arithmetic, same floors."""

    def test_jacob_eleven_lines_seven_count(self):
        # Carlos 2026-10-22: "Jacob at 11 lines. Seven of those are ported,
        # four of those are upgrade lines." Plus one fiber sale.
        got = run.metrics_from_grids([agent("JACOB ISAIAH ORTEGA", internet=1, lines=11)],
                                     lines_of(JACOB_ISAIAH_ORTEGA=(0, 7, 4, 0, 0)))
        self.assertEqual(got, {"JACOB ISAIAH ORTEGA": {"Int": 1, "NL": 7, "Int Up": 4,
                                                       "Air": 0, "DTV": 0}})
        self.assertEqual(run.units_for(got)["JACOB ISAIAH ORTEGA"]["units"], 8)

    def test_int_is_internet_minus_upgrades_minus_aia_floored(self):
        got = run.metrics_from_grids([agent("A", internet=3, upgrades=1, aia=1)], {})
        self.assertEqual((got["A"]["Int"], got["A"]["Int Up"], got["A"]["Air"]), (1, 2, 1))
        got = run.metrics_from_grids([agent("B", internet=1, upgrades=1, aia=1)], {})
        self.assertEqual(got["B"]["Int"], 0)                     # floored, not -1
        self.assertEqual(run.units_for(got)["B"]["units"], 1)   # the Air still counts

    def test_nl_is_new_plus_port_minus_tablets_minus_wearables_floored(self):
        got = run.metrics_from_grids([], lines_of(ANA=(6, 0, 0, 1, 0)))
        self.assertEqual(got["ANA"]["NL"], 5)                    # 5 phones + 1 tablet
        got = run.metrics_from_grids([], lines_of(JUSTIN=(1, 1, 0, 0, 1)))
        self.assertEqual(got["JUSTIN"]["NL"], 1)                 # 1 phone + 1 watch
        got = run.metrics_from_grids([], lines_of(ODD=(1, 0, 0, 2, 0)))
        self.assertEqual(got["ODD"]["NL"], 0)                    # floored
        got = run.metrics_from_grids([], lines_of(BYOD=(0, 9, 0, 0, 0)))
        self.assertEqual(got["BYOD"]["NL"], 9)                   # BYOD is never taken off

    def test_wireless_only_rep_has_no_internet(self):
        got = run.metrics_from_grids([], lines_of(ONLY_LINES=(2, 1, 1, 0, 0)))
        self.assertEqual(got["ONLY LINES"], {"Int": 0, "Air": 0, "DTV": 0, "NL": 3,
                                             "Int Up": 1})

    def test_att_only_rep_has_zero_lines_never_the_raw_count(self):
        # SaraPlus says 6 lines sold; the Wireless grid has no row for him.
        # The relay's rule: a rep missing from the grid sold no lines.
        got = run.metrics_from_grids([agent("ONLY FIBER", internet=2, lines=6)], {})
        self.assertEqual(got["ONLY FIBER"]["NL"], 0)
        self.assertEqual(got["ONLY FIBER"]["Int"], 2)

    def test_lines_none_is_refused_not_papered_over(self):
        with self.assertRaises(ValueError):
            run.metrics_from_grids([agent("A", lines=5)], None)

    def test_names_are_keyed_like_the_relay(self):
        got = run.metrics_from_grids([agent("Jacob Isaiah Ortega (NDS01)- Alphalete", internet=1)],
                                     {"JACOB ISAIAH ORTEGA": {"New Lines": 1, "Port Lines": 0,
                                                              "Upgrade Lines": 0, "Tablets": 0,
                                                              "Wearables": 0}})
        self.assertEqual(list(got), ["JACOB ISAIAH ORTEGA"])
        self.assertEqual((got["JACOB ISAIAH ORTEGA"]["Int"], got["JACOB ISAIAH ORTEGA"]["NL"]),
                         (1, 1))
        self.assertEqual(run.metrics_from_grids([agent("")], {}), {})

    def test_a_rep_on_two_att_rows_is_summed(self):
        got = run.metrics_from_grids([agent("TWICE", internet=1), agent("TWICE", internet=2, aia=1)], {})
        self.assertEqual((got["TWICE"]["Int"], got["TWICE"]["Air"], got["TWICE"]["Int Up"]), (2, 1, 1))

    def test_through_the_real_parsers(self):
        att = SP.parse_att([att_row("JACOB ISAIAH ORTEGA", internet=1, lines=11),
                            att_row("Group", marker="4_Campaign")])
        lines = SP.parse_lines(W_HEADERS, [w_row("JACOB ISAIAH ORTEGA", port=7, upg=4),
                                           w_row("ANA GRIFFIN", new=6, tablets=1)])
        got = run.units_for(run.metrics_from_grids(att, lines))
        self.assertEqual(got["JACOB ISAIAH ORTEGA"]["units"], 8)
        self.assertEqual(got["ANA GRIFFIN"]["units"], 5)
        self.assertEqual(got["ANA GRIFFIN"]["Int"], 0)


class SaraProblemTest(unittest.TestCase):
    def test_missing_labels_hold_and_say_which(self):
        why = run.sara_problem(sara_read(lines=None, headers=["", "Records", "Line Count"]))
        self.assertIn("New Lines / Port Lines / Upgrade Lines / Tablets / Wearables", why)
        self.assertIn("headers read: Records, Line Count", why)
        self.assertIn("nothing is written", why)

    def test_shape_problem_holds(self):
        why = run.sara_problem(sara_read(lines={}, shape_problem="nothing is marked '5_Agent'"))
        self.assertIn("twice", why)
        self.assertIn("5_Agent", why)

    def test_a_clean_read_has_no_problem(self):
        self.assertEqual(run.sara_problem(sara_read(lines={})), "")
        self.assertEqual(run.sara_problem(sara_read(lines=lines_of(A=(1, 0, 0, 0, 0)))), "")


class ChooseSourceTest(unittest.TestCase):
    NO_RELAY = "no carlos* office enrolled as 'nds' relayed for this day -- relayed: carlos-b2batt (b2b_att)"
    NO_CREDS = "no creds file at /x/saraplus-nds-creds.json (and no ...)"

    def test_auto_relay_first(self):
        self.assertEqual(run.choose_source("auto", "carlos-nds", "", True, "creds file /x"),
                         ("relay", ""))
        self.assertEqual(run.choose_source("auto", "carlos-nds", "", False, self.NO_CREDS),
                         ("relay", ""))

    def test_auto_then_sara(self):
        self.assertEqual(run.choose_source("auto", None, self.NO_RELAY, True, "creds file /x"),
                         ("sara", ""))

    def test_auto_neither_names_both(self):
        src, why = run.choose_source("auto", None, self.NO_RELAY, False, self.NO_CREDS)
        self.assertIsNone(src)
        self.assertIn("no nds relay for the day (no carlos* office", why)
        self.assertIn("relayed: carlos-b2batt (b2b_att)", why)
        self.assertIn("no creds file at /x/saraplus-nds-creds.json", why)

    def test_pinned_relay(self):
        self.assertEqual(run.choose_source("relay", "k", "", True, "")[0], "relay")
        src, why = run.choose_source("relay", None, self.NO_RELAY, True, "creds file /x")
        self.assertIsNone(src)
        self.assertIn("never reads SaraPlus directly", why)
        self.assertNotIn("creds", why)

    def test_pinned_sara(self):
        self.assertEqual(run.choose_source("sara", "k", "", True, "")[0], "sara")
        src, why = run.choose_source("sara", "k", "", False, self.NO_CREDS)
        self.assertIsNone(src)
        self.assertIn("never reads the relay", why)
        self.assertIn("no creds file at", why)


class CredsStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "saraplus-nds-creds.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_names_the_path_both_env_names_and_the_command(self):
        cr, why, exists = CFG.creds_status(self.path, env={})
        self.assertIsNone(cr)
        self.assertFalse(exists)
        self.assertIn(str(self.path), why)
        self.assertIn("SARAPLUS_NDS_EMAIL / SARAPLUS_NDS_PASSWORD", why)
        self.assertIn('set_credentials --push "Lucy 2"', why)

    def test_environment_wins_and_is_never_echoed(self):
        self.path.write_text(json.dumps({"email": "file@x", "password": "file-pw"}))
        cr, why, _ = CFG.creds_status(self.path, env={"SARAPLUS_NDS_EMAIL": "env@x",
                                                      "SARAPLUS_NDS_PASSWORD": "env-pw"})
        self.assertEqual(cr, {"email": "env@x", "password": "env-pw"})
        self.assertIn("environment", why)
        self.assertNotIn("env-pw", why)

    def test_good_file(self):
        self.path.write_text(json.dumps({"email": " nds@x ", "password": "p w"}))
        cr, why, exists = CFG.creds_status(self.path, env={})
        self.assertEqual(cr, {"email": "nds@x", "password": "p w"})
        self.assertTrue(exists)
        self.assertIn("nds@x", why)
        self.assertNotIn("p w", why)

    def test_bad_json_and_missing_keys_exist_but_are_unusable(self):
        self.path.write_text("{not json")
        cr, why, exists = CFG.creds_status(self.path, env={})
        self.assertEqual((cr, exists), (None, True))
        self.assertIn("not readable JSON", why)
        self.path.write_text(json.dumps({"email": "a@b"}))
        cr, why, exists = CFG.creds_status(self.path, env={})
        self.assertEqual((cr, exists), (None, True))
        self.assertIn("missing password", why)
        self.path.write_text(json.dumps(["a", "b"]))
        self.assertIsNone(CFG.creds_status(self.path, env={})[0])

    def test_paths_follow_home(self):
        with mock.patch.dict(os.environ, {"HOME": self.tmp.name}):
            self.assertEqual(CFG.creds_path(),
                             Path(self.tmp.name) / ".config" / "recruiting-report" / "saraplus-nds-creds.json")
            self.assertEqual(CFG.profile_dir().name, "saraplus-nds-profile")
            self.assertEqual(CFG.profile_dir().parent, CFG.creds_path().parent)
            with self.assertRaises(RuntimeError):
                CFG.creds()


class PreflightTest(unittest.TestCase):
    def preflight(self, patchright=(True, "1.55.0"), home=None, env=None):
        out = io.StringIO()
        env = dict(env or {})
        env["HOME"] = home or tempfile.mkdtemp()
        for k in (CFG.ENV_EMAIL, CFG.ENV_PASSWORD):
            env.setdefault(k, "")
        with mock.patch.object(run, "_patchright_status", return_value=patchright), \
             mock.patch.dict(os.environ, env, clear=False), \
             contextlib.redirect_stdout(out):
            rc = run.preflight()
        return rc, out.getvalue()

    def test_all_good(self):
        home = tempfile.mkdtemp()
        cdir = Path(home) / ".config" / "recruiting-report"
        cdir.mkdir(parents=True)
        (cdir / "saraplus-nds-creds.json").write_text(json.dumps(CREDS))
        (cdir / "saraplus-nds-profile").mkdir()
        rc, out = self.preflight(home=home)
        self.assertEqual(rc, 0)
        lines = [l for l in out.splitlines() if l.strip()]
        self.assertEqual(len(lines), 4)                              # and nothing else
        self.assertIn("patchright: ok (1.55.0)", out)
        self.assertIn("creds: ok -- creds file %s for nds@example.com" % (cdir / "saraplus-nds-creds.json"), out)
        self.assertIn("profile dir: %s (exists)" % (cdir / "saraplus-nds-profile"), out)
        self.assertIn("PREFLIGHT OK", out)
        self.assertNotIn(CREDS["password"], out)

    def test_missing_creds_fails(self):
        rc, out = self.preflight()
        self.assertEqual(rc, 1)
        self.assertIn("creds: MISSING -- no creds file at", out)
        self.assertIn("not yet -- created on the first login", out)
        self.assertIn("PREFLIGHT FAILED", out)

    def test_missing_patchright_fails_even_with_creds(self):
        home = tempfile.mkdtemp()
        cdir = Path(home) / ".config" / "recruiting-report"
        cdir.mkdir(parents=True)
        (cdir / "saraplus-nds-creds.json").write_text(json.dumps(CREDS))
        rc, out = self.preflight(patchright=(False, "ModuleNotFoundError: No module named 'patchright'"),
                                 home=home)
        self.assertEqual(rc, 1)
        self.assertIn("patchright: MISSING (ModuleNotFoundError", out)
        self.assertIn("creds: ok", out)

    def test_environment_login_counts(self):
        rc, out = self.preflight(env={CFG.ENV_EMAIL: "env@x", CFG.ENV_PASSWORD: "env-pw"})
        self.assertEqual(rc, 0)
        self.assertIn("login from the environment", out)
        self.assertNotIn("env-pw", out)


class _Ctx:
    def __init__(self, page=None):
        self.pages = [page] if page is not None else []
        self.closed = False

    def new_page(self):
        p = mock.Mock(name="page")
        self.pages.append(p)
        return p

    def close(self):
        self.closed = True


class LoginTest(unittest.TestCase):
    """login_healing is the login; the passcode wall is handed to
    rc_contact_sync.sara.login once, on the same profile."""

    def test_plain_login_is_the_shared_healing_login(self):
        ctx, page = _Ctx(), object()
        with mock.patch.object(SP, "login_healing", return_value=(ctx, page, "https://b/")) as lh:
            got = run._login("pw", "/prof", CREDS, log=lambda m: None)
        self.assertEqual(got, (ctx, page, "https://b/"))
        self.assertEqual(lh.call_args.args, ("pw", "/prof", "nds@example.com", "s3cret-Pw-9"))
        self.assertEqual(lh.call_args.kwargs["headless"], True)
        self.assertIn("saraplus-nds-creds.json", lh.call_args.kwargs["creds_hint"])

    def test_passcode_wall_is_answered_from_the_inbox_once(self):
        from automations.rc_contact_sync import sara as RC
        page = mock.Mock(name="page")
        ctx = _Ctx(page)
        said = []
        with mock.patch.object(SP, "login_healing", side_effect=SP.SaraPasscodeWall("wall")), \
             mock.patch.object(SP, "open_context", return_value=ctx) as oc, \
             mock.patch.object(RC, "login", return_value="https://www.saraplus.com/e/(S(x))/") as rl:
            got = run._login("pw", "/prof", CREDS, log=said.append)
        self.assertEqual(got, (ctx, page, "https://www.saraplus.com/e/(S(x))/"))
        oc.assert_called_once_with("pw", "/prof", headless=True)
        self.assertEqual(rl.call_args.args, (page, "nds@example.com", "s3cret-Pw-9"))
        self.assertTrue(any("emailed passcode" in m for m in said))
        self.assertTrue(any("trusted from here on" in m for m in said))
        self.assertFalse(ctx.closed)

    def test_wall_that_the_inbox_cannot_clear_raises_both_and_closes(self):
        from automations.rc_contact_sync import sara as RC
        ctx = _Ctx(mock.Mock(name="page"))
        with mock.patch.object(SP, "login_healing", side_effect=SP.SaraPasscodeWall("wall text")), \
             mock.patch.object(SP, "open_context", return_value=ctx), \
             mock.patch.object(RC, "login", side_effect=RuntimeError("no code arrived")):
            with self.assertRaises(SP.SaraPasscodeWall) as cm:
                run._login("pw", "/prof", CREDS, log=lambda m: None)
        self.assertIn("wall text", str(cm.exception))
        self.assertIn("RuntimeError: no code arrived", str(cm.exception))
        self.assertTrue(ctx.closed)

    def test_other_errors_pass_straight_through(self):
        with mock.patch.object(SP, "login_healing", side_effect=SP.SaraError("bounced")):
            with self.assertRaises(SP.SaraError):
                run._login("pw", "/prof", CREDS, log=lambda m: None)


class ReadSaraTest(unittest.TestCase):
    """read_sara's orchestration with the browser faked: two passes in one
    session, the sales grid re-read once when it looks half-rendered, the
    Wireless grid read by label, the context always closed."""

    GOOD_ATT = [att_row("Group", marker="4_Campaign"),
                att_row("JACOB ISAIAH ORTEGA", internet=1, lines=11)]
    HALF = [att_row("Acme", marker="1_Company"), att_row("Plano", marker="2_Location")]
    W_ROWS = [w_row("JACOB ISAIAH ORTEGA", port=7, upg=4)]

    def read(self, att_reads, headers=W_HEADERS, w_rows=None):
        page = mock.Mock(name="page")
        ctx = _Ctx(page)
        att_iter = iter(att_reads)

        def run_report(pg, base, day, service, grid, log=print):
            self.calls.append((service, grid, day, base))
            if service == "AT&T":
                return next(att_iter)
            return self.W_ROWS if w_rows is None else w_rows

        self.calls = []
        said = []
        with mock.patch("patchright.sync_api.sync_playwright") as sp, \
             mock.patch.object(run, "_login", return_value=(ctx, page, "https://b/")) as lg, \
             mock.patch.object(SP, "_run_report", side_effect=run_report), \
             mock.patch.object(SP, "grid_headers", return_value=list(headers)):
            sp.return_value.__enter__.return_value = "PW"
            out = run.read_sara(DAY, CREDS, profile_dir="/prof", log=said.append)
        self.ctx, self.login_call, self.said = ctx, lg.call_args, said
        return out

    def test_two_passes_one_session(self):
        out = self.read([self.GOOD_ATT])
        self.assertEqual([(s, g) for s, g, _d, _b in self.calls],
                         [("AT&T", SP.GRID_ATT), ("Wireless", SP.GRID_WIRELESS)])
        self.assertTrue(all(d == DAY and b == "https://b/" for _s, _g, d, b in self.calls))
        self.assertEqual(self.login_call.args, ("PW", "/prof", CREDS))
        self.assertEqual(out["att"], [agent("JACOB ISAIAH ORTEGA", internet=1, lines=11)])
        self.assertEqual(out["lines"], lines_of(JACOB_ISAIAH_ORTEGA=(0, 7, 4, 0, 0)))
        self.assertEqual((out["att_rows"], out["wireless_rows"], out["shape_problem"]), (2, 1, ""))
        self.assertEqual(out["wireless_headers"], W_HEADERS)
        self.assertIsNotNone(out["read_at"])
        self.assertTrue(self.ctx.closed)
        self.assertEqual(run.sara_problem(out), "")

    def test_half_rendered_sales_grid_is_read_again(self):
        out = self.read([self.HALF, self.GOOD_ATT])
        self.assertEqual([s for s, _g, _d, _b in self.calls], ["AT&T", "AT&T", "Wireless"])
        self.assertEqual(out["shape_problem"], "")
        self.assertEqual(len(out["att"]), 1)
        self.assertTrue(any("reading it again" in m for m in self.said))
        self.assertTrue(any("second read was fine" in m for m in self.said))

    def test_sales_grid_wrong_twice_is_a_shape_problem(self):
        out = self.read([self.HALF, self.HALF])
        self.assertIn("5_Agent", out["shape_problem"])
        self.assertEqual(out["att"], [])
        self.assertIn("could not be read as rep rows, twice", run.sara_problem(out))

    def test_missing_wireless_labels_come_back_as_none(self):
        out = self.read([self.GOOD_ATT], headers=["", "", "", "Records", "Line Count"])
        self.assertIsNone(out["lines"])
        self.assertTrue(any("labels were NOT found" in m for m in self.said))
        self.assertIn("headers read: Records, Line Count", run.sara_problem(out))
        with self.assertRaises(ValueError):
            run.metrics_from_grids(out["att"], out["lines"])

    def test_context_closes_when_a_pass_raises(self):
        page = mock.Mock(name="page")
        ctx = _Ctx(page)
        with mock.patch("patchright.sync_api.sync_playwright") as sp, \
             mock.patch.object(run, "_login", return_value=(ctx, page, "https://b/")), \
             mock.patch.object(SP, "_run_report", side_effect=SP.SaraError("the 'AT&T' report failed 3 times")):
            sp.return_value.__enter__.return_value = "PW"
            with self.assertRaises(SP.SaraError):
                run.read_sara(DAY, CREDS, profile_dir="/prof", log=lambda m: None)
        self.assertTrue(ctx.closed)


if __name__ == "__main__":
    unittest.main()
