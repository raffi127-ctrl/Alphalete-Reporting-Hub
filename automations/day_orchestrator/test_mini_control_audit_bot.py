"""The audit-bot queue window: list, peek, quarantine — and nothing deletes.

WHY THIS EXISTS (2026-10-19). Raf's audit watcher crash-looped all night on
Lucy 1 while Megan was off the office LAN, and the queue could not see
~/2nd-rd-audits at all. These pin the three rules that make the window safe:
it never leaves the bot folder, it never copies a secrets file, and a
quarantine is a MOVE that refuses to overwrite.

    python -m unittest automations.day_orchestrator.test_mini_control_audit_bot
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.day_orchestrator import mini_control as mc

LOGS = Path(mc.REPO_ROOT) / "output" / "logs"


class AuditBotWindow(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.rt = self.home / "2nd-rd-audits"
        (self.rt / "inbox").mkdir(parents=True)
        (self.rt / ".runtime").mkdir()
        (self.rt / ".runtime" / "watcher.log").write_text("line1\nTraceback: boom\n")
        (self.rt / ".runtime" / ".env").write_text("SLACK_BOT_TOKEN=xoxb-secret\n")
        (self.rt / "inbox" / "poison.mp4").write_bytes(b"\0" * 10)
        p = mock.patch.object(mc.Path, "home", return_value=self.home)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        self.made = []
        self.addCleanup(lambda: [f.unlink() for f in self.made if f.exists()])

    def _track(self, msg):
        for stem in [w.strip("`") for w in msg.split() if w.startswith("auditbot-")]:
            self.made.append(LOGS / f"{stem}.log")

    def test_ls_lists_inbox(self):
        ok, msg = mc._action_audit_bot_ls("inbox")
        self._track(msg)
        self.assertTrue(ok, msg)
        self.assertIn("1 entries", msg)
        dump = (LOGS / f"{msg.split('logtail ')[1].split()[0]}.log").read_text()
        self.assertIn("poison.mp4", dump)

    def test_peek_copies_log(self):
        ok, msg = mc._action_audit_bot_peek(".runtime/watcher.log")
        self._track(msg)
        self.assertTrue(ok, msg)
        stem = msg.split("logtail ")[1].split()[0]
        self.assertIn("Traceback: boom", (LOGS / f"{stem}.log").read_text())

    def test_peek_refuses_secrets_and_escapes(self):
        self.assertFalse(mc._action_audit_bot_peek(".runtime/.env")[0])
        self.assertFalse(mc._action_audit_bot_peek("../../.ssh/id_ed25519")[0])

    def test_quarantine_moves_never_deletes(self):
        ok, msg = mc._action_audit_bot_quarantine("inbox/poison.mp4")
        self.assertTrue(ok, msg)
        self.assertFalse((self.rt / "inbox" / "poison.mp4").exists())
        self.assertEqual((self.rt / "failed" / "poison.mp4").stat().st_size, 10)

    def test_quarantine_refuses_overwrite(self):
        (self.rt / "failed").mkdir()
        (self.rt / "failed" / "poison.mp4").write_bytes(b"old")
        ok, _ = mc._action_audit_bot_quarantine("inbox/poison.mp4")
        self.assertFalse(ok)
        self.assertTrue((self.rt / "inbox" / "poison.mp4").exists())
        self.assertEqual((self.rt / "failed" / "poison.mp4").read_bytes(), b"old")

    def test_quarantine_refuses_escape(self):
        self.assertFalse(mc._action_audit_bot_quarantine("../../etc/hosts")[0])

    def test_actions_registered_and_off_budget(self):
        for a in ("audit_bot_ls", "audit_bot_peek", "audit_bot_quarantine"):
            self.assertIn(a, mc.ACTIONS)
            self.assertIn(a, mc.PLUMBING_ACTIONS)


if __name__ == "__main__":
    unittest.main()
