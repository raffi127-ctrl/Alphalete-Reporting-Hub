"""The checkpoint's voice for an INCOMPLETE that is a FINDING, not a break.

Two reports now reach the checkpoint having done their whole job and merely
reported something they noticed:

  vantura_board_audit      kind='finding'       the SOURCE (the board) is wrong
  captainship_cancel_rate  kind='unfilled_icd'  the source is fine, one owner
                                                had no number

Both take the concise-parent / detail-in-thread path and skip the re-run +
paste-to-Claude block — but they are NOT the same news, so each owns its
wording (_FINDING_KINDS). Megan 2026-08-15 on the cancel-rate one: "the alert
on Melik just needs to say his is the only one not filled so we know that's not
a big deal / fail."

Run:  python -m automations.day_orchestrator.test_notify_findings   (3.9-safe)
"""
from __future__ import annotations

import types
import unittest
from unittest import mock

from automations.day_orchestrator import notify


def _rs(missing):
    return types.SimpleNamespace(
        report_id="captainship_cancel_rate",
        display_name="Captainship - Cancel Rate (ATT Fiber)",
        missing=list(missing))


class FindingSpecLookup(unittest.TestCase):
    """Which manifest kinds take the findings path."""

    def _with_kind(self, kind):
        m = {"kind": kind} if kind else None
        with mock.patch("automations.shared.run_manifest.read_manifest",
                        return_value=m), \
             mock.patch.object(notify, "_manifest_id", lambda c, r: "x"):
            return notify._is_findings_report(None, _rs([]))

    def test_board_audit_finding_still_takes_the_path(self):
        self.assertTrue(self._with_kind("finding"))

    def test_unfilled_icd_takes_the_path(self):
        """Without this the cancel-rate INCOMPLETE falls through to the normal
        FAILED-shaped post: paste-to-Claude block, re-run command, terminated
        split — an incident page for a run that filled every tab."""
        self.assertTrue(self._with_kind("unfilled_icd"))

    def test_an_ordinary_fill_report_does_not(self):
        self.assertFalse(self._with_kind("report"))
        self.assertFalse(self._with_kind("ICD"))
        self.assertFalse(self._with_kind(None))


class Wording(unittest.TestCase):
    """The actual text that goes to #claudecorrections."""

    def _post(self, kind, missing):
        """Run _post_findings_corrections with Slack stubbed; return
        (title, parent_lines, reply_lines)."""
        seen = {}

        def _fake_incident(cfg, *, key, title, body, details, followup=None,
                           day=None, dry_run=False, tag=None):
            seen.update(title=title, body=body, details=details)
            return {"ts": "1", "text": title, "new": True}

        with mock.patch.object(notify, "_finding_spec",
                               lambda c, r: notify._FINDING_KINDS[kind]), \
             mock.patch.object(notify, "_incident_post", _fake_incident):
            notify._post_findings_corrections(None, _rs(missing),
                                              "Captainship - Cancel Rate "
                                              "(ATT Fiber)", dry_run=True)
        return seen["title"], seen["body"], seen["details"]

    def test_unfilled_icd_parent_is_reassuring_and_names_the_owner(self):
        title, body, _ = self._post(
            "unfilled_icd", ["Melik El Jaiez (Tony's team, 0-30)"])
        text = title + "\n" + "\n".join(body)
        self.assertIn("Melik El Jaiez", text,
                      "the owner must be readable without opening the thread")
        self.assertIn("ran fine, 1 ICD didn't fill", text)
        self.assertIn("not a break", text)
        self.assertIn("nothing to re-run", text)
        self.assertIn(":white_check_mark:", title)
        for bad in (":warning:", ":rotating_light:", "FAILED", "Error"):
            self.assertNotIn(bad, text)

    def test_unfilled_icd_detail_carries_the_what_to_check(self):
        _, _, detail = self._post(
            "unfilled_icd", ["Melik El Jaiez (Tony's team, 0-30)"])
        thread = "\n".join(detail)
        self.assertIn("Melik El Jaiez (Tony's team, 0-30)", thread)
        self.assertIn("Usually nothing to do", thread)
        self.assertIn("no data is not 0%", thread)
        self.assertIn("filter / alias", thread)

    def test_plural(self):
        title, body, _ = self._post(
            "unfilled_icd", ["Melik El Jaiez (Tony's team, 0-30)",
                             "Andrew Burton (Sahil's team, 30-60)"])
        self.assertIn("2 ICDs didn't fill", title)
        self.assertIn("Andrew Burton (Sahil's team, 30-60)", "\n".join(body))

    def test_board_audit_wording_is_unchanged(self):
        """The vantura audit must read exactly as it did before the split."""
        title, body, detail = self._post("finding", ["Rep X is still Active"])
        self.assertIn(":warning:", title)
        self.assertIn("1 open data-quality finding(s)", title)
        self.assertIn("board data-quality issue(s) — details in thread",
                      "\n".join(body))
        self.assertIn("Report an Issue", "\n".join(body))
        self.assertIn("*Open findings:*", "\n".join(detail))
        self.assertIn("Roll Call statuses", "\n".join(detail))


if __name__ == "__main__":
    unittest.main()
