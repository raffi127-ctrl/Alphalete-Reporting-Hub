"""The holder must hold a live TOKEN, not a rendering console.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_holder_appstream_token

WHAT THIS GUARDS (Megan 2026-08-25). `_warm_appstream` used to return True the
moment `#searchMC` was present after a reload, and never reach its
storage_state branch. But `#searchMC` renders off CFID/CFTOKEN alone, and the
holder's own 6-minute reload keeps those alive indefinitely. So once the rqst
SSO token aged out, the holder sat warming a console carrying no token,
`_export_appstream` correctly refused to write (its guard: no token → keep the
last good export), and the loop printed:

    [2026-08-25 11:29:32] AppStream ✓ — 0 cookies (office-11580 console warm)

every six minutes, for days. Two separate defects in one line:

1. THE REMOTE RE-SEED COULD NOT REACH IT. `--appstream-push-fleet` writes a
   fresh token to APPSTREAM_STORAGE_STATE, and _reuse_appstream_storage_state
   re-reads that file on EVERY call — but the early return meant it was never
   called. The one process whose whole job is holding that session was the one
   process a successful push could not reach. Lucy 1 stayed tokenless all
   morning on 8/25 after an 08:42 push that verified clean on all three boxes.

2. ✓ ON AN EMPTY EXPORT. The only signal that would have shown this read fine
   the entire time.

So the bar is the token now, and a 0-cookie export is reported as the problem
it is.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.shared import session_holder as sh


def _ctx(*, rqst: int, domain: str = "www.applicantstream.com"):
    """A context whose storage_state carries `rqst` rqst_ tokens."""
    cookies = [{"name": "CFID", "domain": domain},
               {"name": "CFTOKEN", "domain": domain}]
    cookies += [{"name": f"rqst_{i}", "domain": domain} for i in range(rqst)]
    ctx = mock.Mock()
    ctx.storage_state.return_value = {"cookies": cookies}
    return ctx


def _page(*, on_appstream: bool = True, searchmc: int = 1):
    page = mock.Mock()
    page.url = ("https://www.applicantstream.com/index.cfm?p=701"
                if on_appstream else "https://example.com/")
    page.locator.return_value.count.return_value = searchmc
    return page


class TheContextProbe(unittest.TestCase):
    """_ctx_rqst_count is what makes 'live' distinguishable from 'renders'."""

    def test_it_counts_applicantstream_rqst_cookies(self):
        self.assertEqual(sh._ctx_rqst_count(_ctx(rqst=2)), 2)

    def test_cf_cookies_alone_count_as_zero(self):
        """The exact shape of the bug: session cookies, no SSO token."""
        self.assertEqual(sh._ctx_rqst_count(_ctx(rqst=0)), 0)

    def test_another_domains_rqst_cookie_does_not_count(self):
        self.assertEqual(
            sh._ctx_rqst_count(_ctx(rqst=3, domain="ownerville.com")), 0)

    def test_a_broken_context_answers_zero_rather_than_raising(self):
        """A probe must never take the holder down."""
        ctx = mock.Mock()
        ctx.storage_state.side_effect = RuntimeError("browser gone")
        self.assertEqual(sh._ctx_rqst_count(ctx), 0)


class ARenderingConsoleIsNotEnough(unittest.TestCase):

    def test_console_with_no_token_falls_through_to_the_state_file(self):
        """THE BUG. This is how a pushed token reaches the live context."""
        with mock.patch.object(sh, "_reuse_appstream_storage_state",
                               return_value=True) as reuse:
            ok = sh._warm_appstream(_ctx(rqst=0), _page(), verbose=False)
        self.assertTrue(ok)
        reuse.assert_called_once()

    def test_console_with_a_token_short_circuits(self):
        """The healthy path must stay cheap — no re-read every 6 minutes."""
        with mock.patch.object(sh, "_reuse_appstream_storage_state",
                               return_value=True) as reuse:
            ok = sh._warm_appstream(_ctx(rqst=1), _page(), verbose=False)
        self.assertTrue(ok)
        reuse.assert_not_called()

    def test_a_dead_state_file_still_reports_failure(self):
        """Console renders, no token, and the saved state can't help either —
        that is a genuine 'needs a re-seed', not a success."""
        with mock.patch.object(sh, "_reuse_appstream_storage_state",
                               return_value=False):
            self.assertFalse(
                sh._warm_appstream(_ctx(rqst=0), _page(), verbose=False))

    def test_off_console_goes_to_the_state_file_as_before(self):
        """Unchanged behaviour when the page isn't on applicantstream at all."""
        with mock.patch.object(sh, "_reuse_appstream_storage_state",
                               return_value=True) as reuse:
            sh._warm_appstream(_ctx(rqst=0), _page(on_appstream=False),
                               verbose=False)
        reuse.assert_called_once()

    def test_a_reload_that_throws_still_falls_through(self):
        page = _page()
        page.reload.side_effect = RuntimeError("navigation failed")
        with mock.patch.object(sh, "_reuse_appstream_storage_state",
                               return_value=True) as reuse:
            self.assertTrue(sh._warm_appstream(_ctx(rqst=1), page,
                                               verbose=False))
        reuse.assert_called_once()


class TheExportGuardIsUnchanged(unittest.TestCase):
    """_export_appstream's refusal to write a tokenless state is CORRECT — it
    protects a good rcaptain login. Only the reporting around it was wrong."""

    def test_a_tokenless_context_exports_nothing(self):
        self.assertEqual(sh._export_appstream(_ctx(rqst=0)), 0)

    def test_a_context_with_a_token_exports(self):
        # Swap the module-level Path for a Mock: a PosixPath's methods are
        # read-only, and this also guarantees no real file is written.
        fake = mock.Mock()
        with mock.patch.object(sh, "APPSTREAM_STORAGE_STATE", fake):
            n = sh._export_appstream(_ctx(rqst=1))
        self.assertEqual(n, 3)          # CFID + CFTOKEN + rqst_0
        fake.write_text.assert_called_once()

    def test_a_tokenless_context_never_touches_the_file(self):
        """The guard's real job: don't clobber the last good export."""
        fake = mock.Mock()
        with mock.patch.object(sh, "APPSTREAM_STORAGE_STATE", fake):
            sh._export_appstream(_ctx(rqst=0))
        fake.write_text.assert_not_called()


class ZeroIsNotSuccess(unittest.TestCase):
    """The ✓ that hid it. Guarded at the source so the log can't lie again."""

    def test_the_loop_only_prints_the_check_when_something_was_exported(self):
        import inspect
        src = inspect.getsource(sh)
        self.assertIn("if apn:", src,
                      "a 0-cookie export must not print the ✓ line")
        self.assertIn("NO rqst token", src,
                      "the empty-export case needs its own visible warning")


if __name__ == "__main__":
    unittest.main()
