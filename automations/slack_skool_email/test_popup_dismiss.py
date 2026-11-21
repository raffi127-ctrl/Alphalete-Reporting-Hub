"""A Slack pop-up over the client is closed before the workspace-menu click.

2026-11-21: the 8am send to Monday's new starts failed with "couldn't open the
workspace menu". The button was there; a ReactModal overlay ate the click.

    python -m unittest automations.slack_skool_email.test_popup_dismiss
"""
import unittest

from automations.slack_skool_email import slack_invite as SI


class _Page:
    def __init__(self, popups, closable=True):
        self.popups = popups
        self.closable = closable
        self.clicked, self.keys = [], []

    def query_selector(self, sel):
        return object() if (sel == SI.POPUP_OVERLAY and self.popups) else None

    def inner_text(self, sel):
        return "What's new in Slack\nsome text"

    def click(self, sel, timeout=None):
        self.clicked.append(sel)
        if not self.closable:
            raise TimeoutError(sel)
        self.popups -= 1

    @property
    def keyboard(self):
        page = self

        class _K:
            def press(self, key):
                page.keys.append(key)
                page.popups -= 1
        return _K()

    def wait_for_timeout(self, ms):
        pass


class DismissPopups(unittest.TestCase):
    def test_no_popup_clicks_nothing(self):
        p = _Page(0)
        SI._dismiss_popups(p, log=lambda *a: None)
        self.assertEqual(p.clicked, [])

    def test_popup_is_closed_with_a_close_button(self):
        p = _Page(1)
        SI._dismiss_popups(p, log=lambda *a: None)
        self.assertEqual(p.popups, 0)
        self.assertEqual(p.clicked[0], SI.POPUP_CLOSE[0])

    def test_no_close_button_falls_back_to_escape(self):
        p = _Page(1, closable=False)
        SI._dismiss_popups(p, log=lambda *a: None)
        self.assertEqual(p.keys, ["Escape"])
        self.assertEqual(p.popups, 0)

    def test_only_dismiss_answers(self):
        for sel in SI.POPUP_CLOSE:
            for word in ("Allow", "Enable", "Accept", "Upgrade", "Turn on"):
                self.assertNotIn(word, sel)


if __name__ == "__main__":
    unittest.main()
