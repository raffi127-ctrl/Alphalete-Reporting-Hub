"""The Send Email / Send SMS boxes come OFF before Send to AI (Carlos,
2026-10-20), and nothing else on the panel is touched.

Runs a real headless Chromium on a stand-in panel -- no AppStream, no login,
nothing sent. Skips (does not fail) on a machine without a browser.
"""
from __future__ import annotations

import unittest

from automations.oat_processing import run as OAT

PANEL = """
<table>
 <tr><td>Call Status</td><td><select><option>Please Select</option></select></td></tr>
 <tr><td>Send Email</td><td><input type=checkbox name=sendEmail checked
     onchange="document.body.dataset.changed=(+(document.body.dataset.changed||0))+1"></td></tr>
 <tr><td>Send SMS</td><td><input type=checkbox name=sendSMS checked
     onchange="document.body.dataset.changed=(+(document.body.dataset.changed||0))+1"></td></tr>
 <tr><td><label for=x>Send Text</label></td><td><input type=checkbox id=x checked></td></tr>
 <tr><td>Matched Only</td><td><input type=checkbox name=matchedOnly checked></td></tr>
</table>
"""


class SendBoxes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        try:
            from patchright.sync_api import sync_playwright
            cls.pw = sync_playwright().start()
            cls.browser = cls.pw.chromium.launch(headless=True)
        except Exception as e:  # noqa: BLE001
            raise unittest.SkipTest("no browser here: %s" % e)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def page(self):
        pg = self.browser.new_page()
        pg.set_content(PANEL)
        self.addCleanup(pg.close)
        return pg

    def ticked(self, pg, sel):
        return pg.evaluate("s => document.querySelector(s).checked", sel)

    def test_live_unticks_both_and_the_page_sees_it(self):
        pg = self.page()
        note = OAT.untick_send_boxes(pg, live=True)
        self.assertFalse(self.ticked(pg, "[name=sendEmail]"))
        self.assertFalse(self.ticked(pg, "[name=sendSMS]"))
        self.assertFalse(self.ticked(pg, "#x"))
        # The page's own change handlers ran (read off the DOM: patchright's
        # evaluate cannot see page globals).
        self.assertEqual(pg.evaluate("document.body.dataset.changed"), "2")
        self.assertIn("unticked", note)

    def test_nothing_else_is_touched(self):
        pg = self.page()
        OAT.untick_send_boxes(pg, live=True)
        self.assertTrue(self.ticked(pg, "[name=matchedOnly]"))

    def test_a_dry_run_changes_nothing(self):
        pg = self.page()
        note = OAT.untick_send_boxes(pg, live=False)
        self.assertTrue(self.ticked(pg, "[name=sendEmail]"))
        self.assertTrue(self.ticked(pg, "[name=sendSMS]"))
        self.assertIn("would untick", note)

    def test_already_off_says_so(self):
        pg = self.page()
        OAT.untick_send_boxes(pg, live=True)
        self.assertIn("already off", OAT.untick_send_boxes(pg, live=True))

    def test_a_panel_without_them_is_not_fatal(self):
        pg = self.browser.new_page()
        self.addCleanup(pg.close)
        pg.set_content("<p>nothing here</p>")
        self.assertIn("not found", OAT.untick_send_boxes(pg, live=True))


if __name__ == "__main__":
    unittest.main()
