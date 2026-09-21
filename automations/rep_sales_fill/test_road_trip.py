"""Road-trip mode: every Field Status 'RT' row, filled from the order log.

No browser, no Sheet: a tiny grid and a tiny order-log CSV.

    python -m unittest automations.rep_sales_fill.test_road_trip
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.rep_sales_fill import board as B
from automations.rep_sales_fill import order_log as OL
from automations.rep_sales_fill import run as R

MON = dt.date(2026, 9, 21)
SUN = dt.date(2026, 9, 27)


def grid():
    """Row 1 banners + 'Field Status', row 3 sub-headers, reps from row 4.
    Cols: C name | D-G Monday Int/Int Up/DTV/NL | H-K Tuesday | L Field Status."""
    w = 12
    r1 = [""] * w
    r1[3], r1[7], r1[11] = "MON", "TUES", "Field Status"
    r3 = [""] * w
    for start in (3, 7):
        r3[start:start + 4] = ["Int", "Int Up", "DTV", "NL"]
    rows = [r1, [""] * w, r3]
    for name, fs in (("Andrew Sanborn", "RT"),
                     ("Jonathan Malpica (Jonny)", "rt"),
                     ("Jose Angel Medellin", "RT"),
                     ("Somebody Local", "Level 1")):
        r = [""] * w
        r[2], r[11] = name, fs
        rows.append(r)
    t = [""] * w
    t[2] = "TOTALS"
    rows.append(t)
    return rows


def log(rows):
    f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                    encoding="utf-8", newline="")
    f.write("Rep,Order Date,Product Type (Broken Out)\n")
    for r in rows:
        f.write(",".join(r) + "\n")
    f.close()
    return Path(f.name)


class RtRows(unittest.TestCase):
    def test_reads_rt_rows_by_label_any_case(self):
        self.assertEqual([n for _r, n in B.rt_reps(grid())],
                         ["Andrew Sanborn", "Jonathan Malpica (Jonny)",
                          "Jose Angel Medellin"])

    def test_no_field_status_column_means_none(self):
        g = grid()
        g[0][11] = "Something Else"
        self.assertEqual(B.rt_reps(g), [])


class Names(unittest.TestCase):
    def test_board_decorations_and_middle_names(self):
        self.assertTrue(R.same_person("Jonathan Malpica (Jonny)", "Jonathan Malpica"))
        self.assertTrue(R.same_person("Jose Angel Medellin", "Jose Medellin"))
        self.assertFalse(R.same_person("Jose Angel Medellin", "Jose Puerto"))

    def test_log_name_with_a_middle_name_the_board_lacks(self):
        src = log([["Jose Medellin", "9/21/2026", "NEW INTERNET"]])
        days, stats, _ = R.rep_counts(src, "Jose Angel Medellin", MON, SUN)
        self.assertEqual(stats["mine"], 1)
        self.assertEqual(days, {"Monday": {"Int": 1}})

    def test_nickname_in_parentheses_is_dropped(self):
        src = log([["Jonathan Malpica", "9/21/2026", "WIRELESS"]])
        _days, stats, _ = R.rep_counts(src, "Jonathan Malpica (Jonny)", MON, SUN)
        self.assertEqual(stats["mine"], 1)

    def test_sale_dates_cover_every_rep(self):
        src = log([["A B", "9/21/2026", "WIRELESS"], ["C D", "9/22/2026", "VIDEO"]])
        self.assertEqual(OL.sale_dates(src), {MON, MON + dt.timedelta(days=1)})


class Transfers(unittest.TestCase):
    def form(self):
        return [{"row": 5, "to": "Jose Medellin", "from": "Somebody Local",
                 "date": MON, "product": "New Internet"},
                {"row": 6, "to": "$20 bonus", "from": "Jose Medellin",
                 "date": MON, "product": "x"},
                {"row": 7, "to": "Other Rep", "from": "Andrew Sanborn",
                 "date": MON - dt.timedelta(days=1), "product": "DTV"}]

    def test_either_side_this_week_only_no_bonus(self):
        self.assertEqual(list(R.transfer_days(self.form(), "Jose Angel Medellin",
                                              MON, SUN)), ["Monday"])
        self.assertEqual(R.transfer_days(self.form(), "Andrew Sanborn", MON, SUN), {})

    def test_locked_target_day_is_not_overwritten(self):
        g = grid()
        g[4][3] = "2"                          # row 5 = Jonny, Monday Int already 2
        blocks = B.day_blocks(g)
        wanted = {"Monday": {"Int": 1}}
        today = MON + dt.timedelta(days=1)
        free, _h, _l = R.plan_rep(g, 5, blocks, wanted, MON, today, False, {})
        self.assertTrue(any(new == 1 or new == "1" for _a, _m, _o, new in free))
        locked, _h, _l = R.plan_rep(g, 5, blocks, wanted, MON, today, False,
                                    {"Monday": ["form row 5"]})
        self.assertEqual(locked, [])

    def test_today_is_never_written(self):
        g = grid()
        blocks = B.day_blocks(g)
        plan, _h, _l = R.plan_rep(g, 4, blocks, {"Monday": {"Int": 3}}, MON,
                                  MON, False, {})
        self.assertEqual(plan, [])


if __name__ == "__main__":
    unittest.main()
