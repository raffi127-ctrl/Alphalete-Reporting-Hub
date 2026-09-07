"""A timed-out Tableau SSO hop gets a second try, not a dead report.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_tableau_sso_retry

WHY (2026-09-07). captainship_activations failed five times, every time on the
same line and the same message:

    patchright._impl._errors.TimeoutError: Page.goto: Timeout 30000ms exceeded.
      - navigating to "https://v2.ownerville.com/index.cfm?p=81&rqst=...&ssook=1"

6373cfb2 gave both navigations their own 90s budget, which is the right first
move — 30s was a number with no relation to what the hop costs. This is the
other half.

A bigger number alone leaves two holes. The chain can outrun ANY budget while
still having ARRIVED (the redirect ends on Tableau; only the last document is
slow to fire domcontentloaded), and until now the exception decided the outcome
rather than where the page ended up. And a login that times out had no retry at
all, while the download it exists to serve gets three attempts plus a
fresh-login escape hatch — so the report died on a hop that a second try would
very likely have cleared.

Which matters here more than anywhere else: captainship_activations opens EIGHT
back-to-back logins in its PSS phase (one per captain, isolated on purpose so a
Tableau filter can't leak into the next pull), and it never failed on the first
one. It failed on a later hop, after all of phase 1 had already been paid for.

The retry fetches a FRESH rqst: ownerville issues a new token per visit, so
replaying a spent one is a dead hop.
"""
from __future__ import annotations  # Lucy 1 / mini run Python 3.9

import unittest

from automations.shared import tableau_patchright as tp


class FakePage:
    """Records goto() calls. `outcomes` is one entry per SSO-hop goto: either a
    URL to land on, or an exception to raise (after which `url` stays at
    `stalled_url`). Token fetching is stubbed out, so every goto here is a hop."""

    def __init__(self, outcomes, stalled_url="https://v2.ownerville.com/index.cfm"):
        self.outcomes = list(outcomes)
        self.stalled_url = stalled_url
        self.url = stalled_url
        self.hops = []

    def goto(self, url, **kw):
        self.hops.append((url, kw))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            self.url = self.stalled_url
            raise outcome
        self.url = outcome

    def wait_for_timeout(self, ms):
        pass


TABLEAU_HOME = "https://us-east-1.online.tableau.com/#/site/sci/home"


class SsoRetryTest(unittest.TestCase):

    def setUp(self):
        self.tokens = []

        def fake_fetch(page):
            self.tokens.append("TOKEN%d" % len(self.tokens))
            return self.tokens[-1]

        self.addCleanup(setattr, tp, "_fetch_ownerville_sso_token",
                        tp._fetch_ownerville_sso_token)
        tp._fetch_ownerville_sso_token = fake_fetch

    # -- the happy path has to stay exactly what it was ------------------

    def test_clean_goto_returns_without_judging_the_landing_url(self):
        """A goto that returns normally is accepted as-is: no URL check, no
        second attempt. We never verified the landing URL before, so a hop that
        legitimately ends somewhere other than tableau.com must not start
        failing now."""
        page = FakePage(["https://v2.ownerville.com/viewable.cfm?x=1"])
        tp._sso_to_tableau(page, verbose=False)
        self.assertEqual(len(page.hops), 1)
        self.assertEqual(len(self.tokens), 1)

    def test_the_hop_still_rides_the_90s_budget(self):
        page = FakePage([TABLEAU_HOME])
        tp._sso_to_tableau(page, verbose=False)
        self.assertEqual(page.hops[0][1]["timeout"], tp.SSO_NAV_TIMEOUT_MS)
        self.assertGreater(tp.SSO_NAV_TIMEOUT_MS, 30_000)

    # -- what killed the report on 9/7 ----------------------------------

    def test_a_timeout_that_actually_landed_is_not_fatal(self):
        page = FakePage([tp.PWTimeout("Page.goto: Timeout 90000ms exceeded.")],
                        stalled_url=TABLEAU_HOME)
        tp._sso_to_tableau(page, verbose=False)          # no raise
        self.assertEqual(len(page.hops), 1, "and no wasted second hop")

    def test_a_stalled_hop_retries_once_on_a_fresh_token(self):
        page = FakePage([tp.PWTimeout("Page.goto: Timeout 90000ms exceeded."),
                         TABLEAU_HOME])
        tp._sso_to_tableau(page, verbose=False)
        self.assertEqual(len(page.hops), 2)
        self.assertEqual(len(self.tokens), 2, "the retry must fetch a NEW rqst")
        self.assertIn(self.tokens[1], page.hops[1][0])
        self.assertNotIn(self.tokens[0], page.hops[1][0])

    def test_it_gives_up_after_the_budget_and_names_the_usual_cause(self):
        page = FakePage([tp.PWTimeout("Page.goto: Timeout 90000ms exceeded.")
                         for _ in range(tp._SSO_ATTEMPTS)])
        with self.assertRaises(RuntimeError) as caught:
            tp._sso_to_tableau(page, verbose=False)
        self.assertEqual(len(page.hops), tp._SSO_ATTEMPTS)
        self.assertIn("ONE session per account", str(caught.exception))
        # The patchright timeout stays reachable as __cause__ — the log tail in
        # the incident post is how these get diagnosed.
        self.assertIsInstance(caught.exception.__cause__, tp.PWTimeout)

    def test_a_missing_token_still_raises_the_old_seed_error(self):
        tp._fetch_ownerville_sso_token = lambda page: None
        page = FakePage([])
        with self.assertRaises(RuntimeError) as caught:
            tp._sso_to_tableau(page, verbose=False)
        self.assertIn("rqst=", str(caught.exception))
        self.assertEqual(page.hops, [], "no hop without a token")


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
