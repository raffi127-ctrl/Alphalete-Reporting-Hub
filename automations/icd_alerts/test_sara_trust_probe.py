"""The SaraPlus trust probe: what it files, and that it never costs a read.

    python -m unittest automations.icd_alerts.test_sara_trust_probe
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import sara_read as SR


class _Ctx:
    def __init__(self, cookies):
        self._c = cookies

    def cookies(self):
        return self._c


NOW = dt.datetime(2026, 10, 24, 10, 0, 0)


class TrustSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = [mock.patch.object(SR, "TRUST_IP_LOG_PATH", self.tmp / "ip.json"),
                  mock.patch.object(SR, "browser_id", lambda: "ua"),
                  mock.patch.object(SR, "session_evidence", lambda now=None: "session evidence: x")]
        for p in self.p:
            p.start()
        SR._IP_CACHE.clear()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def test_cookie_names_and_expiry_never_values(self):
        exp = (NOW + dt.timedelta(days=30)).timestamp()
        ctx = _Ctx([
            {"name": ".ASPXAUTH", "domain": "www.saraplus.com", "value": "SECRET1", "expires": exp},
            {"name": "SARAPlus", "domain": "www.saraplus.com", "value": "SECRET2", "expires": -1},
            {"name": "other", "domain": "google.com", "value": "x", "expires": -1},
        ])
        with mock.patch.object(SR, "_ip_hash", lambda now: "abc123"):
            out = SR.trust_snapshot("code-wall", ctx, NOW)
        self.assertIn(".ASPXAUTH @ www.saraplus.com: expires 2026-11-23", out)
        self.assertIn("SARAPlus @ www.saraplus.com: session-only", out)
        self.assertNotIn("SECRET", out)
        self.assertNotIn("google.com", out)
        self.assertIn("ip hash now: abc123", out)

    def test_ip_history_adds_only_on_change(self):
        SR._ip_history("aaa", NOW)
        SR._ip_history("aaa", NOW + dt.timedelta(hours=1))
        rows = SR._ip_history("bbb", NOW + dt.timedelta(hours=2))
        self.assertEqual([r["ip"] for r in rows], ["aaa", "bbb"])

    def test_failed_ip_lookup_is_a_question_mark(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("offline")):
            self.assertEqual(SR._ip_hash(NOW), "?")

    def test_ip_is_hashed_not_sent(self):
        class _R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n):
                return b"203.0.113.7"
        with mock.patch("urllib.request.urlopen", return_value=_R()):
            h = SR._ip_hash(NOW)
        self.assertEqual(len(h), 10)
        self.assertNotIn("203", h)


class NoteTrustNeverRaisesTests(unittest.TestCase):
    def test_broken_ctx_and_relay_do_not_raise(self):
        class _Bad:
            def cookies(self):
                raise RuntimeError("closed")
        with mock.patch("automations.icd_alerts.relay.report_fault",
                        side_effect=RuntimeError("down")):
            SR.note_trust("session-lost", _Bad())   # must not raise

    def test_files_a_stamped_probe_stage(self):
        seen = {}

        def _rf(stage, summary, detail="", **kw):
            seen.update(stage=stage, summary=summary, detail=detail)
            return True
        with mock.patch("automations.icd_alerts.relay.report_fault", _rf), \
                mock.patch.object(SR, "trust_snapshot", lambda e, c, n: "detail"):
            SR.note_trust("fresh-login-ok", _Ctx([]))
        self.assertTrue(seen["stage"].startswith("probe-"))
        self.assertIn("fresh-login-ok", seen["summary"])


if __name__ == "__main__":
    unittest.main()
