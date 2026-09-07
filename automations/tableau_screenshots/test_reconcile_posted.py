"""The 2026-09-07 morning, as a test: a capture run dies before write_manifest,
8 of 9 boards never post, and NOTHING alerts. Each test below is one half of why
that was silent, or one half of why the fix must not become noise.
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.tableau_screenshots import pages as pages_mod
from automations.tableau_screenshots import reconcile_posted as rp
from automations.tableau_screenshots import slack_post as sp

DAY = dt.date(2026, 9, 7)
LATE_ENOUGH = dt.datetime(2026, 9, 7, 15, 0)     # past LATE_DUE + SETTLE_DONE
EARLY = dt.datetime(2026, 9, 7, 4, 45)           # the 4:31 batch has just run


class FakeClient:
    """Channels -> the board ids sitting in today's thread. None = no thread;
    the string 'boom' = the history read itself fails."""

    def __init__(self, by_channel):
        self.by_channel = by_channel


def _patched(fake: FakeClient):
    """Patch the two slack_post readers reconcile() depends on."""

    def find_thread_ts(client, channel, today):
        val = fake.by_channel.get(channel, set())
        if val == "boom":
            raise sp.DedupReadUnavailable("conversations.history timed out")
        if val is None:
            return (None, False)
        return ("111.222", False)

    def posted_ids(client, channel, thread_ts, pages, today):
        val = fake.by_channel.get(channel, set())
        if val == "boom":
            raise sp.DedupReadUnavailable("conversations.history timed out")
        return set(val or ())

    return (mock.patch.object(sp, "find_thread_ts", find_thread_ts),
            mock.patch.object(sp, "posted_ids", posted_ids))


def run_reconcile(by_channel, orgs, *, now=LATE_ENOUGH):
    fake = FakeClient(by_channel)
    p1, p2 = _patched(fake)
    with p1, p2:
        return rp.reconcile(DAY, client=fake, orgs=orgs, now=now)


def _chans(org):
    return sp.channels_for(org)


class TestTheSilentMorning(unittest.TestCase):
    """The bug: 1 board posted, 8 missing, and the channel heard nothing."""

    def test_eight_missing_boards_are_reported(self):
        org = "elevate"                       # single-channel org, simple case
        ch = _chans(org)[0]
        rep = run_reconcile({ch: {"b2b_box"}}, [org])
        res = rep.orgs[0]
        self.assertFalse(rep.clean, "1-of-9 must not read as a clean morning")
        self.assertIn("b2b_box", res.present)
        self.assertGreater(len(res.missing), 5)
        self.assertNotIn("b2b_box", res.missing)

    def test_alert_fires_with_the_missing_boards(self):
        org = "elevate"
        rep = run_reconcile({_chans(org)[0]: {"b2b_box"}}, [org])
        parts = rp.failed_parts(rep)
        self.assertTrue(parts)
        blob = " ".join(parts)
        self.assertIn("AT&T Internet Country Sales Tracker", blob)
        self.assertNotIn("B2B Box Tracker —", blob)   # the one that DID post

    def test_a_complete_thread_alerts_nothing(self):
        org = "elevate"
        rep = run_reconcile({_chans(org)[0]: set(rp.expected_for(org, DAY,
                                                                now=LATE_ENOUGH))},
                            [org])
        self.assertTrue(rep.clean)
        self.assertEqual(rp.failed_parts(rep), [])
        self.assertFalse(rp.alert_if_incomplete(rep, dry_run=True))


class TestStayQuietWhenItCannotTell(unittest.TestCase):
    """An unreadable channel is UNKNOWN, never a drop. Slack latency made every
    history read time out on 2026-09-07; claiming those channels were empty would
    have raised a false alarm on top of a real one."""

    def test_unreadable_channel_is_not_a_miss(self):
        org = "elevate"
        rep = run_reconcile({_chans(org)[0]: "boom"}, [org])
        self.assertEqual(len(rep.unreadable), 1)
        self.assertEqual(rep.readable, [])
        self.assertEqual(rp.failed_parts(rep), [])
        self.assertTrue(rep.clean, "unknown is not dirty")

    def test_unreadable_channel_is_named_in_the_note(self):
        """It must be VISIBLE that coverage had a hole, without being an alarm."""
        rep = run_reconcile({_chans("elevate")[0]: "boom",
                             _chans("palace")[0]: {"b2b_box"}},
                            ["elevate", "palace"])
        with mock.patch("automations.shared.section_drop_alert.alert") as al:
            al.return_value = True
            rp.alert_if_incomplete(rep)
        note = al.call_args.kwargs["note"]
        self.assertIn("could not be read", note)
        self.assertIn(sp.ORG_LABEL["elevate"], note)


class TestLateBoardsAreNotMissingYet(unittest.TestCase):
    """Box is DELIBERATELY absent at 4:31. Alerting then would fire every day and
    teach everyone to ignore the alert — the failure mode this whole fix exists
    to prevent."""

    def test_late_board_excluded_before_its_window(self):
        want = rp.expected_for("elevate", DAY, now=EARLY)
        self.assertNotIn("b2b_box", want)

    def test_late_board_expected_after_its_window(self):
        want = rp.expected_for("elevate", DAY, now=LATE_ENOUGH)
        self.assertIn("b2b_box", want)

    def test_morning_thread_without_box_is_clean_at_4am(self):
        org = "elevate"
        want = rp.expected_for(org, DAY, now=EARLY)
        rep = run_reconcile({_chans(org)[0]: set(want)}, [org], now=EARLY)
        self.assertTrue(rep.clean)
        self.assertEqual(rp.failed_parts(rep), [])


class TestNoThreadAtAll(unittest.TestCase):
    def test_missing_thread_is_flagged_as_no_post(self):
        org = "elevate"
        rep = run_reconcile({_chans(org)[0]: None}, [org])
        self.assertTrue(rep.orgs[0].thread_missing)
        self.assertIn("no tracker thread at all today",
                      " ".join(rp.failed_parts(rep)))

    def test_kind_is_no_post_when_only_threads_are_missing(self):
        rep = run_reconcile({_chans("elevate")[0]: None}, ["elevate"])
        with mock.patch("automations.shared.section_drop_alert.alert") as al:
            al.return_value = True
            rp.alert_if_incomplete(rep)
        self.assertEqual(al.call_args.kwargs["kind"], "no_post")


class TestTheAlertStaysReadable(unittest.TestCase):
    """Megan's standing rule for this channel: a drop must read at a glance. 8
    boards x 10 orgs must not become 80 bullet lines."""

    def test_board_missing_everywhere_is_one_line(self):
        orgs = ["elevate", "palace", "indelible"]
        by_ch = {}
        for o in orgs:
            for c in _chans(o):
                by_ch[c] = {"b2b_box"}          # everything else missing
        rep = run_reconcile(by_ch, orgs)
        parts = rp.failed_parts(rep)
        # ONE line per missing BOARD, not one per (board, channel): 8 boards
        # across 3 orgs is 8 lines here and would be 24 uncompressed.
        att = [p for p in parts
               if p == "AT&T Internet Country Sales Tracker — missing from ALL channels"]
        self.assertEqual(len(att), 1, f"expected one compressed line, got {parts}")
        self.assertEqual(len(parts), 8, f"one line per board, got {parts}")
        self.assertFalse([p for p in parts if sp.ORG_LABEL["palace"] in p],
                         "a board missing everywhere must not also be listed per-org")

    def test_one_org_specific_gap_names_that_org(self):
        orgs = ["elevate", "palace"]
        full = set(rp.expected_for("elevate", DAY, now=LATE_ENOUGH))
        by_ch = {c: set(full) for o in orgs for c in _chans(o)}
        for c in _chans("palace"):
            by_ch[c] = full - {"nds"}
        rep = run_reconcile(by_ch, orgs)
        parts = rp.failed_parts(rep)
        self.assertEqual(len(parts), 1, parts)
        self.assertIn(sp.ORG_LABEL["palace"], parts[0])
        self.assertIn("NDS Tracker", parts[0])


class TestExpectedSetTracksTheRealDeclarations(unittest.TestCase):
    """The audit must read the SAME source the poster reads, or the two drift and
    the reconciliation quietly audits the wrong list."""

    def test_subset_org_is_only_owed_its_subset(self):
        want = set(rp.expected_for("domin8", DAY, now=LATE_ENOUGH))
        self.assertEqual(want, set(sp.ORG_TRACKERS["domin8"]))
        self.assertNotIn("nds", want)

    def test_default_org_is_owed_every_non_opt_in_board(self):
        want = set(rp.expected_for("elevate", DAY, now=LATE_ENOUGH))
        self.assertEqual(want, set(pages_mod.default_ids()))

    def test_opt_in_board_never_expected_org_wide(self):
        for org in ("elevate", "palace", "alphalete"):
            self.assertNotIn("order_tiered_bonus",
                             rp.expected_for(org, DAY, now=LATE_ENOUGH),
                             f"{org} should not be owed an opt-in-only board")


class TestWatcherNeverFailsItself(unittest.TestCase):
    def test_main_exits_zero_even_when_boards_are_missing(self):
        rep = run_reconcile({_chans("elevate")[0]: {"b2b_box"}}, ["elevate"])
        with mock.patch.object(rp, "reconcile", return_value=rep), \
             mock.patch.object(rp, "alert_if_incomplete", return_value=True):
            self.assertEqual(rp.main(["--alert", "--dry-run"]), 0)


if __name__ == "__main__":
    unittest.main()
