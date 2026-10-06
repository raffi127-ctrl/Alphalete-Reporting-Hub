"""A knocks read that finds no grid files WHAT IT SAW, not just a traceback.

Jamis, 2026-10-06: his Mac said "the knocks table never appeared" every sweep
for four hours while the same office, impersonated from Lucy 2, served its grid
at once. The traceback alone could not tell those two laptops apart.
"""
import unittest

from automations.icd_alerts import ov_read


class _Page:
    url = "https://v2.ownerville.com/index.cfm?p=89&rqst=abc"

    def title(self):
        return "OwnerVille"

    def evaluate(self, _js):
        return "Please select an office to continue"


class _BrokenPage(_Page):
    def title(self):
        raise RuntimeError("target closed")

    def evaluate(self, _js):
        raise RuntimeError("target closed")


class EvidenceTest(unittest.TestCase):
    def test_carries_log_url_title_and_text(self):
        out = ov_read._page_evidence(_Page(), ["OwnerVille session still good",
                                               "  pinned campaign 2",
                                               "grid never built after 3 navigations"])
        self.assertIn("pinned campaign 2", out)
        self.assertIn("grid never built", out)
        self.assertIn("page url: https://v2.ownerville.com/index.cfm?p=89", out)
        self.assertIn("page title: OwnerVille", out)
        self.assertIn("Please select an office", out)

    def test_keeps_only_the_last_15_log_lines(self):
        out = ov_read._page_evidence(_Page(), ["line %d" % i for i in range(40)])
        self.assertNotIn("line 24", out)
        self.assertIn("line 25", out)
        self.assertIn("line 39", out)

    def test_a_dead_page_still_yields_the_log(self):
        out = ov_read._page_evidence(_BrokenPage(), ["OwnerVille session has lapsed"])
        self.assertIn("session has lapsed", out)
        self.assertIn("page url:", out)
        self.assertNotIn("page title", out)


if __name__ == "__main__":
    unittest.main()
