"""churn_mix_guard: a New Internet total that is really the Wireless one.

Every case below is a real captainship total read off the sheet on 2026-10-06
(the day the views flipped) or 2026-10-05 (a normal day).

Run:  python -m unittest automations.shared.test_churn_mix_guard
"""
import unittest

from automations.shared.churn_mix_guard import looks_like_wireless


def _t(**periods):
    return {p.replace("d", "").replace("_", "-"): {"num": n, "denom": d}
            for p, (n, d) in periods.items()}


class LooksLikeWireless(unittest.TestCase):

    def test_pat_flipped_view(self):
        ni = _t(d0_30=(40, 1235), d30=(51, 1164), d60=(81, 1318), d90=(156, 1395))
        wl = _t(d0_30=(40, 1235), d30=(51, 1169), d60=(81, 1337), d90=(156, 1431))
        self.assertTrue(looks_like_wireless(ni, wl))

    def test_tony_flipped_view_9pct_apart(self):
        # 4f9c237d's 3% line missed this one.
        ni = _t(d0_30=(25, 669), d30=(17, 572))
        wl = _t(d0_30=(25, 606), d30=(17, 539))
        self.assertTrue(looks_like_wireless(ni, wl))

    def test_raf_flipped_view_identical(self):
        ni = _t(d0_30=(76, 2145), d30=(75, 1791))
        self.assertTrue(looks_like_wireless(ni, dict(ni)))

    def test_real_day_is_not_flagged(self):
        ni = _t(d0_30=(83, 3362), d30=(126, 3901))
        wl = _t(d0_30=(41, 1246), d30=(50, 1193))
        self.assertFalse(looks_like_wireless(ni, wl))

    def test_one_period_differing_clears_it(self):
        ni = _t(d0_30=(40, 1235), d30=(126, 3901))
        wl = _t(d0_30=(40, 1235), d30=(51, 1169))
        self.assertFalse(looks_like_wireless(ni, wl))

    def test_no_churn_anywhere_is_not_evidence(self):
        ni = _t(d0_30=(0, 40), d30=(1, 42))
        wl = _t(d0_30=(0, 41), d30=(1, 40))
        self.assertFalse(looks_like_wireless(ni, wl))

    def test_missing_counts_or_totals(self):
        self.assertFalse(looks_like_wireless({}, {}))
        self.assertFalse(looks_like_wireless(None, _t(d30=(5, 100))))
        self.assertFalse(looks_like_wireless({"30": {"pct": "5%"}},
                                             {"30": {"pct": "5%"}}))


if __name__ == "__main__":
    unittest.main()
