"""Nobody stays blank in a delta box, and a zero is only ever written on
evidence.

Eve, 2026-09-07: "cada vez que se agregue una persona nueva, tenes que
backfillear los numeros diarios de la semana anterior, sino quedan en blanco,
aplicalo como regla general ... si no tienen ventas=0".

Stage 1 (the pre-rollover snapshot) settles a MOVE between captainships. These
cover stage 2, which settles everybody else off last week's program crosstabs:
a name the pull carries gets its real days, a name no view carries gets a
literal 0, and a name whose program FAILED to pull gets neither — absence only
means zero when the pull actually happened.

Offline: no Sheet, no Tableau.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.org_sales_board import delta_lastweek_backfill as bf
from automations.org_sales_board import rollover as ro

# A | rank · B | rep · C/D/E the week triplet · then one triplet per day:
# F/G/H Monday, I/J/K Tuesday, L/M/N Wednesday.
DAY_COLS = (6, 9, 12)
DAYS = ("Monday", "Tuesday", "Wednesday")
# The box sits UNDER a stand-in daily table, because a rep whose name appears
# in col B only once on the whole tab is a hand-keyed row that
# `rollover.manual_fill_rows` (and so this backfill) deliberately skips.
DAILY_ROWS = 1 + 6
TITLE_ROW = DAILY_ROWS + 1
HDR_ROW = TITLE_ROW + 1
FIRST_REP = HDR_ROW + 1
WEEK = [dt.date(2026, 8, 24), dt.date(2026, 8, 25), dt.date(2026, 8, 26)]
DAY_DATES = dict(zip(DAYS, WEEK))
ALIASES: dict = {}


def _title_row(title="CARLOS CAPTAINSHIP"):
    row = [title, "", "Total for week", "", ""]
    for d in DAYS:
        row += [d, "", ""]
    return row


def _hdr_row():
    row = ["", "", "Total this week", "Last week", "Delta"]
    for _d in DAYS:
        row += ["This week", "Last week", "Delta"]
    return row


def _rep(r: int, name: str, this=(0, 0, 0), last=None):
    """One rep row. `last=None` leaves the 'Last week' day cells BLANK — the
    state a person added after Tuesday's freeze is actually in."""
    row = ["1", name,
           "=F%d+I%d+L%d" % (r, r, r), "=G%d+J%d+M%d" % (r, r, r),
           "=Iferror((C%d-D%d)/D%d,0)" % (r, r, r)]
    for i, c in enumerate(DAY_COLS):
        a, b = ro.a1col(c), ro.a1col(c + 1)
        row += [str(this[i]), "" if last is None else str(last[i]),
                "=Iferror((%s%d-%s%d)/%s%d,0)" % (a, r, b, r, b, r)]
    return row


def _totals(r: int, first: int, last_rep: int):
    row = ["Captainship", "", "=F%d+I%d+L%d" % (r, r, r),
           "=G%d+J%d+M%d" % (r, r, r), "=Iferror((C%d-D%d)/D%d,0)" % (r, r, r)]
    for c in DAY_COLS:
        a, b = ro.a1col(c), ro.a1col(c + 1)
        row += ["=SUM(%s%d:%s%d)" % (a, first, a, last_rep),
                "=SUM(%s%d:%s%d)" % (b, first, b, last_rep),
                "=Iferror((%s%d-%s%d)/%s%d,0)" % (a, r, b, r, b, r)]
    return row


# Five reps already frozen (enough to calibrate on) + one added afterwards.
FROZEN = [("Rep One", (5, 6, 7), (1, 2, 3)),
          ("Rep Two", (1, 1, 1), (4, 5, 6)),
          ("Rep Three", (2, 2, 2), (7, 8, 9)),
          ("Rep Four", (3, 3, 3), (2, 0, 4)),
          ("Rep Five", (4, 4, 4), (0, 0, 1))]
NEW_REP = "Nueva Persona"


def _daily_stub():
    """Enough of a daily table that every rep's name appears twice in col B."""
    rows = [["", "B2B - All Units", "Monday", "Tuesday", "Wednesday"]]
    for name, this, _last in FROZEN:
        rows.append(["1", name] + [str(v) for v in this])
    rows.append(["1", NEW_REP, "9", "9", "9"])
    return rows


def _board(new_last=None):
    rows = _daily_stub() + [_title_row(), _hdr_row()]
    r = FIRST_REP
    for name, this, last in FROZEN:
        rows.append(_rep(r, name, this, last))
        r += 1
    rows.append(_rep(r, NEW_REP, (9, 9, 9), new_last))
    last_rep = r
    rows.append(_totals(r + 1, FIRST_REP, last_rep))
    return rows, [x[:] for x in rows]           # (values, formulas)


def _prog(extra=None, metric="count", program="b2b"):
    """The parsed last-week pull: every frozen rep at the numbers the board
    already has, so calibration passes."""
    data = {}
    for name, _this, last in FROZEN:
        data[name.lower()] = {metric: dict(zip(WEEK, last))}
    if extra:
        data.update(extra)
    return {program: data}


class TheFixtureIsShaped(unittest.TestCase):
    def test_one_box_six_reps(self):
        grid, _f = _board()
        tables = ro.find_delta_tables(grid)
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0]["this_cols"], list(DAY_COLS))
        self.assertEqual(len(tables[0]["data_rows"]), len(FROZEN) + 1)

    def test_only_the_new_rep_is_blank(self):
        grid, f = _board()
        cells = bf.blank_cells(grid, f)
        self.assertEqual({c["name"] for c in cells}, {NEW_REP})
        self.assertEqual(len(cells), len(DAYS))

    def test_the_box_routes_to_its_program(self):
        grid, _f = _board()
        t = ro.find_delta_tables(grid)[0]
        self.assertEqual(bf.box_title(grid, t), "CARLOS CAPTAINSHIP")
        self.assertEqual(bf.program_hint(bf.box_title(grid, t)), "b2b")


class AbsentFromEveryViewIsZero(unittest.TestCase):
    def test_seven_literal_zeros(self):
        grid, f = _board()
        cells = bf.blank_cells(grid, f)
        got, notes = bf.plan_from_programs(grid, cells, _prog(), [],
                                           DAY_DATES, ALIASES)
        new_row = FIRST_REP + len(FROZEN)
        self.assertEqual([u["range"] for u in got],
                         [f"{c}{new_row}" for c in ("G", "J", "M")])
        self.assertEqual([u["values"][0][0] for u in got], [0, 0, 0])
        self.assertTrue(any("0" in n for n in notes), notes)

    def test_a_failed_program_writes_nothing(self):
        """Absence is only zero when the pull happened. It did not."""
        grid, f = _board()
        cells = bf.blank_cells(grid, f)
        got, notes = bf.plan_from_programs(grid, cells, _prog(), ["b2b"],
                                           DAY_DATES, ALIASES)
        self.assertEqual(got, [])
        self.assertIn("b2b", " ".join(notes))
        self.assertIn(NEW_REP, " ".join(notes))


class PresentInTheViewGetsRealNumbers(unittest.TestCase):
    def test_per_day_values_land(self):
        grid, f = _board()
        cells = bf.blank_cells(grid, f)
        prog = _prog({NEW_REP.lower(): {"count": dict(zip(WEEK, (11, 0, 13)))}})
        got, _n = bf.plan_from_programs(grid, cells, prog, [],
                                        DAY_DATES, ALIASES)
        self.assertEqual([u["values"][0][0] for u in got], [11, 0, 13])

    def test_found_in_another_program_than_the_hint(self):
        """per_for falls back across every program; so does this."""
        grid, f = _board()
        cells = bf.blank_cells(grid, f)
        prog = _prog()
        prog["nds"] = {NEW_REP.lower(): {"Total": dict(zip(WEEK, (2, 3, 4)))}}
        got, _n = bf.plan_from_programs(grid, cells, prog, [],
                                        DAY_DATES, ALIASES)
        self.assertEqual([u["values"][0][0] for u in got], [2, 3, 4])


class NothingAlreadyThereIsTouched(unittest.TestCase):
    def test_a_frozen_zero_is_left_alone(self):
        """A literal 0 means 'frozen, and the answer was zero' — not blank."""
        grid, f = _board(new_last=(0, 0, 0))
        self.assertEqual(bf.blank_cells(grid, f), [])

    def test_a_formula_is_never_overwritten(self):
        grid, f = _board()
        new_row = FIRST_REP + len(FROZEN)
        for c in DAY_COLS:                       # the new rep's Last-week cells
            f[new_row - 1][c] = '=SUMIF($B$1:$B$9,"x",$C$1:$C$9)'
        self.assertEqual(bf.blank_cells(grid, f), [])


class TheCalibrationGuard(unittest.TestCase):
    def test_a_clean_pull_calibrates(self):
        grid, _f = _board()
        chk, bad = bf.calibrate_programs(grid, _prog(), DAY_DATES, ALIASES)
        self.assertEqual((chk, bad), (len(FROZEN), []))

    def test_the_wrong_week_is_caught(self):
        """Every frozen row disagreeing = the pull is not the week the board
        froze. apply_backfill refuses to write anything off it."""
        grid, _f = _board()
        shifted = _prog()
        for _name, vals in shifted["b2b"].items():
            vals["count"] = {d: v + 100 for d, v in vals["count"].items()}
        chk, bad = bf.calibrate_programs(grid, shifted, DAY_DATES, ALIASES)
        self.assertEqual(chk, len(FROZEN))
        self.assertEqual(len(bad), len(FROZEN))
        self.assertGreater(len(bad) / chk, bf.MAX_PROGRAM_DISAGREE_SHARE)

    def test_one_re_filed_rep_does_not_block_the_run(self):
        """A rep re-filed under another captain since the freeze may disagree.
        One out of five is drift, not a wrong week — but five is under the
        minimum, so the guard needs BOTH knobs to be meaningful."""
        grid, _f = _board()
        drift = _prog()
        drift["b2b"]["rep one"]["count"] = dict(zip(WEEK, (99, 99, 99)))
        chk, bad = bf.calibrate_programs(grid, drift, DAY_DATES, ALIASES)
        self.assertEqual((chk, len(bad)), (len(FROZEN), 1))

    def test_an_empty_pull_calibrates_on_nothing(self):
        """No frozen row is in the pull -> 0 checked -> under the minimum, so
        nothing is written. An empty pull must never read as 'everybody sold
        zero'."""
        grid, _f = _board()
        chk, bad = bf.calibrate_programs(grid, {"b2b": {}}, DAY_DATES, ALIASES)
        self.assertEqual((chk, bad), (0, []))
        self.assertLess(chk, bf.MIN_PROGRAM_CALIBRATION_ROWS)


class TheNewInternetBoxReadsItsOwnMetric(unittest.TestCase):
    def test_new_internet_kind_picks_the_new_internet_sum(self):
        prog = {"fiber": {"a rep": {"Total": {WEEK[0]: 10},
                                    "NewInternet": {WEEK[0]: 3}}}}
        got, _tk = bf.program_days(prog, "fiber", "A Rep", "NEW INTERNET",
                                   ALIASES)
        self.assertEqual(got, {WEEK[0]: 3})
        got, _tk = bf.program_days(prog, "fiber", "A Rep", "ALL UNITS",
                                   ALIASES)
        self.assertEqual(got, {WEEK[0]: 10})

    def test_absent_is_none_not_empty(self):
        """(None) 'no view carries them' and ({}) 'carried, sold nothing' both
        end at 0 — but only the first has to check the failed-program list."""
        self.assertEqual(bf.program_days({"b2b": {}}, "b2b", "Ghost",
                                         "ALL UNITS", ALIASES), (None, None))


if __name__ == "__main__":
    unittest.main()


class TheWeekTheParseCameBackOn(unittest.TestCase):
    """The 1-PAGER worksheets are RELATIVE windows, so 'last week' is only last
    week while the view's clock agrees with the board's. The dates decide."""

    def test_parsed_dates_reads_what_the_pull_actually_is(self):
        parsed = {"a rep": {"count": {WEEK[0]: 3, WEEK[2]: 1}},
                  "b rep": {"count": {WEEK[1]: 5}}}
        self.assertEqual(bf.parsed_dates(parsed), set(WEEK))

    def test_an_empty_parse_has_no_dates(self):
        self.assertEqual(bf.parsed_dates({}), set())
        self.assertEqual(bf.parsed_dates({"a": {"count": {}}}), set())

    def test_a_different_week_is_not_a_subset(self):
        want = set(WEEK)
        other = {dt.date(2026, 8, 31), dt.date(2026, 9, 1)}
        self.assertFalse(other <= want)
        self.assertTrue({WEEK[0]} <= want)
