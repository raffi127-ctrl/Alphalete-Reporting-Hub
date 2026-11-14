"""Churn by Rep: worst 0-30 day churn at the top, best at the bottom
(Carlos 2026-11-14).

  python -m unittest automations.nds_metrics.test_churn_by_rep_order
"""
import unittest

from automations.nds_metrics import run as R


def _d(act, disc, act60=0, disc60=0):
    return {"0-30 Day": {"act": act, "disc": disc}, "31-60 Day": {"act": act60, "disc": disc60}}


class Order(unittest.TestCase):
    def test_worst_first_ties_and_blanks(self):
        agg = {("__TOTAL__", ""): _d(100, 10),
               ("Andrew", "WIRELESS"): _d(16, 0),
               ("Aaron", "WIRELESS"): _d(11, 2),             # 18.2%
               ("Rodolfo", "WIRELESS"): _d(17, 5),           # 29.4%  -> top
               ("Jacob", "WIRELESS"): _d(15, 5),             # 33.3%  -> above Rodolfo
               ("Elisa", "AIR"): _d(1, 1),                   # 100% on Air ...
               ("Elisa", "WIRELESS"): _d(6, 0),              # ... 1/7 = 14.3% across products
               ("Yahir", "AIR"): _d(1, 0),
               ("Yahir", "WIRELESS"): _d(5, 1),              # 1/6 = 16.7%
               ("Zed", "WIRELESS"): _d(0, 0, act60=4, disc60=1),   # no 0-30 activations -> last
               ("Brianna", "AIR"): _d(1, 1)}                 # 100%
        order = R.churn_rep_order(agg)
        reps = []
        for rep, _p in order:
            if rep not in reps:
                reps.append(rep)
        self.assertEqual(reps, ["Brianna", "Jacob", "Rodolfo", "Aaron", "Yahir", "Elisa", "Andrew", "Zed"])
        self.assertEqual([p for r, p in order if r == "Elisa"], ["AIR", "WIRELESS"])   # products together, alphabetical
        self.assertNotIn("__TOTAL__", reps)

    def test_tie_breaks_more_disconnects_then_more_activated_then_name(self):
        agg = {("B", "W"): _d(10, 1), ("A", "W"): _d(10, 1), ("C", "W"): _d(20, 2), ("D", "W"): _d(20, 3)}
        reps = [r for r, _p in R.churn_rep_order(agg)]
        self.assertEqual(reps, ["D", "C", "A", "B"])   # 15% first; 10% ties: C (2 disc) then A/B by name


if __name__ == "__main__":
    unittest.main()


class ThreeTables(unittest.TestCase):
    """2026-11-14: wireless non-BYOD / wireless BYOD / Air, national average on top."""

    def test_section_for(self):
        self.assertEqual(R.churn_section_for("WIRELESS", {"wireless_ip": "BYOD", "package": "", "device": "XT2215-1"}), "byod")
        self.assertEqual(R.churn_section_for("WIRELESS", {"wireless_ip": "Next36", "package": "AT&T Premium 2.0",
                                                          "device": "iPhone 18 Pro - 256GB - Black"}), "nonbyod")
        self.assertEqual(R.churn_section_for("AIR", {}), "air")
        self.assertIsNone(R.churn_section_for("NEW INTERNET", {}))
        self.assertIsNone(R.churn_section_for("", {}))

    def test_national_average_parses_the_view(self):
        import tempfile, pathlib
        from automations.office_metrics import nds_churn as NC
        hdr = "Owner & Office\tRep\tColor\tMeasure\t0-30 Day\t30 Day\t60 Day\t90 Day\t120 Day"
        lines = [hdr,
                 "CARLOS HIDALGO\tAna\tRed\tChurn Rate\t12.5%\t\t\t\t",
                 "\t\tTotal\tDisconnect Count Churn\t1\t\t\t\t",
                 "\t\tTotal\tActivated SPE/SP\t8\t\t\t\t",
                 "ZAID ARABYAT\tBen\tGreen\tChurn Rate\t2.0%\t1.0%\t\t\t",
                 "\t\tTotal\tDisconnect Count Churn\t2\t1\t\t\t",
                 "\t\tTotal\tActivated SPE/SP\t100\t100\t\t\t",
                 "Average\t\t\tChurn Rate\t2.8%\t1.0%\t\t\t",
                 "\t\t\tDisconnect Count Churn\t3\t1\t\t\t",
                 "\t\t\tActivated SPE/SP\t108\t100\t\t\t"]
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "view.csv"
            p.write_bytes(("\n".join(lines)).encode("utf-16"))
            nat = NC.national_average(p)
        self.assertEqual(nat["average"]["0-30"], {"pct": "2.8%", "num": 3.0, "denom": 108.0})
        self.assertEqual(nat["average"]["30"]["pct"], "1.0%")
        self.assertEqual((nat["summed"]["0-30"]["num"], nat["summed"]["0-30"]["denom"]), (3.0, 108.0))
        self.assertEqual(nat["summed"]["0-30"]["pct"], "2.8%")
        self.assertEqual((nat["owners"], nat["reps"]), (2, 2))

