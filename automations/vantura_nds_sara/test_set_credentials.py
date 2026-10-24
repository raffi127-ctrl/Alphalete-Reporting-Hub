"""The NDS SaraPlus login file: written here, pushed to Lucy 2, landed there
-- fakes only, no prompts, no queue, no network.

    python -m unittest automations.vantura_nds_sara.test_set_credentials -v

Pins: the file lands at config.creds_path() at mode 600 with exactly the two
keys; the password is never printed; --push goes through mini_control's
redacted transit under the key `saraplus-nds-creds`; that key is whitelisted
on BOTH sides of the transit (push_cred_file reads it here, set_cred_file
installs it on the runner) and resolves to the same path run.py reads; and
it is a whole-file key, never merged.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.day_orchestrator import mini_control as mc
from automations.vantura_nds_sara import config as CFG
from automations.vantura_nds_sara import set_credentials as SC

EMAIL = "nds@example.com"
PW = "Hunter2-not-echoed"


class _Home:
    """A scratch HOME, so Path.home() -- in config AND in mini_control's
    whitelist lambdas -- lands in a directory the test owns."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.dict(os.environ, {"HOME": self.tmp.name})
        self.patch.start()
        return Path(self.tmp.name)

    def __exit__(self, *exc):
        self.patch.stop()
        self.tmp.cleanup()


class WhitelistTest(unittest.TestCase):
    def test_key_is_whitelisted_and_resolves_to_the_file_run_reads(self):
        self.assertIn(CFG.CRED_KEY, mc._CRED_FILES)
        self.assertEqual(CFG.CRED_KEY, "saraplus-nds-creds")
        with _Home() as home:
            self.assertEqual(mc._CRED_FILES[CFG.CRED_KEY](), CFG.creds_path())
            self.assertEqual(mc._CRED_FILES[CFG.CRED_KEY](),
                             home / ".config" / "recruiting-report" / "saraplus-nds-creds.json")

    def test_its_own_key_not_another_readers(self):
        # One key per account AND per reader (config.py): the three other
        # SaraPlus logins keep their own files.
        others = {"saraplus-creds", "saraplus-creds-b2b", "saraplus-creds-nds"}
        self.assertTrue(others <= set(mc._CRED_FILES))
        paths = {k: mc._CRED_FILES[k]() for k in others | {CFG.CRED_KEY}}
        self.assertEqual(len(set(paths.values())), 4)

    def test_whole_file_never_merged(self):
        self.assertNotIn(CFG.CRED_KEY, mc._CRED_FILES_MERGE)
        self.assertNotIn(CFG.CRED_KEY, mc._CRED_PUSH_FIELDS)

    def test_set_cred_file_installs_it_at_mode_600(self):
        with _Home():
            ok, msg = mc._action_set_cred_file(
                "%s %s" % (CFG.CRED_KEY, json.dumps({"email": EMAIL, "password": PW})))
            self.assertTrue(ok, msg)
            path = CFG.creds_path()
            self.assertTrue(path.exists())
            self.assertEqual(json.loads(path.read_text()), {"email": EMAIL, "password": PW})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertNotIn(PW, msg)
            # the way `lucy` ships it: shlex-quoted JSON, unwrapped on landing
            ok, msg = mc._action_set_cred_file(
                "%s '%s'" % (CFG.CRED_KEY, json.dumps({"email": EMAIL, "password": PW + "x"})))
            self.assertTrue(ok, msg)
            self.assertEqual(json.loads(path.read_text())["password"], PW + "x")
            self.assertIn("unwrapped shlex quoting", msg)
            # run.py's own loader reads what landed
            cr, why, exists = CFG.creds_status()
            self.assertEqual(cr, {"email": EMAIL, "password": PW + "x"})
            self.assertNotIn(PW, why)

    def test_push_cred_file_queues_the_file_under_the_key(self):
        with _Home():
            SC.write_creds(EMAIL, PW)
            with mock.patch.object(mc, "_this_box", return_value="carlos-laptop"), \
                 mock.patch.object(mc, "_machine_profile", return_value="laptop"), \
                 mock.patch.object(mc, "enqueue") as enq:
                ok, msg = mc._action_push_cred_file("%s Lucy 2" % CFG.CRED_KEY)
            self.assertTrue(ok, msg)
            self.assertIn("queued saraplus-nds-creds", msg)
            self.assertIn("'Lucy 2'", msg)
            self.assertNotIn(PW, msg)
            enq.assert_called_once()
            action, args = enq.call_args.args[:2]
            self.assertEqual(action, "set_cred_file")
            key, payload = args.split(None, 1)
            self.assertEqual(key, CFG.CRED_KEY)
            self.assertEqual(json.loads(payload), {"email": EMAIL, "password": PW})
            self.assertEqual(enq.call_args.kwargs["machine"], "Lucy 2")
            self.assertTrue(enq.call_args.kwargs["auto"])

    def test_push_without_the_file_refuses(self):
        with _Home():
            with mock.patch.object(mc, "_this_box", return_value="carlos-laptop"), \
                 mock.patch.object(mc, "enqueue") as enq:
                ok, msg = mc._action_push_cred_file("%s Lucy 2" % CFG.CRED_KEY)
            self.assertFalse(ok)
            self.assertIn("couldn't read saraplus-nds-creds.json here", msg)
            self.assertEqual(enq.call_count, 0)

    def test_an_unknown_key_is_refused_on_both_sides(self):
        ok, msg = mc._action_set_cred_file('saraplus-nds-cred {"email": "a", "password": "b"}')
        self.assertFalse(ok)
        self.assertIn("unknown file-key", msg)
        with mock.patch.object(mc, "_this_box", return_value="carlos-laptop"):
            ok, msg = mc._action_push_cred_file("saraplus-nds-cred Lucy 2")
        self.assertFalse(ok)
        self.assertIn("unknown file-key", msg)


class SetCredentialsTest(unittest.TestCase):
    def main(self, argv, answers, push=None):
        """Run SC.main with `ask` answering in order; returns (rc, stdout)."""
        answers = list(answers)
        out = io.StringIO()
        pushes = []

        def fake_push(args):
            pushes.append(args)
            return push if push is not None else (True, "queued saraplus-nds-creds (58 chars) onto 'Lucy 2' — Args blank on landing")

        with mock.patch.object(SC, "ask", side_effect=lambda *a, **k: answers.pop(0)), \
             mock.patch.object(mc, "_action_push_cred_file", side_effect=fake_push), \
             contextlib.redirect_stdout(out):
            rc = SC.main(argv)
        self.pushes = pushes
        return rc, out.getvalue()

    def test_writes_the_file_600_and_prints_no_password(self):
        with _Home():
            rc, out = self.main([], [EMAIL, PW, PW])
            self.assertEqual(rc, 0)
            path = CFG.creds_path()
            self.assertEqual(json.loads(path.read_text()), {"email": EMAIL, "password": PW})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertIn("wrote %s (mode 600) for %s" % (path, EMAIL), out)
            self.assertIn('Next: lucy push_cred_file saraplus-nds-creds "Lucy 2"', out)
            self.assertNotIn(PW, out)
            self.assertNotIn(str(len(PW)), out.split("wrote")[1].split("for")[0])
            self.assertEqual(self.pushes, [])
            # Enter keeps the email already on file
            self.assertEqual(SC.current_email(), EMAIL)

    def test_push_goes_through_the_redacted_transit_under_the_key(self):
        with _Home():
            rc, out = self.main(["--push", "Lucy 2", "--email", EMAIL], [PW, PW])
            self.assertEqual(rc, 0)
            self.assertEqual(self.pushes, ["saraplus-nds-creds Lucy 2"])
            self.assertIn("pushed: queued saraplus-nds-creds", out)
            self.assertIn("lucy rerun vantura_nds_sara --preflight", out)
            self.assertNotIn(PW, out)

    def test_failed_push_exits_1_but_the_file_stays(self):
        with _Home():
            rc, out = self.main(["--push", "Lucy 2", "--email", EMAIL], [PW, PW],
                                push=(False, "unknown file-key 'saraplus-nds-creds'"))
            self.assertEqual(rc, 1)
            self.assertIn("push FAILED: unknown file-key", out)
            self.assertTrue(CFG.creds_path().exists())

    def test_mismatch_cancel_and_no_email_write_nothing(self):
        with _Home():
            rc, out = self.main([], [EMAIL, PW, PW + "typo"])
            self.assertEqual(rc, 1)
            self.assertIn("didn't match", out)
            self.assertFalse(CFG.creds_path().exists())
            rc, out = self.main([], [EMAIL, ""])
            self.assertEqual(rc, 1)
            self.assertIn("no password given", out)
            rc, out = self.main([], [""])
            self.assertEqual(rc, 1)
            self.assertIn("no email given", out)
            self.assertFalse(CFG.creds_path().exists())
            self.assertNotIn(PW, out)

    def test_docstring_carries_the_exact_command(self):
        self.assertIn('python -m automations.vantura_nds_sara.set_credentials --push "Lucy 2"',
                      SC.__doc__)
        self.assertEqual(CFG.SET_CREDENTIALS_CMD,
                         'python -m automations.vantura_nds_sara.set_credentials --push "Lucy 2"')


if __name__ == "__main__":
    unittest.main()
