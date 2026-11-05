import datetime as dt
import unittest
from unittest import mock

from automations.second_round_contacts import config as C
from automations.second_round_contacts import contacts as K
from automations.second_round_contacts import roster as R
from automations.second_round_contacts import rules
from automations.second_round_contacts import state as S
from automations.second_round_contacts import run as RUN
from automations.second_round_contacts.run import plan_adds

T = dt.date(2026, 10, 31)


def ent(sr="2026-10-20", status=S.TRACKED):
    return {"second_round": sr, "status": status, "first_name": "Ana", "last_name": "Lopez"}


class Rules(unittest.TestCase):
    def test_under_a_week_waits(self):
        self.assertEqual(rules.decide(ent("2026-10-28"), {}, T)[0], rules.WAIT)

    def test_not_hired_after_a_week_is_removed(self):
        v, why = rules.decide(ent("2026-10-20"), {}, T)
        self.assertEqual(v, rules.DELETE)
        self.assertIn("not hired", why)

    def test_scheduled_start_waits_then_removed_at_three_weeks(self):
        f = {"bob": dt.date(2026, 10, 20)}
        self.assertEqual(rules.decide(ent(), f, T)[0], rules.WAIT)
        self.assertEqual(rules.decide(ent(), f, dt.date(2026, 11, 10))[0], rules.DELETE)

    def test_showed_and_badged_graduates(self):
        f = {"ns_showed": dt.date(2026, 10, 27), "progress": 100}
        self.assertEqual(rules.decide(ent(), f, T)[0], rules.HIRED)

    def test_showed_not_badged_waits_then_removed(self):
        f = {"ns_showed": dt.date(2026, 10, 27), "progress": 60}
        self.assertEqual(rules.decide(ent(), f, T)[0], rules.WAIT)
        v, why = rules.decide(ent(), f, dt.date(2026, 11, 20))
        self.assertEqual(v, rules.DELETE)
        self.assertIn("never fully badged", why)

    def test_unreadable_progress_never_removes(self):
        f = {"ns_showed": dt.date(2026, 9, 1), "progress": None}
        self.assertEqual(rules.decide(ent(), f, T)[0], rules.WAIT)

    def test_hired_is_kept_forever(self):
        self.assertEqual(rules.decide(ent(status=S.HIRED), {}, dt.date(2027, 6, 1))[0], rules.KEEP)


class Roster(unittest.TestCase):
    def test_parse_rows(self):
        vals = [C.ROSTER_HEADERS,
                ["Omar Perez", "11280", "OmarReception@gmail.com", "Yes", "", "10/27/2026", "", "", ""],
                ["Someone", "", "x@y.com", "Yes", "", "", "", "", ""],
                ["Shaylee Miller", "office 24226", "shaylee.rec@gmail.com", "No", "RES-FIBER", "", "note", "", ""]]
        rows = R.parse_rows(vals)
        self.assertEqual([r.owner for r in rows], ["Omar Perez", "Shaylee Miller"])
        o = rows[0]
        self.assertEqual((o.office, o.account, o.active, o.ov_campaign, o.start),
                         ("11280", "omarreception@gmail.com", True, C.DEFAULT_OV_CAMPAIGN, dt.date(2026, 10, 27)))
        self.assertEqual((rows[1].office, rows[1].active, rows[1].ov_campaign), ("24226", False, "RES-FIBER"))

    def test_headers_in_any_order(self):
        vals = [["Reception Email", "Owner", "Active", "ApplicantStream Office ID"],
                ["a@b.com", "X Y", "yes", "123"]]
        self.assertEqual(R.parse_rows(vals)[0].office, "123")


class TwoOffices(unittest.TestCase):
    """Omar 2026-11-05: his own funnel is 24232, the first run read Raf's 24153."""

    A = {"first_name": "Ana", "last_name": "Lopez", "phone": "2145550101", "email": ""}

    def owner(self, cell="24232, 24153"):
        return R.parse_rows([C.ROSTER_HEADERS, ["Omar", cell, "r@x.com", "Yes", "", "", "", "", ""]])[0]

    def test_new_office_first_old_still_read(self):
        o = self.owner()
        self.assertEqual((o.office, o.offices), ("24232", ["24232", "24153"]))
        self.assertEqual(self.owner("24153").offices, ["24153"])

    def test_adds_keep_the_office_that_could_be_read(self):
        from automations.applicant_tracker.applicantstream import OfficeNotAvailable

        def fake(_app, office, _labels, _days):
            if office == "24232":
                raise OfficeNotAvailable("no")
            return [(C.LABEL_BOOKED, T, self.A)]
        with mock.patch.object(RUN, "read_lists", fake):
            found, errors = RUN.read_offices(None, ["24232", "24153"], C.ADD_LABELS, [T])
        self.assertEqual(len(found), 1)
        self.assertEqual(errors, ["office 24232 not available"])

    def test_audit_merges_offices_earliest_date(self):
        key = S.key_for(self.A)
        by_office = {"24232": [(C.LABEL_OFFERED, dt.date(2026, 11, 4), self.A)],
                     "24153": [(C.LABEL_OFFERED, dt.date(2026, 11, 2), self.A)]}
        with mock.patch.object(RUN, "read_lists", lambda _a, office, _l, _d: by_office[office]):
            facts = RUN.gather_facts(None, ["24232", "24153"], {key}, T)
        self.assertEqual(facts[key]["offered"], dt.date(2026, 11, 2))

    def test_audit_refuses_to_decide_on_an_unread_office(self):
        def fake(_a, office, _l, _d):
            if office == "24153":
                raise RuntimeError("down")
            return []
        with mock.patch.object(RUN, "read_lists", fake):
            with self.assertRaises(RuntimeError):
                RUN.gather_facts(None, ["24232", "24153"], {"p:1"}, T)

    def test_contacts_from_an_office_off_the_row_are_kept_not_audited(self):
        entries = {"p:1": {"office": "24153", "status": S.TRACKED},
                   "p:2": {"office": "24232", "status": S.TRACKED},
                   "p:3": {"office": "24153", "status": S.REMOVED}}
        self.assertEqual(RUN.from_old_office(self.owner("24232"), entries), {"p:1"})
        self.assertEqual(RUN.from_old_office(self.owner("24232, 24153"), entries), set())


class Contacts(unittest.TestCase):
    def test_display_and_note(self):
        a = {"first_name": "Ana", "last_name": "Lopez", "phone": "2145550101"}
        self.assertEqual(K.display_name(a, dt.date(2026, 10, 31)), "Ana Lopez (2R 10/31)")
        self.assertIn("AppStream 11280", K.note_for("Omar", "11280", dt.date(2026, 10, 31)))

    def test_state_key_prefers_phone(self):
        self.assertEqual(S.key_for({"phone": "(214) 555-0101", "email": "a@b.com"}), "p:2145550101")
        self.assertEqual(S.key_for({"email": "A@B.com"}), "e:a@b.com")


class Planning(unittest.TestCase):
    def test_earliest_day_wins_and_existing_skipped(self):
        a = {"first_name": "Ana", "last_name": "Lopez", "phone": "2145550101", "email": ""}
        b = {"first_name": "Bo", "last_name": "Diaz", "phone": "", "email": "bo@x.com"}
        found = [(C.LABEL_HELD, dt.date(2026, 10, 30), a), (C.LABEL_BOOKED, dt.date(2026, 10, 28), a),
                 (C.LABEL_BOOKED, dt.date(2026, 10, 29), b)]
        rows = plan_adds(found, {"2145550101": "Ana Lopez"}, {})
        by = {r["applicant"]["first_name"]: r for r in rows}
        self.assertEqual(by["Ana"]["status"], "exists")
        self.assertEqual(by["Bo"]["status"], "add")
        self.assertEqual(by["Bo"]["day"], dt.date(2026, 10, 29))
        self.assertEqual(by["Ana"]["day"], dt.date(2026, 10, 28))


if __name__ == "__main__":
    unittest.main()
