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

    def test_the_run_writes_what_it_should_and_leaves_day1_alone(self):
        self.assertIn("ad", L.WRITE_KEYS)
        self.assertIn("int1", L.WRITE_KEYS)
        self.assertIn("next_step", L.WRITE_KEYS)
        # SHOWED TO DAY 1 is decided on the start day -- day1.py fills it
        self.assertNotIn("day1", L.WRITE_KEYS)
        # Owner Liked is not ours to write (Megan 2026-11-21): the new OBCL
        # does not carry it, so nothing derives it any more.
        self.assertNotIn("owner_liked", L.WRITE_KEYS)

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


class NextStep(unittest.TestCase):
    """Megan 2026-11-20: every 2nd round on the update, and what's next."""

    def test_only_two_statuses_are_still_somebody_s_move(self):
        owed = {s for s in L.ORDER
                if L.next_step(s).startswith("Call")}
        self.assertEqual(owed, {L.LM, L.TO_CALL})

    def test_a_bob_says_when_they_start(self):
        self.assertEqual(L.next_step(L.BOB, "11/23"), "Starts 11/23")

    def test_a_bob_with_no_date_says_so_rather_than_nothing(self):
        self.assertEqual(L.next_step(L.BOB, ""), "Starts - date not set")

    def test_the_reason_after_the_colon_does_not_break_the_match(self):
        self.assertEqual(L.next_step("Leader said no: issues with schedule"),
                         "Closed - leader said no")
        self.assertEqual(L.next_step("Declined - going to keep interviewing"),
                         "Closed - they declined")

    def test_nothing_is_left_blank(self):
        """A blank cell reads as 'nobody has looked at this', which is the
        opposite of what BOB or Declined means."""
        for s in L.ORDER:
            self.assertTrue(L.next_step(s, "11/23"), "%r said nothing" % s)

    def test_it_is_written_and_found_by_header(self):
        self.assertIn("next_step", L.WRITE_KEYS)
        # It has to sit BEFORE the blank spacer: resolve stops at the first
        # empty header, because everything right of it is MONTHLY TOTALS.
        at = HDR.index("")
        head = HDR[:at] + ["Next Step"] + HDR[at:]
        self.assertEqual(L.resolve(head)["next_step"], at)

    def test_a_column_added_past_the_spacer_is_not_seen(self):
        """The constraint, written down: a header after the blank is in the
        MONTHLY TOTALS block and resolve never reaches it."""
        self.assertNotIn("next_step", L.resolve(HDR + ["Next Step"]))

    def test_build_rows_fills_it(self):
        row = L.build_rows([cand("a", bob="BOB", orient="11/23/2026 1:00 PM")])[0]
        self.assertEqual(row["next_step"], "Starts 11/23")
