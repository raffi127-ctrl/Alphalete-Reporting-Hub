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
        return {"tables": "#table-dispositions.display",
                "frames": "",
                "text": "Please select an office to continue"}


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
        self.assertIn("tables: #table-dispositions", out)
        self.assertIn("iframes: none", out)

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


class _PickerPage:
    """A page whose evaluate() plays the client picker."""
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def evaluate(self, js, arg=None):
        self.calls.append(arg)
        return self.answer

    def wait_for_load_state(self, *_a, **_k):
        pass

    def wait_for_timeout(self, *_a):
        pass


class ChooseClientTest(unittest.TestCase):
    def test_picks_by_id_and_reports_what_it_chose(self):
        pg = _PickerPage("clientSel -> B2B AT&T SBS (2)")
        self.assertTrue(ov_read._choose_client(pg, "2", "b2b_att", log=lambda m: None))
        self.assertEqual(pg.calls[0][0], "2")
        self.assertIn("at&t", pg.calls[0][1])

    def test_no_picker_means_false(self):
        pg = _PickerPage("")
        self.assertFalse(ov_read._choose_client(pg, "16", "b2b_box", log=lambda m: None))

    def test_a_dead_page_means_false_not_a_crash(self):
        class Dead(_PickerPage):
            def evaluate(self, js, arg=None):
                raise RuntimeError("target closed")
        self.assertFalse(ov_read._choose_client(Dead(""), "2", "att", log=lambda m: None))
