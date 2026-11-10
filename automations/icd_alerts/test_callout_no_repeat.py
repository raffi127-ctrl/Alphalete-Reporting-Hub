"""Back-to-back call-outs never use the same sentence (Megan 2026-11-10:
Sahil's room got "admiring the neighborhood" at 1:03 and again at 1:41)."""
import datetime as dt
import unittest

from automations.icd_alerts import gap_callouts as G

POOL = G.lines_for(None)
WHO = [{"name": "Pat Example", "mins": 35}]


def _wording(text):
    return text.replace("35", "").replace("45", "")


class NoRepeat(unittest.TestCase):
    def test_two_callouts_in_one_clock_hour_differ(self):
        """The bug itself: both halves of an hour drew one sentence."""
        for office in ("sahil", "nigel", "cody", "frank", "jacob", "ryan"):
            for hour in range(9, 21):
                a_at = dt.datetime(2026, 11, 10, hour, 3)
                b_at = dt.datetime(2026, 11, 10, hour, 41)
                a_i = G.template_index("callout", office, a_at, POOL)
                a = G.line(office, WHO, a_at, remember=False)
                b = G.line(office, WHO, b_at, remember=False, last=[G._slot(a_at), a_i])
                self.assertNotEqual(_wording(a), _wording(b), (office, hour))

    def test_a_whole_day_never_repeats_back_to_back(self):
        last, at = None, dt.datetime(2026, 11, 10, 9, 0)
        while at.hour < 21:
            i = G.template_index("callout", "sahil", at, POOL, last)
            if last:
                self.assertNotEqual(i, last[1], at)
            last = [G._slot(at), i]
            at += dt.timedelta(minutes=30)

    def test_rerun_in_the_same_half_hour_repeats_itself(self):
        at = dt.datetime(2026, 11, 10, 13, 3)
        i = G.template_index("callout", "sahil", at, POOL)
        again = G.template_index("callout", "sahil", at.replace(minute=20), POOL, [G._slot(at), i])
        self.assertEqual(i, again)

    def test_junk_marker_is_ignored(self):
        at = dt.datetime(2026, 11, 10, 13, 3)
        want = G.template_index("callout", "sahil", at, POOL)
        for junk in (None, "x", [], {"a": 1}, [1, 2, 3]):
            self.assertEqual(G.template_index("callout", "sahil", at, POOL, junk), want)

    def test_receipts_too(self):
        pool = G.receipt_lines_for(None)
        a_at, b_at = dt.datetime(2026, 11, 10, 14, 5), dt.datetime(2026, 11, 10, 14, 35)
        a_i = G.template_index("receipt", "sahil", a_at, pool)
        b_i = G.template_index("receipt", "sahil", b_at, pool, [G._slot(a_at), a_i])
        self.assertNotEqual(a_i, b_i)


if __name__ == "__main__":
    unittest.main()
