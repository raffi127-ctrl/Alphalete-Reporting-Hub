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
        m = mock.MagicMock()
        m.exists.return_value = True
        return mock.patch.object(C, "ECO_CREDS_PATH", m)

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

    def test_using_own_key_follows_the_path(self):
        with self._no_own_key():
            self.assertFalse(C.using_own_key())
        with self._own_key():
            self.assertTrue(C.using_own_key())


if __name__ == "__main__":
    unittest.main()
