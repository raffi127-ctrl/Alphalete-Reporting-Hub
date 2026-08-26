"""Telling every channel that Tableau is behind — and never promising a time.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.tableau_screenshots.test_stale_notice

WHY (Megan 2026-08-26, the morning the trackers were behind): "can we post in
every channel letting them know updated ones will be posted when it's updated."

Two pieces, and the point of both is that a note has to be TRUE:

  1. A board held because its Tableau extract hasn't refreshed gets the
     STALE_LATE_NOTE wording, not Box's "~7am". We control when Box lands; we do
     not control when Tableau catches up, and a note naming a time it misses is
     how a channel learns to stop reading the note.
  2. `annotate_today` edits today's EXISTING parent — it never posts a new
     message and never creates a thread. A channel with no thread today is
     reported, not filled with a heads-up about boards that were never promised.

Plus the two things that would quietly corrupt a thread: dropping an *UPDATED*
tag that's already on the header, and annotating a board that merely failed to
capture as "still coming".
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.tableau_screenshots import slack_post as sp
from automations.tableau_screenshots import pages as pg


class _Client:
    """Slack stub: one channel has today's thread, another has none."""

    def __init__(self, with_thread=("C_HAS",), parent_text=None):
        self.with_thread = set(with_thread)
        self.parent_text = parent_text
        self.updates = []          # (channel, ts, text)
        self.posted = []           # anything posted — must stay EMPTY

    def conversations_history(self, channel, **kw):
        if channel not in self.with_thread:
            return {"messages": []}
        text = self.parent_text or f"*{sp.header_title(dt.date(2026, 8, 26))}*"
        return {"messages": [{"ts": "111.222", "text": text}]}

    def conversations_replies(self, channel, ts, **kw):
        return {"messages": []}    # no images in the thread yet

    def chat_update(self, channel, ts, text, **kw):
        self.updates.append((channel, ts, text))
        return {"ok": True}

    def chat_postMessage(self, channel, text, **kw):
        self.posted.append((channel, text))
        return {"ok": True, "ts": "333.444"}

    def files_upload_v2(self, **kw):
        self.posted.append(("file", kw.get("channel")))
        return {"ok": True, "file": {"id": "F1"}}


class StaleNoteWordingTest(unittest.TestCase):
    """A held board must not inherit Box's "~7am" promise."""

    TODAY = dt.date(2026, 8, 26)

    def tearDown(self):
        pg.clear_runtime_late()

    def test_runtime_held_board_gets_the_tableau_wording(self):
        pg.mark_late(["nds"])
        text = sp.header_text(pg.PAGES, self.TODAY, pending_late=["nds"])
        line = next(l for l in text.splitlines() if "NDS Tracker" in l)
        self.assertIn(sp.STALE_LATE_NOTE, line)
        self.assertNotIn("~7am", line)

    def test_box_keeps_its_own_schedule_note(self):
        """Box is late by SCHEDULE, so "~7am" is the honest note for it — and it
        stays that way even on a morning when another board was held."""
        pg.mark_late(["nds"])
        text = sp.header_text(pg.PAGES, self.TODAY,
                              pending_late=["nds", "b2b_box"])
        box = next(l for l in text.splitlines() if "Box Tracker" in l)
        self.assertIn(sp.LATE_NOTE, box)
        self.assertNotIn(sp.STALE_LATE_NOTE, box)

    def test_a_board_that_is_not_pending_carries_no_note_at_all(self):
        pg.mark_late(["nds"])
        text = sp.header_text(pg.PAGES, self.TODAY, pending_late=[])
        self.assertNotIn(sp.STALE_LATE_NOTE, text)
        self.assertNotIn(sp.LATE_NOTE, text)


class AnnotateTodayTest(unittest.TestCase):

    TODAY = dt.date(2026, 8, 26)

    def _use(self, client):
        real = sp.smp._client
        sp.smp._client = lambda *a, **k: client
        self.addCleanup(setattr, sp.smp, "_client", real)

    def _org(self, channels):
        orig_c, orig_l = dict(sp.ORG_CHANNELS), dict(sp.ORG_LABEL)
        sp.ORG_CHANNELS["_t"] = list(channels)
        sp.ORG_LABEL["_t"] = "#test"
        self.addCleanup(lambda: (sp.ORG_CHANNELS.clear(),
                                 sp.ORG_CHANNELS.update(orig_c),
                                 sp.ORG_LABEL.clear(),
                                 sp.ORG_LABEL.update(orig_l)))
        return "_t"

    def tearDown(self):
        pg.clear_runtime_late()

    def test_the_note_lands_in_the_existing_header_and_nothing_is_posted(self):
        c = _Client(with_thread=["C_HAS"])
        self._use(c)
        res = sp.annotate_today(pg.PAGES, self.TODAY, org=self._org(["C_HAS"]))
        self.assertEqual([r["status"] for r in res["results"]], ["annotated"])
        self.assertEqual(c.posted, [], "annotate must never post a message")
        self.assertIn(sp.STALE_NOTICE, c.updates[0][2])

    def test_no_thread_today_is_reported_never_created(self):
        c = _Client(with_thread=[])
        self._use(c)
        res = sp.annotate_today(pg.PAGES, self.TODAY, org=self._org(["C_NONE"]))
        self.assertEqual([r["status"] for r in res["results"]],
                         ["no thread today"])
        self.assertEqual(c.posted, [])
        self.assertEqual(c.updates, [])

    def test_an_updated_tag_already_on_the_header_survives(self):
        """Re-rendering the header must not demote a corrected thread back to
        looking like the morning's wrong one."""
        parent = (f"*{sp.header_title(self.TODAY)}*  {sp.UPDATED_TAG}")
        c = _Client(with_thread=["C_HAS"], parent_text=parent)
        self._use(c)
        sp.annotate_today(pg.PAGES, self.TODAY, org=self._org(["C_HAS"]))
        self.assertIn(sp.UPDATED_TAG, c.updates[0][2])

    def test_only_late_boards_are_annotated_as_still_coming(self):
        """No image is in the thread in this stub, yet only the LATE boards may
        be promised — a board that simply failed to capture is not owed."""
        c = _Client(with_thread=["C_HAS"])
        self._use(c)
        res = sp.annotate_today(pg.PAGES, self.TODAY, org=self._org(["C_HAS"]))
        self.assertEqual(res["results"][0]["pending"],
                         [p["id"] for p in pg.PAGES if pg.is_late(p)])

    def test_dry_run_reads_nothing_and_writes_nothing(self):
        c = _Client(with_thread=["C_HAS"])
        self._use(c)
        res = sp.annotate_today(pg.PAGES, self.TODAY, org=self._org(["C_HAS"]),
                                dry_run=True)
        self.assertTrue(res["dry_run"])
        self.assertIn(sp.STALE_NOTICE, res["header"])
        self.assertEqual((c.updates, c.posted), ([], []))

    def test_custom_text_overrides_the_standard_wording(self):
        c = _Client(with_thread=["C_HAS"])
        self._use(c)
        sp.annotate_today(pg.PAGES, self.TODAY, org=self._org(["C_HAS"]),
                          note="Tableau is down; updates land here.")
        self.assertIn("Tableau is down", c.updates[0][2])
        self.assertNotIn(sp.STALE_NOTICE, c.updates[0][2])


if __name__ == "__main__":
    unittest.main()
