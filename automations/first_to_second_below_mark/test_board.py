"""The two-week board: layout and the 'did anything move' check, offline."""
import datetime as dt
import unittest

from automations.first_to_second_below_mark import board as b
from automations.first_to_second_below_mark import run as rep

H = list(rep.DEFAULT_HEADERS[:16])            # A..P, the board's block
W = len(H)
E = H.index(rep.PCT_HEADER)
C = H.index("1st interviews showed up")


def row(owner, shown, pct):
    r = [""] * W
    r[0], r[C], r[E] = owner, shown, pct
    return r


def week(label, start, per_day, future_from=None):
    wr = b.WeekResult(label=label, start=start)
    for day in rep.ars.DAYS:
        d = b.day_date(start, day)
        all_rows = per_day.get(day, [])
        dr = b.DayResult(day=day, date=d, future=bool(future_from and d >= future_from))
        if not dr.future:
            dr.all_rows = all_rows
            dr.interviewed = sum(1 for r in all_rows if r[C])
            dr.rows = rep.worst_first(rep.below_the_mark(all_rows, H), H)
        wr.days[day] = dr
    return wr


class Dates(unittest.TestCase):
    def test_this_week_is_the_sunday_that_starts_it(self):
        self.assertEqual(b.this_week_start(dt.date(2026, 9, 18)), dt.date(2026, 9, 13))

    def test_sunday_keeps_the_week_that_just_ended(self):
        self.assertEqual(b.this_week_start(dt.date(2026, 9, 20)), dt.date(2026, 9, 13))

    def test_day_dates(self):
        self.assertEqual(b.day_date(dt.date(2026, 9, 13), "Monday"), dt.date(2026, 9, 14))
        self.assertEqual(b.day_date(dt.date(2026, 9, 13), "Friday"), dt.date(2026, 9, 18))


class Layout(unittest.TestCase):
    def setUp(self):
        self.this = week("9/13", dt.date(2026, 9, 13), {
            "Monday": [row("Ann", 10, 0.3), row("Bob", 10, 0.5), row("Cid", 8, 0.2)],
        }, future_from=dt.date(2026, 9, 19))
        self.last = week("9/6", dt.date(2026, 9, 6), {
            "Monday": [row("Dee", 10, 0.1)],
        })

    def test_weeks_sit_side_by_side_and_days_line_up(self):
        lay = b.lay_out([self.this, self.last], H, "status", {}, False)
        g = lay.values
        self.assertTrue(g[0][0].startswith("THIS WEEK"))
        self.assertTrue(g[0][W + b.GAP_COLS].startswith("LAST WEEK"))
        mon = lay.band_rows[0] - 1
        self.assertTrue(g[mon][0].startswith("MONDAY 9/14"))
        self.assertTrue(g[mon][W + b.GAP_COLS].startswith("MONDAY 9/7"))
        # Monday is as tall as its longer side: two offices on the left.
        self.assertEqual([g[mon + 1][0], g[mon + 2][0]], ["Cid", "Ann"])
        self.assertEqual(g[mon + 1][W + b.GAP_COLS], "Dee")
        self.assertEqual(lay.band_rows[1], lay.band_rows[0] + 3)

    def test_a_quiet_day_says_so_and_a_future_one_says_not_yet(self):
        this = week("9/13", dt.date(2026, 9, 13), {
            "Tuesday": [row("Bob", 10, 0.5)]}, future_from=dt.date(2026, 9, 18))
        lay = b.lay_out([this, self.last], H, "s", {}, False)
        tue = lay.band_rows[1] - 1
        self.assertIn("0 of 1", lay.values[tue][0])
        self.assertTrue(lay.values[tue + 1][0].startswith("No office"))
        fri = lay.band_rows[4] - 1
        self.assertIn("not yet", lay.values[fri][0])


class Moved(unittest.TestCase):
    def test_changes_since_the_last_check_are_noted(self):
        first = week("9/13", dt.date(2026, 9, 13), {
            "Monday": [row("Ann", 10, 0.3), row("Bob", 10, 0.35), row("Cid", 10, 0.5)]},
            future_from=dt.date(2026, 9, 19))
        last = week("9/6", dt.date(2026, 9, 6), {})
        lay = b.lay_out([first, last], H, "x · checked Thu 9/17 18:30 CT", {}, False)
        prior = b.read_prior(lay.values, W, H)
        self.assertEqual(prior.stamp, "Thu 9/17 18:30")
        self.assertEqual(prior.listed[("9/13", "Monday")], {"Ann": 0.3, "Bob": 0.35})

        # Friday: an applicant called back -- Ann dropped, Bob rose, Cid slipped.
        again = week("9/13", dt.date(2026, 9, 13), {
            "Monday": [row("Ann", 10, 0.2), row("Bob", 10, 0.45), row("Cid", 10, 0.4)]},
            future_from=dt.date(2026, 9, 19))
        moved = b.compare([again, last], prior, H)
        self.assertEqual(moved[("9/13", "Monday", "Ann")], ("retention", "Ann (was 30%)"))
        self.assertEqual(moved[("9/13", "Monday", "Cid")][0], "owner")
        self.assertEqual(again.days["Monday"].risen, ["Bob (35% -> 45%)"])
        lay2 = b.lay_out([again, last], H, "s", moved, False)
        band = lay2.values[lay2.band_rows[0] - 1][0]
        self.assertIn("back above 40%: Bob (35% -> 45%)", band)
        self.assertIn("changed since last check: ", band)
        self.assertIn("Ann (was 30%)", band)
        self.assertIn("Cid (new)", band)
        self.assertEqual(lay2.cell_notes, [])      # never a note: it prints in the DM

    def test_today_is_not_compared(self):
        prior = b.PriorFill(stamp="Fri 9/18 13:00",
                            listed={("9/13", "Friday"): {"Ann": 0.3}})
        wk = week("9/13", dt.date(2026, 9, 13), {"Friday": [row("Ann", 10, 0.2)]})
        wk.days["Friday"].today = True
        self.assertEqual(b.compare([wk], prior, H), {})

    def test_first_run_compares_nothing(self):
        wk = week("9/13", dt.date(2026, 9, 13), {"Monday": [row("Ann", 10, 0.3)]})
        self.assertEqual(b.compare([wk], b.PriorFill(), H), {})


class NetworkRetry(unittest.TestCase):
    def test_a_dropped_connection_is_retried(self):
        import requests
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) < 2:
                raise requests.exceptions.ConnectionError("Connection aborted")
            return "ok"
        self.assertEqual(b._with_network_retry(flaky, logfn=lambda *_: None, wait=0), "ok")
        self.assertEqual(len(calls), 2)

    def test_a_missing_box_is_not_retried(self):
        calls = []

        def missing():
            calls.append(1)
            raise LookupError("no box")
        with self.assertRaises(LookupError):
            b._with_network_retry(missing, logfn=lambda *_: None, wait=0)
        self.assertEqual(len(calls), 1)


class Baseline(unittest.TestCase):
    def test_an_every_office_fill_is_no_baseline(self):
        wk = week("9/13", dt.date(2026, 9, 13), {"Monday": [row("Ann", 10, 0.3)]})
        prior = b.PriorFill(stamp="Fri 9/18 07:15", show_all=True,
                            listed={("9/13", "Monday"): {"Ann": None}})
        self.assertEqual(b.compare([wk], prior, H), {})

    def test_blank_before_is_not_a_move(self):
        wk = week("9/13", dt.date(2026, 9, 13), {"Monday": [row("Ann", 10, 0.3)]})
        prior = b.PriorFill(stamp="Fri 9/18 07:15",
                            listed={("9/13", "Monday"): {"Ann": None}})
        self.assertEqual(b.compare([wk], prior, H), {})

    def test_status_line_marks_an_all_fill(self):
        lay = b.lay_out([week("9/13", dt.date(2026, 9, 13), {})], H,
                        "every office  ·  checked Fri 9/18 07:15 CT", {}, True)
        self.assertTrue(b.read_prior(lay.values, W, H).show_all)


class Colours(unittest.TestCase):
    def test_every_rule_needs_a_number(self):
        reqs = b.cf_requests(0, [], H, 2, 60)
        formulas = [r["addConditionalFormatRule"]["rule"]["booleanRule"]["condition"]
                    ["values"][0]["userEnteredValue"] for r in reqs]
        self.assertTrue(formulas)
        self.assertTrue(all(f.startswith("=AND(ISNUMBER(") for f in formulas))
        # the right-hand week points at its own columns
        self.assertTrue(any("ISNUMBER(V5)" in f for f in formulas))


class EveLayout(unittest.TestCase):
    def _reqs(self):
        wk = week("9/13", dt.date(2026, 9, 13), {"Monday": [row("Ann", 10, 0.3)]},
                  future_from=dt.date(2026, 9, 19))
        lay = b.lay_out([wk, week("9/6", dt.date(2026, 9, 6), {})], H, "s", {}, False)
        return lay, b.format_requests(1, 2, 3, H, lay, 2, [100] * W)

    def test_rows_3_and_4_are_one_box_before_the_group_banners(self):
        _, reqs = self._reqs()
        boxes = [r["mergeCells"]["range"] for r in reqs
                 if "mergeCells" in r and r["mergeCells"]["mergeType"] == "MERGE_COLUMNS"]
        g = H.index("Disqualified") - 1
        self.assertEqual([(x["startRowIndex"], x["endRowIndex"], x["startColumnIndex"],
                           x["endColumnIndex"]) for x in boxes],
                         [(2, 4, 0, g), (2, 4, W + 1, W + 1 + g)])

    def test_day_bands_are_taller_and_everything_else_resets(self):
        lay, reqs = self._reqs()
        sizes = [(r["updateDimensionProperties"]["range"]["startIndex"],
                  r["updateDimensionProperties"]["properties"]["pixelSize"])
                 for r in reqs if "updateDimensionProperties" in r
                 and r["updateDimensionProperties"]["range"]["dimension"] == "ROWS"]
        self.assertEqual(sizes[0], (0, b.ROW_PX))
        for band_row in lay.band_rows:
            self.assertIn((band_row - 1, b.DAY_ROW_PX), sizes)

    def test_blank_before_never_counts_as_back_above(self):
        wk = week("9/13", dt.date(2026, 9, 13), {"Monday": [row("Ann", 10, 0.5)]})
        prior = b.PriorFill(stamp="Fri 9/18 07:47",
                            listed={("9/13", "Monday"): {"Ann": None}})
        b.compare([wk], prior, H)
        self.assertEqual(wk.days["Monday"].risen, [])


class Screenshot(unittest.TestCase):
    def setUp(self):
        from automations.first_to_second_below_mark import board_shot as bs
        self.bs = bs
        this = week("9/13", dt.date(2026, 9, 13), {
            "Friday": [row("Ann", 10, 0.3), row("Bob", 10, 0.2)]})
        last = week("9/6", dt.date(2026, 9, 6), {"Friday": [row("Dee", 10, 0.1)]})
        self.grid = b.lay_out([this, last], H, "s", {}, False).values
        # the merged header box: the header text sits on row 3
        self.grid[2][0] = self.grid[2][W + 1] = "Owner Name"

    def test_second_week_found_by_its_header(self):
        self.assertEqual(self.bs.block_start(self.grid), W + b.GAP_COLS)

    def test_each_side_stops_at_its_own_last_office(self):
        band, last, text = self.bs.find_day(self.grid, "Friday", 0)
        self.assertTrue(text.startswith("FRIDAY 9/18"))
        self.assertEqual(last, band + 2)
        band_r, last_r, text_r = self.bs.find_day(self.grid, "Friday", W + b.GAP_COLS)
        self.assertEqual((band_r, last_r), (band, band + 1))
        self.assertTrue(text_r.startswith("FRIDAY 9/11"))


if __name__ == "__main__":
    unittest.main()
