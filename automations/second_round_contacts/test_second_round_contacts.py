import datetime as dt
import unittest

from automations.second_round_contacts import config as C
from automations.second_round_contacts import contacts as K
from automations.second_round_contacts import roster as R
from automations.second_round_contacts import rules
from automations.second_round_contacts import state as S
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
