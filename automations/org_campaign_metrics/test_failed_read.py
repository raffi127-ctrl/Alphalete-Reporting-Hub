"""A failed Sheets read stops the stamper; it is never read as an empty tab.

    python -m unittest automations.org_campaign_metrics.test_failed_read

2026-11-20: the stamper died on Lucy 2 with KeyError 'sheets'. A 429 body
({"error": ...}) came back from the first read, and the code indexed it as data.
The same pattern one read later (`.get("values", [])`) would have turned that 429
into "the Campaign Log is empty". upsert_values / upsert_goals would then have
rewritten J:N and P:R from row 2 with only the incoming rows, wiping stored
weeks and Carlos's typed goals.
"""
import unittest
from unittest import mock

from automations.org_campaign_metrics import sheet as SH


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


class _Session:
    """Answers GETs from a script; records every POST (a write)."""

    def __init__(self, gets):
        self.gets = list(gets)
        self.posts = []

    def get(self, url, params=None):
        return self.gets.pop(0)

    def post(self, url, json=None):
        self.posts.append((url, json))
        return _Resp(200, {})


QUOTA = _Resp(429, {"error": {"code": 429, "message": "Quota exceeded"}})
META = _Resp(200, {"sheets": [{"properties": {"title": SH.TAB, "sheetId": 7}}]})


@mock.patch.object(SH.time, "sleep", lambda s: None)
class FailedRead(unittest.TestCase):

    def test_a_429_that_clears_is_retried(self):
        S = _Session([QUOTA, META])
        self.assertEqual(SH.ensure_tab(S, log=lambda *a: None), 7)

    def test_a_429_that_never_clears_raises_not_keyerror(self):
        S = _Session([QUOTA, QUOTA, QUOTA])
        with self.assertRaises(RuntimeError) as cm:
            SH.ensure_tab(S, log=lambda *a: None)
        self.assertIn("429", str(cm.exception))

    def test_a_failed_values_read_writes_nothing(self):
        """THE ONE THAT WOULD HAVE WIPED THE LOG."""
        S = _Session([META, QUOTA, QUOTA, QUOTA])
        with self.assertRaises(RuntimeError):
            SH.upsert_values(S, [("Carlos Hidalgo", "2026-11-22", 1, "288")],
                             log=lambda *a: None)
        self.assertEqual(S.posts, [])

    def test_a_failed_goals_read_writes_nothing(self):
        S = _Session([META, QUOTA, QUOTA, QUOTA])
        with self.assertRaises(RuntimeError):
            SH.upsert_goals(S, [("Carlos Hidalgo", 1, "300")], seed_only=True,
                            log=lambda *a: None)
        self.assertEqual(S.posts, [])

    def test_an_empty_range_is_still_empty(self):
        """A 200 with no 'values' key is a genuinely empty block, not an error."""
        S = _Session([META, _Resp(200, {"range": "x"})])
        changed = SH.upsert_values(S, [("Carlos Hidalgo", "2026-11-22", 1, "288")],
                                   log=lambda *a: None)
        self.assertEqual(changed, 1)
        self.assertEqual(len(S.posts), 1)


if __name__ == "__main__":
    unittest.main()
