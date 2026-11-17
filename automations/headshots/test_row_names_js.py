"""Finding a rep, against the two table shapes OwnerVille really serves.

2026-11-17, James Turnage: he sat on Raf's Charter Communications - D2D the
whole time, spelled correctly, and no search could ever have found him.

  * The row writes the name as "James<br>Turnage". A <br> puts NOTHING into
    the text Playwright matches against, so the row reads "JamesTurnage" and
    a pattern wanting a space between the parts cannot hit. inner_text() DOES
    render that <br> as a newline -- which is why every debug line printed
    "james turnage" with a space while the match kept failing.
  * The name reader took each row's FIRST LINE as the person. True on
    RES-AT&T; on Charter the first cell is the EMPLOYEE ID and the name cell
    breaks lines, so names read as '9576433' and then as a bare 'James'.

Both were invisible until the walk was widened past RES-AT&T today.

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

# Charter, as the live table really renders it: id first, and the name cell
# broken by a <br>.
CHARTER = """<table><tbody>
<tr><td>9541175</td><td>brianrucker31@gmail.com</td><td>Edit</td>
    <td>James<br>Rucker</td><td>Photo</td></tr>
<tr><td>9576433</td><td>jamesturnage23@gmail.com</td><td>Edit</td>
    <td>James<br>Turnage</td><td>Photo</td></tr>
</tbody></table>"""

# The same shape with OwnerVille dropping a letter, which it is entitled to do.
CHARTER_TYPO = CHARTER.replace("James<br>Turnage", "James<br>Turnag")


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
        """The bug: these came back as ['9541175', '9576433'], then 'James'."""
        self.assertEqual(self.names(CHARTER), ["James Rucker", "James Turnage"])

    def test_the_man_himself_is_found_across_the_line_break(self):
        """THE case: 11/14 - 11/17 this returned None every five minutes."""
        self.assertIsNotNone(U._rep_row(self.page(CHARTER), "James Turnage"))

    def test_an_exact_name_is_found_either_shape(self):
        self.assertIsNotNone(U._rep_row(self.page(RES_ATT), "James Rucker"))
        self.assertIsNotNone(U._rep_row(self.page(CHARTER), "James Rucker"))

    def test_the_neighbour_is_not_him(self):
        self.assertIsNone(U._rep_row(self.page(CHARTER), "James Smith"))

    def test_a_typo_in_ownerville_is_forgiven_at_the_higher_bar(self):
        row, got = U._fuzzy_row(self.page(CHARTER_TYPO), "James Turnage",
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
