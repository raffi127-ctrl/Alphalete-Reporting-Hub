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

    def test_counts_move_without_their_percent(self):
        # Eve, 2026-09-22: a count that moves while its % stays put used to be
        # invisible. Counts read as counts, percents as percents.
        prev = {("Kash Rai", MON): [{"owner": "Kash Rai", "interviewer": "Daniela",
                                     "sent": 66, "b1": 20, "s1": 10, "r1": 0.5,
                                     "b2": 4, "s2": 2, "r2": 0.5}]}
        now = [(dt.date(2026, 9, 13), {"Monday": [
            [{"owner": "Kash Rai", "interviewer": "Daniela",
              "sent": 70, "b1": 20, "s1": 10, "r1": 0.5,
              "b2": 8, "s2": 4, "r2": 0.5}]]})]
        got = [c.text for c in r.compare(prev, now)[MON]]
        self.assertEqual(sorted(got), ["Kash Rai 2nd booked 4→8", "Kash Rai 2nd showed 2→4",
                                       "Kash Rai Sent 66→70"])

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
    def test_message_is_one_line_and_names_the_second_picture(self):
        from automations.call_list_to_2nd import slack_post
        plain = slack_post.message("CALL LIST TO 2ND ROUND  ·  Monday 9/21")
        self.assertEqual(len(plain.splitlines()), 1)
        self.assertNotIn("green", plain)                     # no colour legend
        self.assertNotIn("picture", plain)                   # nothing moved: one image
        self.assertIn("last picture", slack_post.message("CALL LIST  ·  Monday 9/21", True))

    def test_the_picture_band_carries_no_change_list(self):
        band = r.picture_band_text(dt.date(2026, 9, 21), 8)
        self.assertEqual(band, "MONDAY 9/21  ·  8 offices")


class WeekPicture(unittest.TestCase):
    """Rafael, 2026-09-24: the week so far, every listed office on every day,
    and a TOTAL FOR THE WEEK box."""
    MON, TUE, WED = dt.date(2026, 9, 21), dt.date(2026, 9, 22), dt.date(2026, 9, 23)

    def _data(self):
        sr_mon = r.SecondRounds()
        sr_mon.by = {"Daniela": [4, 2]}
        sr_wed = r.SecondRounds()
        sr_wed.by = {"Daniela": [6, 5], "Maria": [2, 0]}
        as_data = {("Isaiah", self.MON): {"sent": 10, "b1": 20, "s1": 10},
                   ("Kash", self.TUE): {"sent": 5, "b1": 4, "s1": 3},
                   ("Kash", self.WED): {"sent": 5, "b1": 6, "s1": 3}}
        logs = {"Kash": {self.MON: sr_mon, self.WED: sr_wed}}

        def group_for(o, d, keep_empty=False):
            return r.make_group(o, ["Daniela"] if o == "Kash" else [], as_data.get((o, d)),
                                logs.get(o, {}).get(d), keep_empty=keep_empty)
        return group_for

    def test_week_days_to(self):
        self.assertEqual(r.week_days_to(self.WED), [self.MON, self.TUE, self.WED])
        fri = dt.date(2026, 9, 25)
        self.assertEqual(r.week_days_to(fri)[0], self.MON)
        self.assertEqual(len(r.week_days_to(fri)), 5)

    def test_every_listed_office_on_every_day_then_the_total(self):
        blocks = r.week_picture_blocks(["Isaiah", "Kash", "Nobody"],
                                       [self.MON, self.TUE, self.WED], self._data())
        self.assertEqual(len(blocks), 4)
        for text, kind, groups in blocks[:3]:
            self.assertEqual(kind, "past")
            self.assertEqual([g[0]["owner"] for g in groups], ["Isaiah", "Kash"])
        # Isaiah had only Monday, but is still on Tuesday's box, blank
        tue = blocks[1][2]
        self.assertIsNone(tue[0][0].get("sent"))
        self.assertIn("1 office", blocks[1][0])            # only Kash active Tuesday
        text, kind, totals = blocks[3]
        self.assertEqual(kind, "total")
        self.assertTrue(text.startswith("TOTAL FOR THE WEEK  ·  Mon 9/21 – Wed 9/23"))
        self.assertEqual([g[0]["owner"] for g in totals], ["Isaiah", "Kash"])

    def test_total_sums_counts_and_recomputes_percents(self):
        blocks = r.week_picture_blocks(["Kash"], [self.MON, self.TUE, self.WED], self._data())
        kash = blocks[-1][2][0]
        head = kash[0]
        self.assertEqual((head["sent"], head["b1"], head["s1"]), (10, 10, 6))
        self.assertAlmostEqual(head["call_ret"], 1.0)      # 10 booked / 10 sent
        self.assertAlmostEqual(head["r1"], 0.6)            # 6 showed / 10 booked
        by = {row["interviewer"]: row for row in kash}
        self.assertEqual((by["Daniela"]["b2"], by["Daniela"]["s2"]), (10, 7))
        self.assertAlmostEqual(by["Daniela"]["r2"], 0.7)
        self.assertEqual(by["Maria"]["r2"], 0)
        self.assertEqual(kash[0]["interviewer"], "Daniela")  # most booked first

    def test_quiet_week_has_no_total_box(self):
        blocks = r.week_picture_blocks(["Nobody"], [self.MON], self._data())
        self.assertEqual([(k, g) for _, k, g in blocks], [("past", [])])   # the day, empty
        self.assertIn("no activity", blocks[0][0])



class MovedColumn(unittest.TestCase):
    """2026-09-24: the updates picture printed counts as percents and cut the
    column off."""
    def test_counts_read_as_counts(self):
        d = dt.date(2026, 9, 21)
        self.assertEqual(r.Change("O", d, "b2", 7, 8).amount(7), "7")
        self.assertEqual(r.Change("O", d, "r2", 0.71, 0.83).amount(0.71), "71%")

    def test_column_fits_the_longest_line(self):
        long = "Call list % 100% → 113%  ·  1st % 39% → 44%  ·  1st showed 10 → 11"
        self.assertGreaterEqual(r.moved_width([long]), 8 * len(long))
        self.assertEqual(r.moved_width([]), r.MOVED_WIDTH)


class OnePicturePerDay(unittest.TestCase):
    """Rafael 2026-09-25: the week in one picture was too large -- one per day."""
    def test_boxes_split_at_each_band(self):
        from automations.call_list_to_2nd import slack_post as sp
        blank = [""] * 4
        v = [["TITLE"], ["status"], ["Owner Name"],
             ["MONDAY 9/21  ·  2 offices"], ["Ann", "x"], ["", "y"], blank,
             ["TUESDAY 9/22  ·  1 office"], ["Ann", "z"], blank,
             ["TOTAL FOR THE WEEK  ·  Mon 9/21 – Tue 9/22  ·  1 offices"], ["Ann", "t"]]
        got = sp.boxes(v, 4)
        self.assertEqual([(t.split()[0], a, b) for t, a, b in got],
                         [("MONDAY", 4, 6), ("TUESDAY", 8, 9), ("TOTAL", 11, 12)])

if __name__ == "__main__":
    unittest.main()
