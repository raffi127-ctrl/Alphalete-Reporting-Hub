"""config.BORROWED_TAGGED: anyone on Raf's rows whose name ends in 'GP' (or
another of Carlos's tags) rides the NDS board, no name list (Carlos 2026-11-22)."""
import datetime as dt
import unittest
from unittest import mock

from automations.nds_oof import run as R

D = dt.date(2026, 11, 22)
AT = dt.datetime(2026, 11, 22, 14, 4)
OWN = [{"Rep": "Sebastian Avellaneda", "Total Knocks": "30", "First Knock": "2:01 PM"},
       {"Rep": "Kevin Andres Smith", "Total Knocks": "8", "First Knock": "2:20 PM"}]
RAF = [{"Rep": "Cinthya Reyes GP", "Total Knocks": "41", "First Knock": "1:40 PM", "Talk To's": "9"},
       {"Rep": "Anette Climaco GP", "Total Knocks": "27", "First Knock": "2:05 PM"},
       {"Rep": "Maria Lopez GP", "Total Knocks": "12", "First Knock": "2:15 PM"},
       {"Rep": "Luis Perez GP Road Trip", "Total Knocks": "6", "First Knock": "2:30 PM"},
       {"Rep": "Kevin Smith GP", "Total Knocks": "3", "First Knock": "2:40 PM"},   # also on ours
       {"Rep": "Jon Road Trip", "Total Knocks": "50", "First Knock": "1:31 PM"},   # Raf's road trip
       {"Rep": "Roman Albert RT", "Total Knocks": "44", "First Knock": "1:33 PM"},
       {"Rep": "Gpe Martinez", "Total Knocks": "20", "First Knock": "1:50 PM"},    # 'gp' not a tag here
       {"Rep": "Jorge Gramajo", "Total Knocks": "60", "First Knock": "1:35 PM"}]
LOG = []


def _run(names, tagged=None, own=OWN):
    tagged = {"rafael": ("Rafael Hidalgo", "Carlos Hidalgo")} if tagged is None else tagged
    with mock.patch.object(R, "_borrow_sources",
                           lambda today: {"rafael": (RAF, AT, "ICD Knocks office raf")}), \
         mock.patch.object(R.C, "BORROWED_ROWS", {"rafael": list(names)} if names is not None else {}), \
         mock.patch.object(R.C, "BORROWED_RIDE_LEADERS", {}), \
         mock.patch.object(R.C, "BORROWED_TAGGED", tagged), \
         mock.patch.object(R, "_log", lambda m: LOG.append(m)):
        return R.borrowed_rows(D, list(own))


class GpTag(unittest.TestCase):
    def setUp(self):
        LOG.clear()

    def test_every_gp_row_comes_over_once(self):
        got = [r["Rep"] for r in _run(["Cinthya Reyes"])]
        self.assertEqual(got, ["Cinthya Reyes GP", "Anette Climaco GP", "Maria Lopez GP",
                               "Luis Perez GP Road Trip"])
        self.assertTrue(any("Maria Lopez GP off rafael by name tag" in m for m in LOG), LOG)

    def test_rafs_own_reps_and_road_trips_stay_off(self):
        got = {r["Rep"] for r in _run(["Cinthya Reyes"])}
        for name in ("Jon Road Trip", "Roman Albert RT", "Gpe Martinez", "Jorge Gramajo"):
            self.assertNotIn(name, got)

    def test_a_tagged_rep_already_on_our_rows_is_not_doubled(self):
        got = {r["Rep"] for r in _run([])}
        self.assertNotIn("Kevin Smith GP", got)
        self.assertTrue(any("Kevin Smith GP is already on our own rows" in m for m in LOG), LOG)

    def test_tag_only_owner_with_no_names_still_reads(self):
        got = [r["Rep"] for r in _run(None)]
        self.assertIn("Maria Lopez GP", got)
        self.assertIn("Cinthya Reyes GP", got)

    def test_board_columns_and_as_of_label(self):
        got = _run([])
        for r in got:
            self.assertEqual(set(r), {"Rep", "Total Knocks", "First Knock"})
        shown, relabel = R.with_as_of(got)
        self.assertEqual(relabel.get("Maria Lopez GP"), "Maria Lopez GP (as of 2:04)")

    def test_switch_off_is_the_old_named_list_only(self):
        got = [r["Rep"] for r in _run(["Cinthya Reyes"], tagged={})]
        self.assertEqual(got, ["Cinthya Reyes GP"])


if __name__ == "__main__":
    unittest.main()
