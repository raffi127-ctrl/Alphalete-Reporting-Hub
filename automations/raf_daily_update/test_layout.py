"""python -m unittest automations.raf_daily_update.test_layout"""
import datetime as dt
import unittest

from automations.raf_daily_update import layout as L

D = dt.date(2026, 10, 13)
HDR = ["Date", "1st round Interviewer", "2nd Round Interviewer", "First Name",
       "Last Name", "Phone Number", "Status", "BOB \nDate", "Time Slot",
       "Email", "SHOWED TO DAY 1", "Ad applied to",
       "Owner Liked the applicant Yes or No", "", "", "MONTHLY TOTALS"]


def cand(first, show="Showed", offered="Y", bob="", orient="", second="Hank Tran"):
    return {"day": D, "first": first, "last": "X", "name": f"{first} X",
            "email": "", "phone": "(214) 555-0101", "first_round": "",
            "second_round": second, "ad": "", "show": show,
            "offered": offered, "bob_status": bob, "orientation": orient}


class Layout(unittest.TestCase):
    def test_resolve_stops_at_totals(self):
        lay = L.resolve(HDR)
        self.assertEqual(lay["bob_date"], 7)
        self.assertEqual(lay["ad"], 11)
        self.assertNotIn("monthly", str(lay))

    def test_month_tab_spacing_and_typo(self):
        titles = ["October -2026", "Febuary-2026", "Template"]
        self.assertEqual(L.month_tab(titles, D), "October -2026")
        self.assertEqual(L.month_tab(titles, dt.date(2026, 2, 3)), "Febuary-2026")
        self.assertIsNone(L.month_tab(titles, dt.date(2026, 11, 1)))

    def test_status_wording(self):
        self.assertEqual(L.status_for(cand("a", show="No Show", offered="")), L.NO_SHOW)
        self.assertEqual(L.status_for(cand("a", offered="N")), L.LEADER_NO)
        self.assertEqual(L.status_for(cand("a", bob="BOB")), L.BOB)
        self.assertEqual(L.status_for(cand("a", bob="Letting us know")), L.LETTING)
        self.assertEqual(L.status_for(cand("a")), L.TO_CALL)

    def test_owner_liked_is_the_offer_not_the_acceptance(self):
        # the November tab's own wording: a leader saying no is the only No
        self.assertEqual(L.owner_liked_for(cand("a", offered="N")), "No")
        self.assertEqual(L.owner_liked_for(cand("a", bob="Declined")), "Yes")
        self.assertEqual(L.owner_liked_for(cand("a", bob="BOB")), "Yes")
        self.assertEqual(L.owner_liked_for(cand("a", bob="LM")), "Yes")
        # a no-show: nobody formed an opinion, so the cell stays empty
        self.assertEqual(
            L.owner_liked_for(cand("a", show="No Show", offered="")), "")

    def test_the_run_writes_owner_liked_and_leaves_day1_alone(self):
        self.assertIn("owner_liked", L.WRITE_KEYS)
        self.assertIn("ad", L.WRITE_KEYS)
        self.assertIn("int1", L.WRITE_KEYS)
        # SHOWED TO DAY 1 is decided on the start day — day1.py fills it
        self.assertNotIn("day1", L.WRITE_KEYS)
        self.assertEqual(L.build_rows([cand("a", bob="BOB")])[0]["owner_liked"],
                         "Yes")

    def test_order_matches_recruiters(self):
        rows = L.build_rows([cand("lm", bob="LM"), cand("ns", show="No Show"),
                             cand("no", offered="N"), cand("dec", bob="Declined"),
                             cand("bob", bob="BOB", orient="10/19/2026 1:00 PM")])
        self.assertEqual([r["first"] for r in rows],
                         ["bob", "dec", "no", "lm", "ns"])
        self.assertEqual((rows[0]["bob_date"], rows[0]["time"]), ("10/19", "1:00"))
        self.assertEqual(rows[0]["phone"], "12145550101")
        self.assertEqual(rows[0]["date"], "10/13/26")
        self.assertEqual(L.split_orientation("Oct 19")[0], "10/19")

    def test_rerun_appends_nothing_twice(self):
        rows = L.build_rows([cand("a"), cand("b")])
        have = [L.person_key(D, "A", "x")]
        self.assertEqual([r["first"] for r in L.new_rows(rows, have)], ["b"])

    def test_tags_group_by_leader(self):
        rows = L.build_rows([cand("a", bob="BOB", orient="10/19"),
                             cand("b", bob="BOB", second="Bill Hirwa"),
                             cand("c", offered="N")])
        t = L.tag_text(rows, {"hank tran": "U1"})
        self.assertIn("<@U1>: a X (starts 10/19)", t)
        self.assertIn("*Bill Hirwa*: b X", t)
        self.assertNotIn("c X", t)
        self.assertEqual(L.tag_text(L.build_rows([cand("c", offered="N")]), {}), "")

    def test_untaggable_leader_goes_to_helpers(self):
        rows = L.build_rows([cand("a", bob="BOB"),
                             cand("b", bob="BOB", second="Bill Hirwa")])
        t = L.tag_text(rows, {"hank tran": "U1"}, helpers=["UA", "UR"])
        self.assertIn("<@UA> <@UR>", t)
        self.assertIn("couldn\u2019t tag *Bill Hirwa*", t)
        self.assertNotIn("*Hank Tran*", t.split("\n")[-1])
        self.assertNotIn("<@UA>", L.tag_text(rows, {"hank tran": "U1",
                                                     "bill hirwa": "U2"},
                                              helpers=["UA"]))


if __name__ == "__main__":
    unittest.main()
