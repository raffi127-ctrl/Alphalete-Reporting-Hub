"""python -m unittest automations.call_list_to_2nd.test_run"""
import datetime as dt
import unittest

from automations.call_list_to_2nd import run as r

LOG_HEADER = ["Client Name", "Date 1st Rd", "1st Round Interviewer", "Full Name", "Qualify",
              "Answer Call", "Booked to 2nd Rd", "Date 2nd Rd", "Showed Up to 2nd Round"]
EVE_HEADER = ["Owner Name", "Interviewer Name", "Sent to call list", "Retention Call list",
              "1st rds booked", "1st rds showed", "1st rd %", "2nd interviews booked",
              "2nd interviews showed", "2nd interview %"]
MON, TUE = dt.date(2026, 9, 14), dt.date(2026, 9, 15)


def row(d1, who, booked, d2, outcome):
    return ["Kash Rai", d1, who, "x", "Qualify", "Answered", booked, d2, outcome]


class SecondRoundCount(unittest.TestCase):
    def test_counts_by_second_round_date_and_interviewer(self):
        vals = [LOG_HEADER,
                row("9/14/2026", "Daniela", "Booked", "9/15/2026", "Showed"),
                row("9/14/2026", "Daniela", "Booked", "9/15/2026", "No Show"),
                row("9/14/2026", "Daniela", "Booked", "9/15/2026", ""),          # not updated
                row("9/14/2026", "Daniela", "Booked", "9/15/2026", "Cancelled"),
                row("9/14/2026", "Daniela", "Booked", "9/15/2026", "Reschedule Requested"),
                row("9/14/2026", "Daniela", "Booked", "9/15/2026", "Paused"),
                row("9/14/2026", "Daniela", "Not Booked", "", ""),
                row("9/14/2026", "Maria", "Booked", "9/15/2026", "Showed")]
        got = r.count_second_rounds(vals, 2026)
        d = got[TUE]
        self.assertEqual((d.booked, d.showed), (5, 2))
        self.assertEqual(d.by, {"Daniela": [4, 1], "Maria": [1, 1]})
        self.assertEqual(got[MON].booked, 0)
        self.assertEqual(got[MON].interviewers, ["Daniela", "Maria"])

    def test_columns_found_by_label_not_position(self):
        # 8 of the tabs have no 'Answer Call' column.
        header = [h for h in LOG_HEADER if h != "Answer Call"]
        vals = [header, ["K", "9/14/2026", "D", "x", "Q", "Booked", "9/15/2026", "Showed"]]
        self.assertEqual(r.count_second_rounds(vals, 2026)[TUE].showed, 1)

    def test_missing_headers_raise(self):
        with self.assertRaises(LookupError):
            r.count_second_rounds([["Client Name", "Date 1st Rd"]], 2026)


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
    def test_thread_link(self):
        from automations.call_list_to_2nd import slack_post
        self.assertEqual(
            slack_post.parse_thread("https://x.slack.com/archives/C0ABC12/p1758480000123456"),
            ("C0ABC12", "1758480000.123456"))


if __name__ == "__main__":
    unittest.main()
