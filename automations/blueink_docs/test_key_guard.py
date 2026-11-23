"""The send must never go out of another office's Blue Ink account.

python -m unittest automations.blueink_docs.test_key_guard
"""
import unittest
from pathlib import Path
from unittest import mock

from automations.blueink_docs import config as C


class KeyBelongsToTheOffice(unittest.TestCase):
    def _no_own_key(self):
        return mock.patch.object(C, "ECO_CREDS_PATH", Path("/nope/none.json"))

    def _own_key(self):
        """A FILE WITH A KEY IN IT, not a path that happens to exist.

        This used to fake `.exists() -> True` and nothing else, which matched
        what using_own_key() asked at the time. On 2026-11-23 the installer's
        sign-in box created that file with an email and a password and no
        key, and the guard read it as "this office has its own key" about a
        machine still reading Alphalete's -- it would have waved through
        exactly the send it exists to refuse. The guard now asks for a key,
        so the test provides one."""
        import json
        import tempfile
        path = Path(tempfile.mkdtemp()) / "blueink-creds.json"
        path.write_text(json.dumps({"blueink_api_key": "THEIR-OWN-KEY"}))
        return mock.patch.object(C, "ECO_CREDS_PATH", path)

    def _own_file_but_no_key(self):
        """What the installer actually leaves behind before a key is added."""
        import json
        import tempfile
        path = Path(tempfile.mkdtemp()) / "blueink-creds.json"
        path.write_text(json.dumps({"email": "a@b.com", "password": "pw"}))
        return mock.patch.object(C, "ECO_CREDS_PATH", path)

    def test_a_saved_password_is_not_a_key(self):
        """An office that has typed its sign-in but not pasted a key is still
        reading Alphalete's account, and must still be refused."""
        with self._own_file_but_no_key():
            self.assertRaises(RuntimeError, C.assert_key_belongs_to, "omar")

    def test_alphalete_may_use_the_repo_copy(self):
        # their own machines have always read it; nothing changes for them
        with self._no_own_key():
            for key in ("raf", "Alphalete", "", None):
                C.assert_key_belongs_to(key)

    def test_another_office_without_its_own_key_is_refused(self):
        with self._no_own_key():
            with self.assertRaises(RuntimeError) as got:
                C.assert_key_belongs_to("omar")
        said = str(got.exception)
        # the refusal has to name the office and the path to fix
        self.assertIn("omar", said)
        self.assertIn("ALPHALETE", said)

    def test_an_office_with_its_own_key_may_send(self):
        with self._own_key():
            C.assert_key_belongs_to("omar")

    def test_the_guard_is_not_a_warning(self):
        """A send that succeeds from the wrong account is the worst shape of
        failure: a real contract, and nothing reports it. So it raises."""
        with self._no_own_key():
            self.assertRaises(RuntimeError, C.assert_key_belongs_to, "cyrus")

    def test_using_own_key_follows_the_key(self):
        with self._no_own_key():
            self.assertFalse(C.using_own_key())
        with self._own_key():
            self.assertTrue(C.using_own_key())


if __name__ == "__main__":
    unittest.main()


class NoOfficeEverReadsAnothersAccount(unittest.TestCase):
    """Megan, 2026-11-23: "nothing should fall back to Alphalete's. That's
    specific to Raf. There should never, ever be any overlap with personal
    account information between ICDs."

    The repo copy is Alphalete's own file. On a machine that belongs to an
    office there is no fallback to it at all: their file answers, or nothing
    does. A missing answer has to READ as missing -- quietly answering it out
    of somebody else's account is how a real contract goes to a real person
    from the wrong Blue Ink, with nothing reporting it.
    """

    def _machines(self, eco: dict, repo: dict, is_eco: bool):
        import json
        import tempfile
        d = Path(tempfile.mkdtemp())
        eco_path, repo_root = d / "eco.json", d / "repo"
        repo_root.mkdir()
        if eco is not None:
            eco_path.write_text(json.dumps(eco))
        (repo_root / "blueink-creds.json").write_text(json.dumps(repo))
        return mock.patch.multiple(C, ECO_CREDS_PATH=eco_path,
                                   REPO_ROOT=repo_root,
                                   is_eco_machine=lambda: is_eco)

    def test_an_office_machine_never_reads_the_repo_key(self):
        with self._machines({"email": "a@b.com", "password": "pw"},
                            {"blueink_api_key": "ALPHALETES"}, True), \
             mock.patch.dict("os.environ", {}, clear=True):
            self.assertRaises(RuntimeError, C.api_key)

    def test_an_office_machine_never_reads_the_repo_template(self):
        """A template id is as much theirs as a key: the wrong one sends
        Alphalete's contract bundle to their new start."""
        with self._machines({"blueink_api_key": "THEIRS"},
                            {"envelope_template_id": "T-ALPHALETE"}, True), \
             mock.patch.dict("os.environ", {}, clear=True):
            self.assertRaises(RuntimeError, C.template_id)

    def test_an_office_machine_never_reads_the_repo_sign_in(self):
        with self._machines({"blueink_api_key": "THEIRS"},
                            {"email": "alphalete@x.com", "password": "pw"},
                            True), \
             mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(C.login_creds(), {})

    def test_our_own_machines_are_untouched(self):
        """Alphalete's machines have always read the repo copy, and this
        changes nothing for them -- they carry no office enrollment."""
        with self._machines({"email": "a@b.com", "password": "pw"},
                            {"blueink_api_key": "OURS",
                             "envelope_template_id": "T-1"}, False), \
             mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(C.api_key(), "OURS")
            self.assertEqual(C.template_id(), "T-1")

    def test_an_office_with_its_own_answers_still_gets_them(self):
        with self._machines({"blueink_api_key": "THEIRS",
                             "envelope_template_id": "T-THEIRS"},
                            {"blueink_api_key": "OURS"}, True), \
             mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(C.api_key(), "THEIRS")
            self.assertEqual(C.template_id(), "T-THEIRS")
