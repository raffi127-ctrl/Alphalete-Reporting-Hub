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
