"""--prune finds a section's thread reply by its bold title (emoji or not)
or, for a file upload whose text is empty, by the upload's filename --
including the house workbook's 'Order Log 11-09-2026.xlsx' (the 11/9 prune
missed the morning copy because 'order_log' never matched that name).

  python -m unittest automations.nds_metrics.test_prune_match
"""
import unittest

from automations.nds_metrics.run import reply_is_section


def _m(text="", *names):
    return {"text": text, "files": [{"name": n} for n in names]}


class PruneMatch(unittest.TestCase):
    def test_caption_with_unicode_or_shortcode_emoji(self):
        self.assertTrue(reply_is_section(
            _m("\U0001F4C4 *NDS Order Log*\nSource: Tableau"), "order_log", "NDS Order Log"))
        self.assertTrue(reply_is_section(
            _m(":page_facing_up: *NDS Order Log*"), "order_log", "NDS Order Log"))

    def test_filename_matches_when_the_text_is_empty(self):
        self.assertTrue(reply_is_section(
            _m("", "Order Log 11-09-2026.xlsx"), "order_log", "NDS Order Log"))
        self.assertTrue(reply_is_section(
            _m("", "nds_revenue_board.png"), "revenue_board", "NDS Revenue Board"))

    def test_other_replies_are_left_alone(self):
        index = _m("In this thread:\n:page_facing_up: NDS Order Log\n"
                   ":dollar: NDS Activation Report Overview")
        self.assertFalse(reply_is_section(index, "order_log", "NDS Order Log"))
        self.assertFalse(reply_is_section(
            _m("\U0001F4B0 *NDS Revenue Board*", "nds_revenue_board.png"),
            "order_log", "NDS Order Log"))
        self.assertFalse(reply_is_section(
            _m("*NDS Knocks Board — Mon–Sat 11/2–11/7*",
               "weekly_knock_dispositions_2026-11-07.png"),
            "knocks_final", "NDS Knocks Board — Day Prior"))


if __name__ == "__main__":
    unittest.main()
