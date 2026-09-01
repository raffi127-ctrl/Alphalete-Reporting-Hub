"""The master pull must refuse a session signed in as a DIFFERENT owner.

The master path (Raf) does not impersonate — it scrapes whatever office the
ownerville session happens to be signed into and publishes it under Raf's name.
The login is a machine-wide credential file, so the session can be someone else
entirely with nothing raising anywhere.

That is not hypothetical. On 2026-09-01 Lucy 1's `ownerville-creds.json` said
`chidalgo`, so every renewal re-established Carlos's office 11580 and wiped the
manual Raf login minutes later. Calvin and Jay failed loudly ("name not found"
— they are not in Carlos's Office Access list), but Raf's board did NOT: the
master pull scraped 11580 and posted it to the Alphalete Partners chat as Raf's
reps. Wrong numbers under the right title are worse than no board, so the
mismatch has to stop the pull.

Offline: no ownerville, no network. The page is a stub that returns a header.
"""
import unittest

from automations.rashad_metrics import knocks_pull as KP

RAF_HEADER = (" RAFAEL HIDALGO - Owner • ALPHALETE SPECIALIZED "
              "MARKETING, INC.-TX (11280) Logout Welcome CEO Dashboard")
CARLOS_HEADER = (" CARLOS HIDALGO - Owner • ALPHALETE SPECIALIZED "
                 "MARKETING, INC.-TX (11580) Logout Welcome CEO Dashboard")


class _StubPage:
    def __init__(self, header):
        self._header = header

    def inner_text(self, _sel):
        if self._header is None:
            raise RuntimeError("body not readable")
        return self._header


class LoggedInOffice(unittest.TestCase):
    def test_reads_the_office_id_from_the_header(self):
        _head, office = KP.logged_in_office(_StubPage(RAF_HEADER))
        self.assertEqual(office, "11280")

    def test_unreadable_header_is_not_a_mismatch(self):
        """An unreadable header must return "" so the caller lets the pull run —
        only a POSITIVE mismatch may block it. A check that fails closed on its
        own flakiness would take the board down for a reason that isn't real."""
        head, office = KP.logged_in_office(_StubPage(None))
        self.assertEqual((head, office), ("", ""))


class MasterPullRefusesTheWrongOwner(unittest.TestCase):
    def test_carlos_session_refuses_to_publish_as_raf(self):
        with self.assertRaises(RuntimeError) as cm:
            KP.pull_master_days_on_page(_StubPage(CARLOS_HEADER), [],
                                        verbose=False)
        msg = str(cm.exception)
        self.assertIn("11580", msg)
        self.assertIn("11280", msg)
        # The message has to name the FIX, not just the symptom: this failure
        # reaches Megan as one line in a Slack alert.
        self.assertIn("ownerville-creds.json", msg)

    def test_raf_session_passes_the_identity_check(self):
        """The right owner must get PAST the guard — proven by the fact that the
        next step (capturing the rqst token off the stub) is what fails."""
        with self.assertRaises(Exception) as cm:
            KP.pull_master_days_on_page(_StubPage(RAF_HEADER), [],
                                        verbose=False)
        self.assertNotIn("refusing to publish", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
