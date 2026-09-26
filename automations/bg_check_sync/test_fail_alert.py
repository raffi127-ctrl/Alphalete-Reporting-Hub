"""Offline tests — no email, no Sheets, no Messages.

    python -m unittest automations.bg_check_sync.test_fail_alert
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.bg_check_sync import fail_alert as fa


class P:
    def __init__(self, first, last):
        self.first, self.last = first, last


class D:
    def __init__(self, first, last, new_status="", needs_adjudication=False):
        self.person = P(first, last)
        self.new_status = new_status
        self.needs_adjudication = needs_adjudication


# Quincy Williams, 2026-09-25: "Background Check Complete - Score FAIL", which
# parse.classify records as Review + needs_adjudication.
QUINCY = D("Quincy", "Williams", new_status="Review", needs_adjudication=True)
PASSED = D("Deric", "Williams", new_status="Passed")
TERMINAL = D("Jane", "Doe", new_status="Failed")


class WhoCounts(unittest.TestCase):
    def test_score_fail_and_terminal_fail_both_count(self):
        got = dict(fa.failures([QUINCY, PASSED, TERMINAL]))
        self.assertEqual(sorted(got), ["Jane Doe", "Quincy Williams"])
        self.assertEqual(got["Jane Doe"], "Failed")
        self.assertIn("Score FAIL", got["Quincy Williams"])

    def test_one_line_per_person_even_with_two_emails(self):
        twice = [QUINCY, D("Quincy", "Williams", "Review", True)]
        self.assertEqual(fa.failures(twice), fa.failures([QUINCY]))

    def test_a_pass_is_never_texted(self):
        self.assertEqual(fa.failures([PASSED]), [])

    def test_message_names_them(self):
        msg = fa.message(fa.failures([QUINCY]))
        self.assertEqual(msg, "🚨 Background check FAILED — this week's new "
                              "start\n• Quincy Williams — Score FAIL — in "
                              "adverse-action review")


class OnlyThisWeek(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patch = mock.patch.object(fa, "STATE",
                                  Path(self.tmp.name) / "texted.json")
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_an_older_week_is_not_texted(self):
        res = fa.send([QUINCY], "9/14", is_current_week=False, dry_run=True)
        self.assertEqual(res["texted"], [])

    def test_current_week_dry_run_says_who(self):
        res = fa.send([QUINCY], "9/21", is_current_week=True, dry_run=True)
        self.assertEqual(res["texted"], ["Quincy Williams"])

    def test_sends_once_then_remembers(self):
        sent = []

        def fake_send(group, text, images, *, dry_run, allow_textonly):
            sent.append((group, text))
            return {"ok": True, "resolved_name": group, "participants": 15}
        with mock.patch("automations.b2b_dispositions.text_post.send_to_group",
                        fake_send):
            first = fa.send([QUINCY], "9/21", is_current_week=True,
                            dry_run=False)
            again = fa.send([QUINCY], "9/21", is_current_week=True,
                            dry_run=False)
        self.assertEqual(first["texted"], ["Quincy Williams"])
        self.assertEqual(sent[0][0], fa.GROUP)
        self.assertEqual(len(sent), 1)               # the 4pm pass stays quiet
        self.assertEqual(again["texted"], [])
        self.assertEqual(again["already"], ["Quincy Williams"])

    def test_a_failed_send_is_not_recorded_so_it_retries(self):
        with mock.patch("automations.b2b_dispositions.text_post.send_to_group",
                        lambda *a, **k: {"ok": False, "why": "no chat"}):
            res = fa.send([QUINCY], "9/21", is_current_week=True,
                          dry_run=False)
        self.assertEqual(res["texted"], [])
        self.assertIn("error", res)
        self.assertEqual(json.loads(fa.STATE.read_text())
                         if fa.STATE.exists() else {}, {})


if __name__ == "__main__":
    unittest.main()
