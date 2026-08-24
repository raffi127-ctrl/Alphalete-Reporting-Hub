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


if __name__ == "__main__":
    unittest.main()
