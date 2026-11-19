"""The board refresh only counts when the web app says so. Offline: requests is faked.

11/18 11:13: apiRefresh ran past Apps Script's 6-minute limit, Google answered
with an HTML error page, and the run put that page in its summary as if the
refresh had worked -- the tie-out then read a half-synced P&L.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.vantura_payroll import run as R

HTML = "<!DOCTYPE html><html><head><title>Error</title></head><body>Exceeded maximum execution time</body></html>"


class _Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code, self.ok = text, status, 200 <= status < 300


def _run(*replies):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params["action"])
        r = replies[len(calls) - 1]
        if isinstance(r, Exception):
            raise r
        return r
    with mock.patch("requests.get", side_effect=fake_get):
        line = R._trigger_refresh("https://example.invalid/exec", log=lambda *a: None)
    return line, calls


class TriggerRefreshTest(unittest.TestCase):
    def test_a_clean_refresh(self):
        line, calls = _run(_Resp('{"ok":true,"action":"refresh","result":"refreshed"}'))
        self.assertEqual(line, "refresh: refreshed")
        self.assertEqual(calls, ["refresh"])

    def test_the_6_minute_page_runs_the_sync_alone(self):
        line, calls = _run(_Resp(HTML), _Resp('{"ok":true,"action":"sync","result":"synced"}'))
        self.assertEqual(calls, ["refresh", "sync"])
        self.assertTrue(line.startswith("refresh: rebuilt, P&L re-synced"), line)
        self.assertEqual(R.payroll_holes(line, "", "", ""), [])

    def test_both_fail_is_a_hole(self):
        line, _ = _run(_Resp(HTML), _Resp(HTML))
        self.assertTrue(line.startswith("refresh: FAILED"), line)
        self.assertIn("refresh did not finish -- the P&L may be half-synced",
                      R.payroll_holes(line, "", "", ""))

    def test_an_older_board_without_sync_is_a_hole(self):
        line, _ = _run(_Resp(HTML), _Resp('{"ok":true,"action":"sync","result":"unknown action"}'))
        self.assertTrue(line.startswith("refresh: FAILED"), line)

    def test_http_error_then_sync_network_error(self):
        import requests
        line, calls = _run(_Resp("busy", 503), requests.ConnectionError("reset"))
        self.assertEqual(calls, ["refresh", "sync"])
        self.assertTrue(line.startswith("refresh: FAILED"), line)

    def test_html_never_lands_in_the_summary(self):
        line, _ = _run(_Resp(HTML), _Resp(HTML))
        self.assertNotIn("<", line)


if __name__ == "__main__":
    unittest.main()
