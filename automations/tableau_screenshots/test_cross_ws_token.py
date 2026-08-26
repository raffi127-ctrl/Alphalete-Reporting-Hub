"""The cross-workspace token preflight (`run._cross_ws_token_missing`).

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.tableau_screenshots.test_cross_ws_token

WHAT THIS GUARDS (Megan 2026-08-24). trang's #freshsuccess-all-leaders lives in
the FRESH SUCCESS Slack, not ours, so it is posted with that workspace's own bot
token. When that token file isn't on the machine the run happens to be on — what
the 8/23 move of the trackers to Lucy 3 changed — the old code quietly kept the
AO 'Lucy' token, which cannot see another workspace at all. Slack answers a
non-member with `channel_not_found`, so the channel got
"#freshsuccess-all-leaders (channel unreadable)" on 8/19 and again on 8/23: a
message that points at a Slack invite when the actual fix is a file on a disk.

So the preflight must name the FILE and the MACHINE, and it must stop the run
from posting that org rather than letting it fail downstream.
"""
from __future__ import annotations

import socket
import unittest
from pathlib import Path

from automations.tableau_screenshots import run


class CrossWsTokenMissingTest(unittest.TestCase):

    def test_missing_token_names_the_file_and_the_machine(self):
        why = run._cross_ws_token_missing(
            "trang", "#freshsuccess-all-leaders", "slack-token-does-not-exist")
        self.assertIn("slack-token-does-not-exist", why)
        self.assertIn(socket.gethostname(), why)
        self.assertIn("#freshsuccess-all-leaders", why)

    def test_it_says_a_different_workspace_not_a_missing_invite(self):
        """The whole failure was reading like a membership problem in OUR
        workspace. The word 'invite' must not be what this alert offers."""
        why = run._cross_ws_token_missing(
            "trang", "#freshsuccess-all-leaders", "slack-token-does-not-exist")
        self.assertIn("DIFFERENT Slack workspace", why)
        self.assertNotIn("nvite", why)

    def test_it_offers_both_fixes(self):
        why = run._cross_ws_token_missing(
            "trang", "#freshsuccess-all-leaders", "slack-token-does-not-exist")
        self.assertIn("Copy the token file", why)
        self.assertIn("from the machine that has it", why)

    def test_an_org_with_no_cross_ws_token_is_not_blocked(self):
        """Every normal org routes through the AO token — this must be silent
        for them or it would stop the whole tracker run."""
        self.assertEqual("", run._cross_ws_token_missing("raf", "#raf", ""))
        self.assertEqual("", run._cross_ws_token_missing("raf", "#raf", None))

    def test_a_present_token_file_is_not_blocked(self):
        import tempfile
        # The helper looks under ~/.config/recruiting-report, so use a name that
        # really is there rather than faking the home directory.
        cfg = Path.home() / ".config" / "recruiting-report"
        cfg.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=cfg, prefix="test-token-",
                                         suffix=".tmp") as fh:
            self.assertEqual("", run._cross_ws_token_missing(
                "trang", "#freshsuccess-all-leaders", Path(fh.name).name))


class OrgSlackTokenRoutingTest(unittest.TestCase):
    """`_org_slack_token` — the same routing, now shared by anything that touches
    a channel. Added 2026-08-26: the tracker header NOTICE went out through the
    AO token for every org, so trang came back `channel_not_found` — the precise
    misread the preflight above exists to prevent, reintroduced by a second code
    path that edits the same channels."""

    def test_a_normal_org_is_left_on_the_default_token(self):
        import os
        os.environ["SLACK_USER_TOKEN"] = "sentinel-ao"
        self.addCleanup(os.environ.pop, "SLACK_USER_TOKEN", None)
        with run._org_slack_token("alphalete", "#alphalete-sales") as missing:
            self.assertEqual("", missing)
            self.assertEqual("sentinel-ao", os.environ["SLACK_USER_TOKEN"])

    def test_a_cross_ws_org_with_no_token_file_yields_the_reason(self):
        """And yields it instead of silently leaving the AO token in place —
        posting/editing with that token is what produced the unreadable alert."""
        import os
        from automations.office_metrics.offices import CROSS_WS_TOKEN_FILES
        if "trang" not in CROSS_WS_TOKEN_FILES:
            self.skipTest("trang is no longer a cross-workspace org")
        cfg = Path.home() / ".config" / "recruiting-report"
        if (cfg / CROSS_WS_TOKEN_FILES["trang"]).exists():
            self.skipTest("this machine HAS the FRESH SUCCESS token")
        os.environ["SLACK_USER_TOKEN"] = "sentinel-ao"
        self.addCleanup(os.environ.pop, "SLACK_USER_TOKEN", None)
        with run._org_slack_token("trang", "#freshsuccess-all-leaders") as why:
            self.assertTrue(why, "a missing cross-ws token must be reported")
            self.assertEqual("sentinel-ao", os.environ["SLACK_USER_TOKEN"])

    def test_the_token_is_restored_even_when_the_body_raises(self):
        """One org's failure must not leave the next org posting as the wrong
        workspace."""
        import os
        import tempfile
        os.environ["SLACK_USER_TOKEN"] = "sentinel-ao"
        self.addCleanup(os.environ.pop, "SLACK_USER_TOKEN", None)
        cfg = Path.home() / ".config" / "recruiting-report"
        cfg.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=cfg, prefix="test-token-",
                                         suffix=".tmp", mode="w") as fh:
            fh.write("other-workspace-token")
            fh.flush()
            from automations.office_metrics import offices as _off
            real = dict(_off.CROSS_WS_TOKEN_FILES)
            _off.CROSS_WS_TOKEN_FILES["_t"] = Path(fh.name).name
            self.addCleanup(lambda: (_off.CROSS_WS_TOKEN_FILES.clear(),
                                     _off.CROSS_WS_TOKEN_FILES.update(real)))
            with self.assertRaises(RuntimeError):
                with run._org_slack_token("_t", "#test") as why:
                    self.assertEqual("", why)
                    self.assertEqual("other-workspace-token",
                                     os.environ["SLACK_USER_TOKEN"])
                    raise RuntimeError("boom")
        self.assertEqual("sentinel-ao", os.environ["SLACK_USER_TOKEN"])


if __name__ == "__main__":
    unittest.main()
