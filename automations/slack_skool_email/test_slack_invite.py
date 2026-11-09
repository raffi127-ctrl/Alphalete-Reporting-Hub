"""The invite dialog's link tab. Run:
python -m unittest automations.slack_skool_email.test_slack_invite"""
import unittest

from automations.slack_skool_email import slack_invite as S

LINK = "https://join.slack.com/t/ao-pbns/shared_invite/zt-abc-DEF"


class FakePage:
    """Only what the dialog needs: clickable selectors, what each one reveals."""

    def __init__(self, html="", clicks=None, clipboard=""):
        self.html, self.clicks, self.clipboard = html, clicks or {}, clipboard
        self.clicked = []

    def click(self, sel, timeout=0):
        if sel not in self.clicks:
            raise TimeoutError(sel)
        self.clicked.append(sel)
        self.html += self.clicks[sel].get("html", "")
        self.clipboard = self.clicks[sel].get("clipboard", self.clipboard)

    def wait_for_timeout(self, ms):
        pass

    def content(self):
        return self.html

    def eval_on_selector_all(self, sel, js):
        return []

    def evaluate(self, js):
        return self.clipboard


class LinkFromModal(unittest.TestCase):
    TAB = S.LINK_TAB_SELECTORS[0]

    def test_the_link_shows_once_its_tab_is_open(self):
        page = FakePage(clicks={self.TAB: {"html": LINK}})
        self.assertEqual(S._link_from_modal(page, lambda m: None), LINK)
        self.assertEqual(page.clicked, [self.TAB])

    def test_a_tab_with_only_a_copy_button_reads_the_clipboard(self):
        page = FakePage(clicks={self.TAB: {},
                                "button:has-text('Copy link')": {"clipboard": LINK}})
        self.assertEqual(S._link_from_modal(page, lambda m: None), LINK)

    def test_the_old_dialog_with_no_tab_still_works(self):
        page = FakePage(clicks={"[data-qa='copy-invite-link']": {"clipboard": LINK}})
        self.assertEqual(S._link_from_modal(page, lambda m: None), LINK)

    def test_something_else_on_the_clipboard_is_no_link(self):
        page = FakePage(clicks={self.TAB: {},
                                "button:has-text('Copy')": {"clipboard": "hello"}})
        self.assertEqual(S._link_from_modal(page, lambda m: None), "")

    def test_nothing_clickable_is_no_link(self):
        self.assertEqual(S._link_from_modal(FakePage(), lambda m: None), "")


if __name__ == "__main__":
    unittest.main()
