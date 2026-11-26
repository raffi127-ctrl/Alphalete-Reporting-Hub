"""Indeed billing holds: the office check's rows become 'Billing Holds' rows
and a back-live note. Faked book, tab and DM; a temp state file."""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import billing_holds as BH
from automations.icd_alerts import post as P


def _row(day, at, billing, mail=None, office="11580"):
    body = {"office": office, "date": day, "at": at, "billing": billing, "billing_mail": mail or {}}
    r = [""] * (P.F_POSTED + 1)
    r[P.F_OFFICE], r[P.F_DAY], r[P.F_STAGE], r[P.F_SUMMARY], r[P.F_DETAIL] = "carlos", day, BH.STAGE, "octo lookup", json.dumps(body)
    return r


class FakeTab:
    def __init__(self, rows=None):
        self.rows = [BH.HOLDS_HEAD] + list(rows or [])
    def get_all_values(self):
        return [list(r) for r in self.rows]
    def append_row(self, row, value_input_option=None):
        self.rows.append(list(row))
    def get(self, a1):
        col, r = a1[0], int(a1[1:])
        return [[self.rows[r - 1][ord(col) - 65]]]
    def update(self, a1, values, value_input_option=None):
        r = int(a1.split(":")[0][1:])
        self.rows[r - 1][2:4] = values[0]


class FakeBook:
    def __init__(self, faults):
        self._faults = faults
    def worksheet(self, name):
        if name == P.FAULTS_TAB:
            return mock.Mock(get_all_values=lambda: [["h"] * 12] + self._faults)
        raise KeyError(name)


class FakeDash:
    def __init__(self, tab):
        self.tab = tab
    def worksheet(self, name):
        if name == BH.HOLDS_TAB:
            return self.tab
        raise KeyError(name)


class HoldsTest(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.p = mock.patch.object(BH, "STATE_PATH", d / "state.json")
        self.p.start(); self.addCleanup(self.p.stop)

    def test_a_hold_opens_from_the_mail_and_closes_with_a_note(self):
        tab = FakeTab()
        dms = []
        day = "2026-11-19"
        faults = [_row(day, "05:00", {"Peak Sales Strategies": "PROBLEM: Action required", "W Edge": "ok"},
                       {"Peak Sales Strategies": {"declined": "2026-11-18 19:05", "signed_in": True}})]
        did = BH.run(dt.date(2026, 11, 19), send=True, book=FakeBook(faults), dash=FakeDash(tab), dm=lambda k, t: dms.append((k, t)), log=lambda m: None)
        self.assertEqual([(a["event"], a["account"]) for a in did], [("hold", "Peak Sales Strategies")])
        self.assertEqual(tab.rows[1][:3], ["Peak Sales Strategies", "11/18/2026 19:05", ""])
        self.assertEqual(dms, [])
        # the same row again: nothing new (handled)
        self.assertEqual(BH.run(dt.date(2026, 11, 19), send=True, book=FakeBook(faults), dash=FakeDash(tab), dm=lambda k, t: dms.append((k, t)), log=lambda m: None), [])
        # the 1pm check: clean again, with the payment mail
        faults.append(_row(day, "13:02", {"Peak Sales Strategies": "ok", "W Edge": "ok"},
                           {"Peak Sales Strategies": {"declined": "2026-11-18 19:05", "paid": "2026-11-19 12:41", "signed_in": True}}))
        did = BH.run(dt.date(2026, 11, 19), send=True, book=FakeBook(faults), dash=FakeDash(tab), dm=lambda k, t: dms.append((k, t)), log=lambda m: None)
        self.assertEqual([(a["event"], a["account"], a["end"]) for a in did], [("live", "Peak Sales Strategies", "2026-11-19T12:41")])
        self.assertEqual(tab.rows[1][2], "11/19/2026 12:41")
        self.assertEqual(len(dms), 1)
        self.assertEqual(dms[0][0], "carlos")
        self.assertIn("back live", dms[0][1]); self.assertIn("Peak Sales Strategies", dms[0][1]); self.assertIn("18 hours", dms[0][1])

    def test_a_hand_typed_open_row_is_reused_and_the_check_time_is_the_fallback(self):
        tab = FakeTab([["Ascendra", "11/18/2026 19:12", "", "typed by hand"]])
        faults = [_row("2026-11-19", "05:00", {"New Ascendra": "PROBLEM: x", "Kinetic Marketing Partners": "PROBLEM: y"},
                       {"New Ascendra": {"signed_in": False}})]
        did = BH.run(dt.date(2026, 11, 19), send=True, book=FakeBook(faults), dash=FakeDash(tab), dm=lambda k, t: None, log=lambda m: None)
        self.assertEqual(len(tab.rows), 3, "Ascendra's hand row reused, Kinetic added")
        self.assertEqual(tab.rows[2][0], "Kinetic Marketing Partners")
        self.assertEqual(tab.rows[2][1], "11/19/2026 05:00")
        self.assertTrue(any("estimated" in a["source"] for a in did if a["account"] == "Kinetic Marketing Partners"))

    def test_walled_or_in_use_moves_nothing_and_preview_writes_nothing(self):
        tab = FakeTab()
        faults = [_row("2026-11-19", "05:00", {"Peak Sales Strategies": "walled", "W Edge": "in use on another computer"})]
        did = BH.run(dt.date(2026, 11, 19), send=True, book=FakeBook(faults), dash=FakeDash(tab), dm=lambda k, t: None, log=lambda m: None)
        self.assertEqual(did, []); self.assertEqual(len(tab.rows), 1)
        faults = [_row("2026-11-19", "13:00", {"Peak Sales Strategies": "PROBLEM: x"})]
        did = BH.run(dt.date(2026, 11, 19), send=False, book=FakeBook(faults), dash=FakeDash(tab), dm=lambda k, t: None, log=lambda m: None)
        self.assertEqual(len(did), 1); self.assertEqual(len(tab.rows), 1, "preview writes nothing")

    def test_a_second_episode_never_reuses_the_old_decline_mail_or_overlaps(self):
        """Ascendra, 11/20-11/21: back live at the 5am check, flagged again a day
        later with Indeed's old 11/18 decline mail still the newest -- the hold
        must start at the check that saw it flagged again, after the previous
        hold's end, never at the old mail."""
        tab = FakeTab([["Ascendra", "11/18/2026 19:12", "11/20/2026 05:00", "first episode"]])
        mail = {"New Ascendra": {"declined": "2026-11-18 19:12", "signed_in": True}}
        faults = [_row("2026-11-20", "05:00", {"New Ascendra": "ok"}, mail),
                  _row("2026-11-20", "13:01", {"New Ascendra": "ok"}, mail),
                  _row("2026-11-21", "05:00", {"New Ascendra": "PROBLEM: x"}, mail)]
        did = []
        for d in ("2026-11-20", "2026-11-21"):
            did += BH.run(dt.date.fromisoformat(d), send=True, book=FakeBook(faults), dash=FakeDash(tab), dm=lambda k, t: None, log=lambda m: None)
        self.assertEqual([(a["event"], a["start"]) for a in did], [("hold", "2026-11-20T21:00")])
        self.assertEqual(len(tab.rows), 3)
        self.assertEqual(tab.rows[2][:3], ["Ascendra", "11/20/2026 21:00", ""])
        self.assertIn("estimated", did[0]["source"])

    def test_a_tally_cut_by_the_relay_still_reads(self):
        hit = "PROBLEM: Action required for your AT&T Wireless Associate (Spanish Required) job"
        billing = {"Acct %02d" % i: (hit if i % 2 else "ok") for i in range(17)}
        mail = {"Acct %02d" % i: {"signed_in": True, "declined": "2026-11-24 14:0%d" % (i % 10),
                                  "paid": "2026-11-16 19:00", "live": "2026-11-0%d 11:01" % (i % 9 + 1),
                                  "note": "x" * 300} for i in range(17)}
        row = _row("2026-11-25", "17:32", billing, mail)
        full = row[P.F_DETAIL]
        self.assertGreater(len(full), 6000)
        row[P.F_DETAIL] = full[:6000]                      # relay._scrub keeps the first 6000
        got = BH.octo_rows(FakeBook([row]), dt.date(2026, 11, 25))
        self.assertEqual(len(got), 1)
        body = got[0]["body"]
        self.assertEqual(body["billing"], billing, "the statuses came before the cut and read whole")
        self.assertEqual(body["at"], "17:32")
        self.assertTrue(body.get("cut"))
        self.assertIn("Acct 00", body["billing_mail"])
        self.assertLess(len(body["billing_mail"]), 17, "the cut ones are left out, not guessed")
        self.assertEqual(BH._tolerant_json(full), json.loads(full), "an uncut row reads as before")
        # the cut inside the statuses themselves: the whole entries still read
        harsh = json.dumps({"office": "11580", "at": "05:00", "billing": {"A%02d" % i: hit * 3 for i in range(40)}})
        part = BH._tolerant_json(harsh[:6000])["billing"]
        self.assertTrue(0 < len(part) < 40, len(part))
        self.assertTrue(all(v == hit * 3 for v in part.values()))

    def test_the_poster_calls_it_inside_a_try(self):
        src = (Path(P.__file__)).read_text()
        i = src.index("billing_holds.run(day, send=args.send)")
        self.assertIn("try:", src[i - 150:i]); self.assertIn("except Exception", src[i:i + 150])


if __name__ == "__main__":
    unittest.main()
