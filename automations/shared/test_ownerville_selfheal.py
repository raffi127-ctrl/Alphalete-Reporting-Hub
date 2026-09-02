"""A dead ownerville session must mint a new one, not stop the fleet.

The session step had no self-heal because the login form was believed
impossible unattended — "the Cloudflare 'verify you are human' check can't be
cleared headless". It can: the box clears itself if you leave it alone before
submitting (Megan 2026-09-01, "you just wait 30 sec before hitting submit on
the PW"). At a 3s pause the submit landed mid-check and the login failed, which
is what made a human look mandatory.

The cost of not having it: on 2026-09-01 the token died twice in one evening,
and each time every board stopped until a person re-minted it by hand.

Offline: refresh_ownerville and the storage-state reuse are both stubbed.
"""
import unittest

from automations.shared import tableau_patchright as TP


class _Page:
    context = object()
    url = "https://v2.ownerville.com/"


class SelfHeal(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._saved = {
            "reuse": TP._reuse_ownerville_storage_state,
            "valid": TP._ownerville_session_valid,
            "tried": TP._OV_SELFHEAL_TRIED,
        }
        TP._ownerville_session_valid = lambda page, verbose=True: False
        TP._OV_SELFHEAL_TRIED = False

    def tearDown(self):
        TP._reuse_ownerville_storage_state = self._saved["reuse"]
        TP._ownerville_session_valid = self._saved["valid"]
        TP._OV_SELFHEAL_TRIED = self._saved["tried"]

    def _reuse(self, results):
        """storage_state reuse: pops the next canned answer per call."""
        seq = list(results)

        def _f(_ctx, _page, _verbose=True):
            self.calls.append("reuse")
            return seq.pop(0) if seq else False
        TP._reuse_ownerville_storage_state = _f

    def _refresh(self, ok):
        import automations.shared.appstream_autorenew as AR
        self._saved.setdefault("refresh", AR.refresh_ownerville)

        def _f(verbose=True):
            self.calls.append("refresh")
            return ok
        AR.refresh_ownerville = _f
        self.addCleanup(setattr, AR, "refresh_ownerville",
                        self._saved["refresh"])

    def test_a_dead_session_is_reminted_and_the_run_continues(self):
        self._reuse([False, True])      # dead, then live after the re-mint
        self._refresh(True)
        TP._ensure_ownerville_logged_in(_Page(), verbose=False)
        self.assertEqual(self.calls, ["reuse", "refresh", "reuse"])

    def test_a_live_session_never_touches_the_login(self):
        """The mint is a repair, not part of the happy path — it must not run
        when the saved session is fine."""
        self._reuse([True])
        self._refresh(True)
        TP._ensure_ownerville_logged_in(_Page(), verbose=False)
        self.assertNotIn("refresh", self.calls)

    def test_a_failed_mint_still_raises_the_real_error(self):
        self._reuse([False])
        self._refresh(False)
        with self.assertRaises(RuntimeError) as cm:
            TP._ensure_ownerville_logged_in(_Page(), verbose=False)
        self.assertIn("session expired or missing", str(cm.exception))

    def test_it_is_tried_once_per_process_not_once_per_call(self):
        """A wrong password must cost ONE login attempt and a clear error, not
        a retry loop against the account."""
        self._reuse([False, False, False, False])
        self._refresh(False)
        for _ in range(3):
            with self.assertRaises(RuntimeError):
                TP._ensure_ownerville_logged_in(_Page(), verbose=False)
        self.assertEqual(self.calls.count("refresh"), 1)


if __name__ == "__main__":
    unittest.main()
