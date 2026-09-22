"""python -m unittest automations.call_list_to_2nd.test_run"""
import datetime as dt
import unittest

from automations.call_list_to_2nd import run as r

EVE_HEADER = ["Owner Name", "Interviewer Name", "Sent to call list", "Retention Call list",
              "1st rds booked", "1st rds showed", "1st rd %", "2nd interviews booked",
              "2nd interviews showed", "2nd interview %"]
MON, TUE = dt.date(2026, 9, 14), dt.date(2026, 9, 15)


TODAY = dt.date(2026, 9, 21)
DAYS_ROW = ["9/20", "Monday", "", "", "", "", "", "Tuesday", "", "", "", "", "",
            "TOTAL for the WEEK"]
SUB_ROW = ["Interviewer", "B", "S", "NS", "RR", "C", "R", "B", "S", "NS", "RR", "C", "R",
           "2nd Rd Booked"]


def box(label, *people):
    rows = [[label] + DAYS_ROW[1:], SUB_ROW]
    for name, mon, tue in people:
        rows.append([name, str(mon[0]), str(mon[1]), "0", "0", "0", "", str(tue[0]),
                     str(tue[1]), "0", "0", "0", "", "x"])
    return rows


class SecondRoundBlock(unittest.TestCase):
    """The '2ND RD SHOWED RETENTION' block of an owner's ARS REPORT tab."""

    def test_reads_booked_and_showed_per_interviewer_per_day(self):
        vals = ([["2ND RD SHOWED RETENTION"], []]
                + box("9/20", ("Daniela", (11, 8), (12, 7)), ("Maria", (1, 1), (0, 0)))
                + [[]] + box("9/27", ("Daniela", (5, 2), (0, 0))))
        got = r.parse_second_block(vals, TODAY)
        # Box '9/20' is the week that ENDS Sunday 9/20: Monday 9/14.
        self.assertEqual(got[MON].by, {"Daniela": [11, 8], "Maria": [1, 1]})
        self.assertEqual((got[MON].booked, got[MON].showed), (12, 9))
        self.assertEqual(got[TUE].by, {"Daniela": [12, 7]})
        self.assertEqual(got[dt.date(2026, 9, 21)].by, {"Daniela": [5, 2]})
        self.assertEqual(got[TUE].interviewers, ["Daniela", "Maria"])

    def test_unnamed_totals_row_is_skipped(self):
        vals = box("9/20", ("Daniela", (3, 2), (0, 0))) + [["", "9", "9"]]
        self.assertEqual(r.parse_second_block(vals, TODAY)[MON].by, {"Daniela": [3, 2]})

    def test_label_year_is_the_nearest(self):
        self.assertEqual(r.label_week_end("9/27", TODAY), dt.date(2026, 9, 27))
        self.assertEqual(r.label_week_end("1/4", TODAY), dt.date(2027, 1, 4))
        self.assertIsNone(r.label_week_end("Interviewer", TODAY))


class Groups(unittest.TestCase):
    def test_one_row_per_interviewer_owner_numbers_on_the_first(self):
        sr = r.SecondRounds(booked=5, showed=2, by={"Maria": [1, 1], "Daniela": [4, 1]})
        g = r.make_group("Kash Rai", [], {"sent": 20, "b1": 10, "s1": 6}, sr)
        self.assertEqual([x["interviewer"] for x in g], ["Daniela", "Maria"])   # most booked first
        self.assertEqual(g[0]["sent"], 20)
        self.assertNotIn("sent", g[1])
        self.assertAlmostEqual(g[0]["r2"], 0.25)
        self.assertAlmostEqual(g[0]["r1"], 0.6)                                 # worked out

    def test_today_leaves_second_round_pct_blank(self):
        sr = r.SecondRounds(booked=10, showed=2, by={"Daniela": [10, 2]})
        self.assertIsNone(r.make_group("K", [], None, sr, is_today=True)[0]["r2"])

    def test_no_second_rounds_is_one_row_with_names(self):
        sr = r.SecondRounds(interviewers=["Ana", "Bo"])
        g = r.make_group("K", [], {"sent": 7}, sr)
        self.assertEqual(len(g), 1)
        self.assertEqual(g[0]["interviewer"], "Ana, Bo")

    def test_no_activity_is_dropped(self):
        self.assertIsNone(r.make_group("K", ["D"], {"sent": 0}, r.SecondRounds()))


class Layout(unittest.TestCase):
    def test_header_order_comes_from_the_tab(self):
        order = r.resolve_columns(EVE_HEADER)
        self.assertEqual(order[0], "owner")
        self.assertEqual(order[-1], "r2")
        with self.assertRaises(SystemExit):
            r.resolve_columns(EVE_HEADER[:-1])
        # After a run, row 3 also carries last week's copy: only the left block counts.
        self.assertEqual(r.resolve_columns(EVE_HEADER + [""] + EVE_HEADER), order)

    def _board(self):
        order = r.resolve_columns(EVE_HEADER)
        kash = [{"owner": "Kash Rai", "interviewer": "Daniela", "sent": 20, "b2": 11, "s2": 8,
                 "r2": 8 / 11},
                {"owner": "Kash Rai", "interviewer": "Maria", "b2": 4, "s2": 1, "r2": 0.25}]
        ana = [{"owner": "Ana", "interviewer": "Lu", "b2": 3, "s2": 3, "r2": 1.0}]
        weeks = [(dt.date(2026, 9, 20), {"Monday": [ana]}),
                 (dt.date(2026, 9, 13), {"Monday": [kash, ana]})]
        return order, weeks, r.lay_out(order, weeks, today=dt.date(2026, 9, 21))

    def test_days_line_up_and_groups_are_recorded(self):
        order, _, lay = self._board()
        tue = [b for b in lay.bands if b.text.startswith("TUESDAY")]
        self.assertEqual(tue[0].row, tue[1].row)            # same row on both sides
        self.assertIn((r.FIRST_BODY_ROW + 1, 2, 1), lay.groups)
        # The owner's cells are written once per group, left blank for the merge.
        right = len(order) + r.GAP_COLS
        self.assertEqual(lay.values[2][right], "")
        self.assertEqual(lay.values[2][right + 1], "Maria")
        self.assertFalse(any(b.text.startswith("SATURDAY") for b in lay.bands))

    def test_read_back_rebuilds_the_groups(self):
        order, _, lay = self._board()
        top = [[""] * (2 * len(order) + r.GAP_COLS)] * (r.FIRST_BODY_ROW - 1)
        back = r.read_back(top + lay.values, order, 2026)
        kash = back[("Kash Rai", MON)]
        self.assertEqual([x["interviewer"] for x in kash], ["Daniela", "Maria"])
        self.assertEqual(kash[0]["sent"], 20)
        self.assertEqual(kash[1]["owner"], "Kash Rai")
        self.assertEqual(back[("Ana", dt.date(2026, 9, 21))][0]["s2"], 3)

    def test_changes_since_last_check(self):
        prev = {("Kash Rai", MON): [{"owner": "Kash Rai", "interviewer": "Daniela", "r1": 0.5,
                                     "r2": 0.64},
                                    {"owner": "Kash Rai", "interviewer": "Maria", "r2": 0.5}],
                ("Ana", MON): [{"owner": "Ana", "interviewer": "Lu", "r2": None}]}
        now = [(dt.date(2026, 9, 13), {"Monday": [
            [{"owner": "Kash Rai", "interviewer": "Daniela", "r1": 0.55, "r2": 0.73},
             {"owner": "Kash Rai", "interviewer": "Maria", "r2": 0.5}],
            [{"owner": "Ana", "interviewer": "Lu", "r2": 0.40}],          # first % is not a change
            [{"owner": "New", "interviewer": "X", "r2": 0.10}]]})]       # not on the board before
        got = sorted(c.text for c in r.compare(prev, now)[MON])
        self.assertEqual(got, ["Kash Rai (Daniela) 2nd % 64%→73%", "Kash Rai 1st % 50%→55%"])
        self.assertEqual(r.prior_stamp([["x"], ["... last checked Mon 9/21 13:58 CT ..."]]),
                         "Mon 9/21 13:58 CT")

    def test_band_caps_the_list(self):
        ch = [r.Change(f"O{i}", MON, "r2", 0.1, 0.2) for i in range(6)]
        band = r.day_band_text("Monday", MON, dt.date(2026, 9, 21), 6, ch)
        self.assertIn("CHANGED: O0 2nd % 10%→20%", band)
        self.assertIn("(+2 more)", band)

    def test_colour_bands(self):
        def colour(key, v):
            for lo, hi, c in r.BANDS[key]:
                if (lo is None or v >= lo) and (hi is None or v < hi):
                    return c
        self.assertIs(colour("call_ret", 0.449), r.RED)
        self.assertIs(colour("call_ret", 0.45), r.GREY)
        self.assertIs(colour("r1", 0.4999), r.GREY)
        self.assertIs(colour("r1", 0.50), r.GREEN)
        self.assertIs(colour("r2", 0.499), r.RED)
        self.assertIs(colour("r2", 0.50), r.GREEN)


class Posting(unittest.TestCase):
    def test_late_updates_are_read_off_the_day_bars(self):
        from automations.call_list_to_2nd import slack_post
        board = [[""]] * (r.FIRST_BODY_ROW - 1) + [
            ["MONDAY 9/14  ·  41 offices  ·  CHANGED: Kash Rai 2nd % 64%→73%", "", "x"],
            ["TUESDAY 9/15  ·  40 offices"]]
        self.assertEqual(slack_post.changed_lines(board),
                         ["Monday 9/14: Kash Rai 2nd % 64%→73%"])


if __name__ == "__main__":
    unittest.main()
