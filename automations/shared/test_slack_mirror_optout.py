"""mirror=False: post the primary, skip the mirror copy.

WHY (Megan 2026-09-04). Everything posted to #alphalete-sales is copied into
#alphalete-lvl1-chat (MIRROR_CHANNELS, Raf 8/23). The 9 PM knock board posts to
#alphalete-sales — and gap_alerts posts the SAME board straight into lvl1 a few
minutes earlier, so lvl1 got two: 2026-09-03 at 21:04 and 21:08.

The obvious fix — drop the office from knocks_intraday — would have deleted the
only copy in #alphalete-sales, the room where every other office's nightly board
lands, to de-duplicate a copy in the mirror. This flag removes the right half:
the primary post is untouched and only the mirror copy is skipped.

Default True, so the dozens of existing callers mirror exactly as before. That
default is the load-bearing part of these tests.
"""
from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path

from automations.shared import slack_metrics_post as smp

TODAY = dt.date(2026, 9, 4)


class _FakeClient:
    def __init__(self):
        self.uploads = []

    def files_upload_v2(self, **kw):
        self.uploads.append(kw)
        return {"ok": True, "file": {"id": "F1"}}

    def reactions_add(self, **kw):
        return {"ok": True}

    def conversations_replies(self, **kw):
        return {"messages": []}


class MirrorOptOut(unittest.TestCase):
    def setUp(self):
        self.client = _FakeClient()
        self._real = (smp._client, smp.mirror_channels, smp._mirror_reply)
        self.mirrored = []
        smp._client = lambda: self.client
        smp.mirror_channels = lambda c: ["C_LVL1"] if c == "C_SALES" else []

    def tearDown(self):
        smp._client, smp.mirror_channels, smp._mirror_reply = self._real

    def _post(self, **kw):
        return smp.post_reply_with_image(
            Path("x.png"), comment="Total Knocks", today=TODAY,
            channel_id="C_SALES", top_level=True, **kw)

    def test_the_primary_post_still_happens(self):
        """The whole point: #alphalete-sales keeps its board."""
        self._post(mirror=False)
        self.assertEqual(len(self.client.uploads), 1)
        self.assertEqual(self.client.uploads[0]["channel"], "C_SALES")

    def test_the_mirror_copy_is_skipped_and_named(self):
        out = self._post(mirror=False)
        self.assertEqual(out.get("mirrors_skipped"), ["C_LVL1"])
        self.assertNotIn("mirrors", out)

    def test_default_still_mirrors(self):
        """Every existing caller must be untouched — this is the one that
        matters most, since every metrics report posts through here."""
        seen = {}
        smp._mirror_reply = lambda *a, **kw: seen.setdefault("called", True)
        self._post()
        self.assertTrue(seen.get("called"))

    def test_dry_run_preview_admits_it_will_not_mirror(self):
        """A preview that still lists the mirror would read as 'two rooms'."""
        out = self._post(mirror=False, dry_run=True)
        self.assertEqual(out["mirrors_to"], [])
        self.assertEqual(
            self._post(dry_run=True)["mirrors_to"], ["C_LVL1"])


class KnocksUsesIt(unittest.TestCase):
    """The board only opts out for an office the registries say is doubled."""

    def test_only_the_colliding_office_skips_its_mirror(self):
        from unittest import mock
        from automations.knocks_intraday import run as KR, roster as R

        calls = []
        recs = [{"key": o.key, "label": o.label, "abbr": o.label[:3],
                 "channel_id": o.channel_id, "channel_name": o.channel_name,
                 "png": "/tmp/x.png", "day": TODAY, "error": None}
                for o in R.enrolled("eod")]
        slot = type("S", (), {"key": "eod", "label": "End of Day"})()

        with mock.patch.object(
                smp, "post_reply_with_image",
                lambda p, **kw: calls.append((kw["channel_id"], kw["mirror"]))), \
                mock.patch.object(KR, "token_path", lambda rec: None), \
                mock.patch.object(KR, "_caption", lambda *a, **k: "cap"):
            KR.post(recs, slot, dry_run=False, logfn=lambda m: None)

        self.assertEqual(len(calls), len(recs))          # nobody lost a board
        off = [c for c, m in calls if not m]
        self.assertEqual(off, ["C068PH3RFSM"])           # #alphalete-sales only


if __name__ == "__main__":
    unittest.main()
