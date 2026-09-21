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
    for day in b.WEEK_DAYS:
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
        self.assertEqual(sizes[0], (b.FIRST_BODY_ROW - 1, b.ROW_PX))
        # the header rows are never squeezed to the body height
        self.assertIn((b.HEADER_ROW - 1, b.HEADER_ROW_PX), sizes)
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


class TabNames(unittest.TestCase):
    def test_the_one_day_production_flag_never_hits_the_board(self):
        self.assertNotEqual(rep.TARGET_TAB.lower(), b.BOARD_TAB.lower())
        self.assertNotEqual(rep.SANDBOX_TAB.lower(), b.BOARD_TAB.lower())


class Clock(unittest.TestCase):
    """Each office at its own 11:00 AM and 6:30 PM (Rafael, 2026-09-21)."""
    def at(self, h, m, day=21):
        return dt.datetime(2026, 9, day, h, m, tzinfo=rep.CT)

    def test_each_zone_lands_on_its_own_ct_hour(self):
        from automations.first_to_second_below_mark import office_tz as tz
        cases = {(10, 0): "America/New_York", (11, 0): "America/Chicago",
                 (12, 0): "America/Denver", (13, 0): "America/Los_Angeles",
                 (17, 30): "America/New_York", (18, 30): "America/Chicago",
                 (19, 30): "America/Denver", (20, 30): "America/Los_Angeles"}
        zones_ = ["America/New_York", "America/Chicago", "America/Denver",
                  "America/Los_Angeles"]
        for (h, m), want in cases.items():
            due = [z for z in zones_ if tz.due_slot(z, self.at(h, m))]
            self.assertEqual(due, [want], f"{h}:{m:02d} CT")

    def test_a_late_start_still_counts_but_never_reaches_the_next_zone(self):
        from automations.first_to_second_below_mark import office_tz as tz
        self.assertEqual(tz.due_slot("America/New_York", self.at(10, 40)), (11, 0))
        self.assertIsNone(tz.due_slot("America/New_York", self.at(11, 0)))
        self.assertIsNone(tz.due_slot("America/Chicago", self.at(10, 59)))

    def test_known_and_unknown_offices(self):
        from automations.first_to_second_below_mark import office_tz as tz
        self.assertEqual(tz.zone_for("Colten Wright", use_aliases=False), "America/New_York")
        self.assertEqual(tz.zone_for("José Velazques", use_aliases=False), "America/Los_Angeles")
        self.assertEqual(tz.zone_or_fallback("Nobody Atall", use_aliases=False),
                         ("America/Chicago", False))

    def test_pick_pass(self):
        roster = ["Colten Wright", "Kash Rai", "JC Pascual"]
        import unittest.mock as um
        from automations.first_to_second_below_mark import office_tz as tz
        with um.patch.object(tz, "_alias_candidates", return_value=[]):
            who, scope, _ = b.pick_pass(roster, self.at(10, 0), due=True)
            self.assertEqual(who, {"Colten Wright"})
            self.assertEqual(scope, "Eastern offices  ·  11:00 AM local update")
            self.assertEqual(b.pick_pass(roster, self.at(14, 0), due=True)[0], set())
            self.assertIsNone(b.pick_pass(roster, self.at(14, 0))[0])
            self.assertEqual(b.pick_pass(roster, self.at(14, 0), zone="pacific")[0],
                             {"JC Pascual"})


class Saturday(unittest.TestCase):
    def test_the_week_runs_to_saturday(self):
        self.assertEqual(b.WEEK_DAYS[-1], "Saturday")
        self.assertEqual(b.day_date(dt.date(2026, 9, 13), "Saturday"), dt.date(2026, 9, 19))
        lay = b.lay_out([week("9/13", dt.date(2026, 9, 13), {})], H, "s", {}, False)
        self.assertEqual(len(lay.band_rows), 6)
        self.assertTrue(lay.values[lay.band_rows[-1] - 1][0].startswith("SATURDAY 9/19"))
        self.assertIn(b.REPORT_TITLE, lay.values[0][0])


class Store(unittest.TestCase):
    def test_round_trip_lines_up_by_header_label(self):
        rows = {("9/13", "Monday", "Ann"): row("Ann", 10, 0.3)}
        vals = b.store_to_values(rows, {("9/13", "Monday", "Ann"): "Mon 9/14 11:00"}, H)
        # a column added to the template later: the stored numbers follow their labels
        H2 = H[:2] + ["New column"] + H[2:]
        back, pulled = b.store_from_values(vals, H2)
        r = back[("9/13", "Monday", "Ann")]
        self.assertEqual(r[H2.index(rep.PCT_HEADER)], 0.3)
        self.assertEqual(r[2], "")
        self.assertEqual(pulled[("9/13", "Monday", "Ann")], "Mon 9/14 11:00")

    def test_build_results_keeps_only_the_pass(self):
        from automations.first_to_second_below_mark import source as src
        owners = [src.Owner(name=n, goal=0.5) for n in ("Ann", "Bob")]             if "goal" in src.Owner.__dataclass_fields__ else None
        if owners is None:
            self.skipTest("Owner shape changed")
        wk = src.Week(label="9/13", header_row=0, owners=owners)
        rows = {("9/13", "Monday", "Ann"): row("Ann", 10, 0.3),
                ("9/13", "Monday", "Bob"): row("Bob", 10, 0.2)}
        res = b.build_results([wk], [dt.date(2026, 9, 13)], H, rows,
                              today=dt.date(2026, 9, 14), only={"Bob"})
        self.assertEqual([r[0] for r in res[0].days["Monday"].rows], ["Bob"])
        self.assertTrue(res[0].days["Tuesday"].future)


class PicturePlan(unittest.TestCase):
    def setUp(self):
        from automations.first_to_second_below_mark import board_shot as bs
        self.bs = bs
        this = week("9/20", dt.date(2026, 9, 20), {
            "Monday": [row("Ann", 10, 0.3)], "Tuesday": [row("Bob", 10, 0.2)]},
            future_from=dt.date(2026, 9, 23))
        this.days["Tuesday"].today = True
        last = week("9/13", dt.date(2026, 9, 13), {
            "Friday": [row("Dee", 10, 0.1)], "Saturday": [row("Eve", 4, 0.25)]})
        self.grid = b.lay_out([this, last], H, "s", {}, False).values
        self.grid[2][0] = self.grid[2][W + 1] = "Owner Name"

    def test_tuesday_is_this_week_monday_to_today(self):
        blocks = self.bs.plan(self.grid, dt.date(2026, 9, 22))
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["caption"], "THIS WEEK  ·  MON 9/21 – TUE 9/22 (TODAY)")
        self.assertEqual([d for d, _ in blocks[0]["days"]], ["Monday", "Tuesday"])

    def test_monday_carries_last_week_whole(self):
        blocks = self.bs.plan(self.grid, dt.date(2026, 9, 21))
        self.assertEqual([x["caption"].split("  ·  ")[0] for x in blocks],
                         ["LAST WEEK", "THIS WEEK"])
        self.assertEqual(blocks[0]["caption"], "LAST WEEK  ·  MON 9/14 – SAT 9/19  ·  FINAL")
        self.assertEqual(len(blocks[0]["days"]), 6)
        sat = self.bs.find_day(self.grid, "Saturday", W + b.GAP_COLS)
        self.assertTrue(blocks[0]["body"].endswith(str(sat[1])))

    def test_subtitle(self):
        st = ("Eastern offices  ·  11:00 AM local update  ·  offices at or under 40% on "
              "'Retention first showed up booked second'  ·  checked Mon 9/21 10:00 CT")
        self.assertEqual(self.bs.subtitle(st), "Eastern offices  ·  11:00 AM local update"
                         "  ·  offices at or under 40%  ·  checked Mon 9/21 10:00 CT")
        self.assertTrue(self.bs.subtitle("offices at or under 40% on x  ·  checked "
                                         "Mon 9/21 10:00 CT").startswith("All offices"))


class BorrowedRoster(unittest.TestCase):
    def test_monday_without_this_weeks_block_checks_last_weeks_offices(self):
        from automations.first_to_second_below_mark import source as src
        last = src.Week(label="9/13", header_row=5, owners=[src.Owner(name="Ann", goal=0.5)])
        weeks = [src.Week(label="9/20", header_row=0, owners=[]), last]
        missing = ["not on tab yet", None]
        b.borrow_roster(weeks, missing)
        self.assertEqual(weeks[0].label, "9/20")
        self.assertEqual([o.name for o in weeks[0].owners], ["Ann"])
        self.assertIn("borrowed from week of 9/13", missing[0])

    def test_a_real_block_is_never_replaced(self):
        from automations.first_to_second_below_mark import source as src
        this = src.Week(label="9/20", header_row=5, owners=[src.Owner(name="Bob")])
        weeks = [this, src.Week(label="9/13", header_row=5, owners=[src.Owner(name="Ann")])]
        missing = [None, None]
        b.borrow_roster(weeks, missing)
        self.assertEqual([o.name for o in weeks[0].owners], ["Bob"])
        self.assertIsNone(missing[0])


if __name__ == "__main__":
    unittest.main()
