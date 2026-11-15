"""Alphalete -> an office's own computer (Raf, 11/15): one switch, nothing twice."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.online_presence import offices


def _raf(**kw):
    base = dict(key="raf", business_name="Alphalete Marketing", slack_channel="C1",
                mode="live", replaces_alphalete=True)
    base.update(kw)
    return offices.Presence(**base)


class Switch(unittest.TestCase):
    def _rows(self, *ps):
        f = Path(tempfile.mkdtemp()) / "offices.json"
        f.write_text(json.dumps([offices._to_row(p) for p in ps]))
        return f

    def test_only_a_live_takeover_counts(self):
        self.assertIsNone(offices.moved_alphalete(self._rows(_raf(mode="dry"))))
        self.assertEqual(offices.moved_alphalete(self._rows(_raf())).key, "raf")

    def test_lucy3_alphalete_jobs_stand_down(self):
        from automations.brand_audit import review_replies, social_inbox, fb_reviews
        with mock.patch("automations.online_presence.offices.moved_alphalete", return_value=_raf()):
            self.assertEqual(review_replies.process_reviews(dry_run=True)[0]["action"], "moved")
            self.assertEqual(social_inbox.process_inbox(dry_run=True)[0]["action"], "moved")
            self.assertEqual(fb_reviews.process(live=False)[0]["action"], "moved")

    def test_memory_carried_over_once_and_never_the_keys(self):
        src, dst = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        for n in ("review_replies.json", "social_inbox.json", "keys.json", "gbp-token.json"):
            (src / n).write_text("{}")
        p = _raf(state_dir=str(dst))
        with mock.patch.object(offices, "alphalete", return_value=mock.Mock(state_dir=str(src))):
            self.assertEqual(offices.migrate_alphalete_state(p), ["review_replies.json", "social_inbox.json"])
            self.assertEqual(offices.migrate_alphalete_state(p), [])          # once
        self.assertFalse((dst / "keys.json").exists())


if __name__ == "__main__":
    unittest.main()
