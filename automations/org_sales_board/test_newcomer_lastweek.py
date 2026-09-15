"""Somebody new on a board gets LAST week too — number or literal 0 — and the
totals only move when they actually sold (Eve 2026-09-01 / 09-07 / 09-15)."""
import datetime as dt
import unittest

from automations.org_sales_board import newcomer_lastweek as N

TODAY = dt.date(2026, 9, 15)          # Tuesday: last week = WE 9.13 (Mon 9/7..Sun 9/13)
MON = dt.date(2026, 9, 7)
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _block(frozen, newcomer="New Person", stack_label="WE 9.13"):
    """An All-Campaigns-shaped tab: leaderboard, daily table + WE stack, delta."""
    reps = list(frozen)
    g = [["AT&T FIBER TEAM", "", "WE 09.20", "WE 09.13"]]
    for i, (n, k) in enumerate(reps, 1):
        g.append([str(i), n, "1", str(k)])
    g.append([str(len(reps) + 1), newcomer, "4", ""])
    lb_total = len(g) + 1
    g.append(["TOTALS", "", "", str(sum(k for _, k in reps))])
    g.append(["", ""])
    hdr = len(g) + 1
    g.append(["All Units", "", *DAYS, "RUNNING WEEK TOTALS", "LAST WEEK'S TOTALS",
              "PREVIOUS WEEK'S TOTALS"])
    g.append(["", "", "14", "15", "16", "17", "18", "19", "20", "", "", ""])
    for i, (n, k) in enumerate(reps, 1):
        g.append([str(i), n, "1", "", "", "", "", "", "", "1", str(k), "0"])
    g.append([str(len(reps) + 1), newcomer, "4", "", "", "", "", "", "", "4", "", ""])
    totals = len(g) + 1
    g.append(["Totals", "", "", "", "", "", "", "", "", "", str(sum(k for _, k in reps)), ""])
    stack = len(g) + 1
    g.append([stack_label, "", "10", "10", "10", "10", "10", "0", "0",
              str(sum(k for _, k in reps)), "", ""])
    g.append(["", ""])
    g.append(["", "", "", "", "", "Monday", "", "", "Tuesday"])
    dhdr = len(g) + 1
    g.append(["", "", "Total this week", "Last week", "Delta", "This week", "Last week",
              "Delta", "This week", "Last week", "Delta"])
    for n, _k in reps:
        g.append(["", n, "1", "1", "0%", "1", "1", "0%", "0", "0", "0%"])
    drow = len(g) + 1
    g.append(["", newcomer, "4", "", "0%", "4", "", "0%", "0", "", "0%"])
    return g, {"lb_total": lb_total, "hdr": hdr, "totals": totals, "stack": stack,
               "dhdr": dhdr, "drow": drow}


REPS = [("Alice A", 10), ("Bob B", 20), ("Cara C", 30), ("Dan D", 40), ("Eve E", 50)]


def _plan(grid, days_of, leaderboard=True):
    from automations.all_campaigns_board import rollover as rj
    lb = rj.find_leaderboard_block(grid) if leaderboard else None
    return N.plan_block(grid, grid, section="All Units", leaderboard=lb,
                        days_of=days_of, today=TODAY, board="test")


def _days(per):
    """A last-week view that agrees with the frozen rows (so calibration
    passes) unless `per` overrides a name."""
    view = {n: {"Monday": k} for n, k in REPS}
    view.update(per)

    def days_of(name):
        d = {x: 0 for x in DAYS}
        d.update(view.get(name, {}))
        return d, ""
    return days_of


class Finders(unittest.TestCase):
    def test_a_blank_among_frozen_rows_is_a_newcomer(self):
        g, at = _block(REPS)
        blanks, filled, _a = N.daily_blanks(g, g, "All Units")
        self.assertEqual([b.name for b in blanks], ["New Person"])
        self.assertEqual(len(filled), 5)

    def test_a_table_nobody_has_frozen_yet_is_not_read_as_new(self):
        g, _ = _block(REPS[:2])
        self.assertEqual(N.daily_blanks(g, g, "All Units")[0], [])

    def test_leaderboard_only_when_the_column_really_is_last_week(self):
        g, _ = _block(REPS)
        from automations.all_campaigns_board import rollover as rj
        lb = rj.find_leaderboard_block(g)
        self.assertEqual(len(N.leaderboard_blanks(g, g, lb["header_row"],
                                                  lb["data_rows"], TODAY)[0]), 1)
        # a week later the same column is two weeks ago — not ours to fill
        self.assertEqual(N.leaderboard_blanks(g, g, lb["header_row"], lb["data_rows"],
                                              TODAY + dt.timedelta(days=7))[0], [])

    def test_a_formula_is_never_a_blank(self):
        g, at = _block(REPS)
        f = [list(r) for r in g]
        f[at["totals"] - 2][10] = "=K1"     # the newcomer's K holds a formula
        self.assertEqual(N.daily_blanks(g, f, "All Units")[0], [])


class Plan(unittest.TestCase):
    def test_no_sales_writes_literal_zeros_and_no_totals(self):
        g, at = _block(REPS)
        ups, notes = _plan(g, _days({}))
        got = {u["range"]: u["values"][0][0] for u in ups}
        self.assertEqual(set(got.values()), {0})
        self.assertIn(f"K{at['totals'] - 1}", got)             # LAST WEEK
        self.assertIn(f"G{at['drow']}", got)                   # delta Monday
        self.assertIn(f"J{at['drow']}", got)                   # delta Tuesday
        self.assertNotIn(f"K{at['totals']}", got)              # totals untouched
        self.assertTrue(any("no sales: 0" in n for n in notes))

    def test_sales_grow_every_total_by_exactly_the_person(self):
        g, at = _block(REPS)
        ups, _ = _plan(g, _days({"New Person": {"Monday": 5, "Tuesday": 3}}))
        got = {u["range"]: u["values"][0][0] for u in ups}
        self.assertEqual(got[f"K{at['totals'] - 1}"], 8)
        self.assertEqual(got["D" + str(at["lb_total"] - 1)], 8)
        self.assertEqual(got[f"K{at['totals']}"], 158)          # 150 + 8
        self.assertEqual(got[f"D{at['lb_total']}"], 158)
        self.assertEqual(got[f"C{at['stack']}"], 15)            # Mon 10 + 5
        self.assertEqual(got[f"D{at['stack']}"], 13)            # Tue 10 + 3
        self.assertEqual(got[f"J{at['stack']}"], 158)
        self.assertEqual(got[f"G{at['drow']}"], 5)
        self.assertEqual(got[f"J{at['drow']}"], 3)

    def test_stack_row_that_is_not_last_week_is_left_alone(self):
        g, at = _block(REPS, stack_label="WE 9.6")
        ups, notes = _plan(g, _days({"New Person": {"Monday": 2}}))
        self.assertNotIn(f"C{at['stack']}", {u["range"] for u in ups})
        self.assertTrue(any("not added to the stack" in n for n in notes))

    def test_a_source_that_disagrees_with_the_frozen_rows_writes_nothing(self):
        g, _ = _block(REPS)
        wrong = {n: {"Monday": k + 7} for n, k in REPS}
        ups, notes = _plan(g, _days(wrong))
        self.assertEqual(ups, [])
        self.assertTrue(any("do not match" in n for n in notes))

    def test_unknown_source_leaves_the_person_blank_and_named(self):
        g, _ = _block(REPS)

        def days_of(name):
            if name == "New Person":
                return None, "its section(s) Retail NL have no last-week view"
            return _days({n: {"Monday": k} for n, k in REPS})(name)
        ups, notes = _plan(g, days_of)
        self.assertEqual(ups, [])
        self.assertTrue(any("Retail NL" in n and "left blank" in n for n in notes))

    def test_a_total_that_is_not_a_number_refuses(self):
        g, at = _block(REPS)
        g[at["totals"] - 1][10] = "n/a"
        with self.assertRaises(N.Refuse):
            _plan(g, _days({"New Person": {"Monday": 1}}))

    def test_second_run_finds_nothing(self):
        g, _ = _block(REPS)
        ups, _n = _plan(g, _days({}))
        from automations.org_sales_board.rollover import a1col  # noqa: F401
        import re
        for u in ups:
            m = re.match(r"([A-Z]+)(\d+)", u["range"])
            col = sum((ord(ch) - 64) * 26 ** i for i, ch in enumerate(reversed(m.group(1))))
            row = g[int(m.group(2)) - 1]
            row += [""] * (col - len(row))
            row[col - 1] = str(u["values"][0][0])
        self.assertEqual(_plan(g, _days({}))[0], [])


class PullFallback(unittest.TestCase):
    """NDS 2026-09-15: the pinned view cannot reach last week, so the view's
    own '(LW2)' worksheet is pulled unpinned instead."""

    def test_pinned_failure_falls_back_to_the_lw2_sheet(self):
        from unittest import mock
        from automations.org_sales_board import section_pull as sp
        seen = []

        def pull(spec, out_dir, page, logfn=None, today=None):
            seen.append((spec.crosstab_sheet, spec.week_pin))
            if spec.week_pin:
                raise RuntimeError("Couldn't find the sheet — saw 1 thumb(s)")
            return "lw2.csv"
        parsed = {"samuel acay": {"Wireless": {MON: 2}}}
        with mock.patch.object(sp, "pull_section_byday", side_effect=pull), \
             mock.patch.object(sp, "parse_byday", return_value=parsed):
            pulls, failed = N.pull_sections(["nds"], TODAY, page=None,
                                            logfn=lambda *a: None)
        self.assertEqual(failed, [])
        self.assertEqual(pulls["nds"], ("Wireless", parsed))
        self.assertEqual(seen[1], (sp.SPECS["nds"].crosstab_sheet + " (LW2)", False))

    def test_both_failing_marks_the_section_failed(self):
        from unittest import mock
        from automations.org_sales_board import section_pull as sp
        with mock.patch.object(sp, "pull_section_byday",
                               side_effect=RuntimeError("no")):
            pulls, failed = N.pull_sections(["nds"], TODAY, page=None,
                                            logfn=lambda *a: None)
        self.assertEqual((pulls, failed), ({}, ["nds"]))


class Calibrate(unittest.TestCase):
    def test_trusted_needs_enough_rows_and_agreement(self):
        self.assertFalse(N.trusted(4, []))
        self.assertTrue(N.trusted(10, ["x"]))
        self.assertFalse(N.trusted(10, ["x", "y"]))


if __name__ == "__main__":
    unittest.main()
