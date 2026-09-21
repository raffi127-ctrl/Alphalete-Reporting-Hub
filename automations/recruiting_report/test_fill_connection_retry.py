"""A dropped connection on a Sheets READ retries; on a write it does not.

    python -m pytest automations/recruiting_report/test_fill_connection_retry.py -q
"""
from unittest import mock

import requests

from automations.recruiting_report import fill


def _wrapped_with(orig):
    import gspread.http_client as hc
    with mock.patch.object(hc.HTTPClient, "request", orig), \
            mock.patch.object(fill, "_global_retry_installed", False), \
            mock.patch.object(fill.time, "sleep"):
        fill._install_global_retry()
        return hc.HTTPClient.request


def _flaky(fail_times):
    calls = {"n": 0}

    def orig(self, method, *a, **k):
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise requests.exceptions.ConnectionError("Connection aborted.")
        return "ok"
    return orig, calls


def test_read_retries_through_a_dropped_connection():
    orig, calls = _flaky(2)
    w = _wrapped_with(orig)
    with mock.patch.object(fill.time, "sleep"):
        assert w(None, "get", "u") == "ok"
    assert calls["n"] == 3


def test_write_is_not_resent():
    orig, calls = _flaky(1)
    w = _wrapped_with(orig)
    with mock.patch.object(fill.time, "sleep"):
        try:
            w(None, "post", "u")
            assert False, "should have raised"
        except requests.exceptions.ConnectionError:
            pass
    assert calls["n"] == 1
