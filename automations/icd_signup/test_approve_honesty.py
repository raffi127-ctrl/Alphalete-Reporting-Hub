"""An approval that refused everything must not say the office is live.

Ryan McSpadden was told "is live" on 2026-09-15 seconds after his approval had
refused BOTH his channels for not having Lucy in them. cmd_knocks returned
failure and nothing looked at it -- the SaraPlus half above has always checked
its own result, and this half never did.

For a Box, Energy Wells or NDS office it is worse than a wrong message: the
board is the only thing they get, so "live" describes an office that posts
nothing at all.
"""
from __future__ import annotations

import inspect
import unittest
from unittest import mock

from automations.icd_signup import approve as A


class TheKnocksResultIsChecked(unittest.TestCase):

    def test_cmd_knocks_return_is_used(self):
        src = inspect.getsource(A.approve)
        self.assertIn("channels.cmd_knocks(rec.office_key) == 0", src,
                      "the knocks approval result is still discarded")

    def test_a_knocks_only_office_is_not_marked_approved(self):
        src = inspect.getsource(A.approve)
        i = src.index("knocks_ok = channels.cmd_knocks")
        after = src[i:]
        self.assertIn("uses_saraplus(rec.campaign)", after)
        self.assertIn("return 1", after,
                      "a Box office whose only product was refused is still "
                      "marked approved")
        # The bail must come BEFORE the status is written.
        self.assertLess(after.index("return 1"), after.index("set_status"),
                        "it marks the office approved before deciding whether "
                        "anything was")

    def test_a_saraplus_office_keeps_its_alerts_but_is_told(self):
        src = inspect.getsource(A.approve)
        self.assertIn("knocks board is", src)
        self.assertIn("NOT", src)


class ARefusedBoxOfficeReturnsNonZero(unittest.TestCase):
    """Behaviour, not text."""

    def _run(self, campaign, knocks_rc):
        rec = mock.MagicMock()
        rec.owner, rec.office_key = "Ryan McSpadden", "ryan"
        rec.status, rec.campaign = "pending", campaign
        rec.knocks_cadence, rec.text_groups = 60, []
        rec.submitted_at = "x"
        ch = mock.MagicMock()
        ch.cmd_approve.return_value = 0
        ch.cmd_knocks.return_value = knocks_rc
        with mock.patch.object(A.store, "get", return_value=rec), \
                mock.patch.object(A.store, "set_status") as setst, \
                mock.patch.dict("sys.modules",
                                {"automations.icd_alerts.approve": ch}), \
                mock.patch("automations.icd_alerts.approve.cmd_approve",
                           return_value=0, create=True), \
                mock.patch("automations.icd_alerts.approve.cmd_knocks",
                           return_value=knocks_rc, create=True):
            rc = A.approve("ryan", do_push=False, log=lambda *_: None)
        return rc, setst.called

    def test_box_office_with_refused_channels(self):
        rc, marked = self._run("b2b_box", knocks_rc=1)
        self.assertEqual(rc, 1)
        self.assertFalse(marked, "it was marked approved anyway")

    def test_box_office_with_good_channels(self):
        rc, marked = self._run("b2b_box", knocks_rc=0)
        self.assertEqual(rc, 0)
        self.assertTrue(marked)


if __name__ == "__main__":
    unittest.main()


class TextsApprovalTouchesOnlyOurColumnsTest(unittest.TestCase):
    """Colten 2026-09-22: approved at 8:50, un-approved by his own 9:05 sweep.
    The writer had rewritten 'Texts: Wanted' + its JSON (the OFFICE's
    columns); the relay saw a disagreement and cleared the approval."""

    def test_writer_updates_only_the_two_approved_cells(self):
        from unittest import mock
        from automations.icd_alerts import approve as A, post as P
        tab = mock.Mock()
        tab.get_all_values.return_value = [["Office"], ["colten"]]
        book = mock.Mock(); book.worksheet.return_value = tab
        with mock.patch("automations.recruiting_report.fill.open_by_key",
                        return_value=book), \
             mock.patch.object(A, "ensure_text_columns"):
            A._write_texts_approval("colten", [{"group": "A Players",
                                                "cadence_min": 0}])
        kw = tab.update.call_args.kwargs
        self.assertEqual(kw["range_name"], "%s2:%s2" % (
            A._col_letter(P.CH_TX_APPROVED_JSON + 1),
            A._col_letter(P.CH_TX_APPROVED + 1)))
        self.assertEqual(len(kw["values"][0]), 2)
        self.assertEqual(kw["values"][0][1], "TRUE")
