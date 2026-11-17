"""The row-name reader, against the two table shapes OwnerVille really serves.

2026-11-17, James Turnage. The reader used to take the row's FIRST LINE as the
person's name. That is true on RES-AT&T and false on Raf's Charter
Communications - D2D, where the first cell is the EMPLOYEE ID -- so every name
read off that campaign was '9576433', and the typo matcher scored real names
against a number. The walk had never reached Charter before (it was pinned to
RES-AT&T), so nothing had ever exposed it.

Runs a real headless browser, because the thing under test is JavaScript
evaluated in the page -- a hand-rolled fake DOM would only prove the fake.
Skips where no browser is installed.

    python -m unittest automations.headshots.test_row_names_js
"""
from __future__ import annotations

import unittest

from automations.headshots import ov_upload as U

# How the same two people render on each campaign of Raf's View Progress.
RES_ATT = """<table><tbody>
<tr><td></td><td>James Rucker (9541175)</td><td>Edit</td><td>Action</td>
    <td>Roadmap - Remove</td></tr>
</tbody></table>"""

CHARTER = """<table><tbody>
<tr><td>9541175</td><td>brianrucker31@gmail.com</td><td>Edit</td>
    <td>James Rucker</td><td>Photo</td></tr>
<tr><td>9576433</td><td>jamesturnage23@gmail.com</td><td>Edit</td>
    <td>James Turnag</td><td>Photo</td></tr>
</tbody></table>"""


def _launcher():
    try:
        from patchright.sync_api import sync_playwright
    except ImportError:                                   # noqa: BLE001
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return None
    return sync_playwright


class ThePageReaders(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        pw = _launcher()
        if pw is None:
            raise unittest.SkipTest("no playwright/patchright installed")
        cls._pw = pw().start()
        try:
            cls._browser = cls._pw.chromium.launch(headless=True)
        except Exception as e:                            # noqa: BLE001
            cls._pw.stop()
            raise unittest.SkipTest(f"no headless browser: {e}")

    @classmethod
    def tearDownClass(cls):
        cls._browser.close()
        cls._pw.stop()

    def page(self, html):
        p = self._browser.new_page()
        p.set_content(html)
        self.addCleanup(p.close)
        return p

    def names(self, html):
        return self.page(html).evaluate(U._ROW_NAMES_JS)

    def test_the_att_shape_reads_the_name(self):
        self.assertEqual(self.names(RES_ATT), ["James Rucker (9541175)"])

    def test_the_charter_shape_reads_names_not_employee_ids(self):
        """The bug: these came back as ['9541175', '9576433']."""
        self.assertEqual(self.names(CHARTER), ["James Rucker", "James Turnag"])

    def test_an_exact_name_is_found_either_shape(self):
        self.assertIsNotNone(U._rep_row(self.page(RES_ATT), "James Rucker"))
        self.assertIsNotNone(U._rep_row(self.page(CHARTER), "James Rucker"))

    def test_ownervilles_spelling_is_forgiven_at_the_higher_bar(self):
        """OV holds "James Turnag"; the submitted name is James Turnage."""
        row, got = U._fuzzy_row(self.page(CHARTER), "James Turnage",
                                verbose=False,
                                min_score=U._MIN_SCORE_OTHER)
        self.assertIsNotNone(row)
        self.assertEqual(got, "James Turnag")

    def test_a_stranger_is_not_forgiven_off_campaign(self):
        """A name that merely looks similar must not pass the higher bar --
        the person we want may not be on that campaign at all."""
        row, _ = U._fuzzy_row(self.page(CHARTER), "James Turner",
                              verbose=False, min_score=U._MIN_SCORE_OTHER)
        self.assertIsNone(row)

    def test_a_blank_table_reads_as_no_names(self):
        html = "<table><tbody><tr><td>No data available in table</td></tr>" \
               "</tbody></table>"
        self.assertNotIn("9576433", self.names(html))


if __name__ == "__main__":
    unittest.main()
