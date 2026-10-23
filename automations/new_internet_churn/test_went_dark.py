"""detect_went_dark must not flag a rep who is only aging out of the longest bucket.

2026-10-23, Captainship Wireless Churn: Kiarri McBroom filled ONLY the 90-day
block (0/3 → 0/2, every shorter block blank) and then left the pull. Her last
activations simply aged past 90 days, but the run flagged her as dark and held
the report INCOMPLETE.

    python -m unittest automations.new_internet_churn.test_went_dark
"""
import unittest
from unittest import mock

from automations.new_internet_churn import fill

PERIODS = ("0-30", "30", "60", "90")


def _tab(rows_by_name):
    """One rep row per section per name; `rows_by_name[name][period]` is the
    recent pct ('' = blank). Returns (values, sections)."""
    values, sections = [], {}
    for p in PERIODS:
        values.append([f"HDR {p}"])
        sections[p] = {"header_row": len(values), "rep_rows": {}}
        for name, per in rows_by_name.items():
            values.append([name, per.get(p, ""), ""])
            sections[p]["rep_rows"][name.lower()] = len(values)
    return values, sections


class WentDarkTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch("automations.shared.terminated_icds.terminated_lookup",
                       return_value=lambda _n: False)
        p.start()
        self.addCleanup(p.stop)

    def test_only_longest_bucket_is_aging_out(self):
        values, sections = _tab({"Kiarri McBroom": {"90": "0.00%"}})
        self.assertEqual(fill.detect_went_dark(values, sections, {"reps": {}}), {})

    def test_shorter_bucket_history_still_flags(self):
        values, sections = _tab({"Eveliz Roca": {"60": "5.00%", "90": "4.00%"}})
        self.assertEqual(fill.detect_went_dark(values, sections, {"reps": {}}),
                         {"60": ["Eveliz Roca"], "90": ["Eveliz Roca"]})

    def test_present_rep_is_never_dark(self):
        values, sections = _tab({"Ana Diaz": {"30": "1.00%", "90": "2.00%"}})
        parsed = {"reps": {"Ana Diaz": {"90": {"pct": "2.00%"}}}}
        self.assertEqual(fill.detect_went_dark(values, sections, parsed), {})


if __name__ == "__main__":
    unittest.main()
