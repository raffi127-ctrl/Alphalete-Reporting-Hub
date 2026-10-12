"""_fetch_csv: once Tableau says "empty" (200, tiny body), a later 500 must not
replace that answer — the callers' status=200 guards read it as "no rows yet".
2026-10-12: 200/1, 200/1, 500/455 → the SCI pass dropped every b2b value.

    python -m unittest automations.att_order_log.test_fetch_csv_empty
"""
import unittest
from unittest import mock

from automations.att_order_log import run as R


class _Resp:
    def __init__(self, status, n):
        self.status, self._b = status, b"x" * n

    def body(self):
        return self._b


class _Page:
    def __init__(self, answers):
        self._a = list(answers)
        self.context = self
        self.request = self

    def get(self, url, timeout=None):
        return self._a.pop(0)


def _fetch(answers):
    with mock.patch.object(R, "_CSV_RETRY_WAIT", 0):
        return R._fetch_csv(_Page(answers), "u", log=lambda *a: None)


class FetchCsvEmpty(unittest.TestCase):
    def test_late_500_keeps_the_empty_answer(self):
        with self.assertRaises(RuntimeError) as cm:
            _fetch([_Resp(200, 1), _Resp(200, 1), _Resp(500, 455)])
        self.assertIn("status=200", str(cm.exception))

    def test_all_500_is_still_an_outage(self):
        with self.assertRaises(RuntimeError) as cm:
            _fetch([_Resp(500, 455)] * 3)
        self.assertIn("status=500", str(cm.exception))

    def test_real_export_returns(self):
        self.assertEqual(len(_fetch([_Resp(500, 455), _Resp(200, 5000)])), 5000)


if __name__ == "__main__":
    unittest.main()
