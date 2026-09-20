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
    the string 'boom' = the history read itself fails; a ``Deleted(ids)`` = the
    parent was deleted but those board images survive under the tombstone."""

    def __init__(self, by_channel):
        self.by_channel = by_channel


class Deleted:
    """Today's parent is gone; `ids` are the images still under its tombstone."""

    def __init__(self, ids):
        self.ids = set(ids)


def _patched(fake: FakeClient):
    """Patch the three slack_post readers reconcile() depends on."""

    def find_today_threads(client, channel, today):
        val = fake.by_channel.get(channel, set())
        if val == "boom":
            raise sp.DedupReadUnavailable("conversations.history timed out")
        if val is None or isinstance(val, Deleted):
            return []                             # no LIVE parent today
        if isinstance(val, list):                 # several threads today
            return [f"111.{i}" for i in range(len(val))]
        return ["111.222"]

    def find_today_tombstones(client, channel, today):
        val = fake.by_channel.get(channel, set())
        if val == "boom":
            raise sp.DedupReadUnavailable("conversations.history timed out")
        return ["999.000"] if isinstance(val, Deleted) else []

    def posted_ids(client, channel, thread_ts, pages, today):
        val = fake.by_channel.get(channel, set())
        if val == "boom":
            raise sp.DedupReadUnavailable("conversations.history timed out")
        if isinstance(val, Deleted):
            return set(val.ids)
        if isinstance(val, list):
            return set(val[int(thread_ts.split(".")[1])])
        return set(val or ())

    return (mock.patch.object(sp, "find_today_threads", find_today_threads),
            mock.patch.object(sp, "posted_ids", posted_ids),
            mock.patch.object(sp, "find_today_tombstones",
                              find_today_tombstones))


def run_reconcile(by_channel, orgs, *, now=LATE_ENOUGH):
    fake = FakeClient(by_channel)
    p1, p2, p3 = _patched(fake)
    with p1, p2, p3:
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


class TestUpdatedRerunThread(unittest.TestCase):
    """2026-09-18: the 08:49 Box rerun opened an *UPDATED* thread holding only
    Box; the other 8 boards were in the 04:47 thread. Reading just the newest
    thread called all 8 "missing from ALL channels"."""

    def test_boards_split_across_two_threads_are_all_present(self):
        org = "elevate"
        owed = rp.expected_for(org, DAY, now=LATE_ENOUGH)
        morning = set(owed) - {"b2b_box"}
        rep = run_reconcile({_chans(org)[0]: [{"b2b_box"}, morning]}, [org])
        self.assertTrue(rep.clean, rep.orgs[0].missing)

    def test_a_board_in_neither_thread_is_still_missing(self):
        org = "elevate"
        owed = rp.expected_for(org, DAY, now=LATE_ENOUGH)
        morning = set(owed) - {"b2b_box", "nds"}
        rep = run_reconcile({_chans(org)[0]: [{"b2b_box"}, morning]}, [org])
        self.assertEqual(rep.orgs[0].missing, ["nds"])


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


class TestADeletedThreadIsNotAMissingOne(unittest.TestCase):
    """2026-09-20, #ambient-sales-1. All nine boards posted (5 at 06:49, 4 in the
    07:05 Box run) and BOTH parents were then deleted in the channel. The audit
    said "NO THREAD (owed 9)" — the same words it uses when a capture run dies
    and nothing is posted anywhere — and the remediation it offered was to re-run
    the capture, which would have burned a Tableau login and fixed nothing."""

    def test_a_deleted_thread_is_not_reported_as_no_thread(self):
        org = "elevate"
        owed = set(rp.expected_for(org, DAY, now=LATE_ENOUGH))
        rep = run_reconcile({_chans(org)[0]: Deleted(owed)}, [org])
        res = rep.orgs[0]
        self.assertFalse(res.thread_missing,
                         "the boards ARE in the channel — this is not a no-post")
        self.assertTrue(res.deleted_thread)
        self.assertEqual(res.missing, [])
        self.assertEqual(set(res.present), owed)

    def test_it_still_counts_as_a_problem(self):
        """What the office sees is 'This message was deleted.' with loose images
        under it. Nine delivered boards nobody can read is not a clean day."""
        org = "elevate"
        owed = set(rp.expected_for(org, DAY, now=LATE_ENOUGH))
        rep = run_reconcile({_chans(org)[0]: Deleted(owed)}, [org])
        self.assertFalse(rep.clean)
        self.assertTrue(rp.failed_parts(rep))

    def test_the_bullet_says_deleted_and_how_many_survived(self):
        org = "elevate"
        owed = set(rp.expected_for(org, DAY, now=LATE_ENOUGH))
        rep = run_reconcile({_chans(org)[0]: Deleted(owed)}, [org])
        blob = " ".join(rp.failed_parts(rep))
        self.assertIn("DELETED", blob)
        self.assertIn(str(len(owed)), blob)
        self.assertNotIn("no tracker thread at all today", blob)

    def test_the_remediation_says_do_not_re_run_the_capture(self):
        org = "elevate"
        owed = set(rp.expected_for(org, DAY, now=LATE_ENOUGH))
        rep = run_reconcile({_chans(org)[0]: Deleted(owed)}, [org])
        with mock.patch("automations.shared.section_drop_alert.alert") as al:
            al.return_value = True
            rp.alert_if_incomplete(rep)
        fix = al.call_args.kwargs["remediation"]["fix"]
        self.assertIn("Do NOT re-run the capture", fix)
        self.assertIn("--new-thread", fix)
        self.assertNotEqual(al.call_args.kwargs["kind"], "no_post")

    def test_a_deleted_thread_missing_boards_reports_both(self):
        """The parent was deleted AND a board never landed — two different facts,
        two bullets, neither hiding the other."""
        org = "elevate"
        owed = set(rp.expected_for(org, DAY, now=LATE_ENOUGH))
        rep = run_reconcile({_chans(org)[0]: Deleted(owed - {"nds"})}, [org])
        parts = rp.failed_parts(rep)
        self.assertTrue([p for p in parts if "DELETED" in p], parts)
        self.assertTrue([p for p in parts if "NDS Tracker" in p], parts)

    def test_a_tombstone_with_none_of_our_boards_is_still_no_thread(self):
        """Somebody deleting an unrelated message must not be read as our
        thread: a tombstone only counts when our captions are under it."""
        org = "elevate"
        rep = run_reconcile({_chans(org)[0]: Deleted(set())}, [org])
        self.assertTrue(rep.orgs[0].thread_missing)
        self.assertFalse(rep.orgs[0].deleted_thread)


class TestCrossWorkspaceOrgIsReadWithItsOwnToken(unittest.TestCase):
    """trang's #freshsuccess-* channels are in the FRESH SUCCESS workspace. The
    audit built ONE client from the AO token and read every org with it, so Slack
    answered `channel_not_found` and FreshSuccess came back UNREADABLE every
    single day (seen 2026-09-20) — permanent blind coverage on the one org that
    has actually broken twice. run.py already routes the POST this way."""

    def test_trang_has_a_cross_workspace_token_file(self):
        from automations.office_metrics.offices import CROSS_WS_TOKEN_FILES
        self.assertIn("trang", CROSS_WS_TOKEN_FILES)

    def test_a_normal_org_keeps_the_default_client(self):
        sentinel = object()
        self.assertIs(rp._client_for("elevate", sentinel), sentinel)

    def test_a_cross_ws_org_builds_a_client_from_its_own_token(self):
        sentinel, built = object(), object()
        with mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch("pathlib.Path.read_text", return_value="xoxb-fs\n"), \
             mock.patch("automations.shared.slack_metrics_post._client",
                        return_value=built) as mk:
            got = rp._client_for("trang", sentinel)
        self.assertIs(got, built)
        self.assertTrue(mk.called)

    def test_the_ao_token_is_restored_afterwards(self):
        """The env var is shared process-wide — leaking the FS token into it
        would make every org AFTER trang read the wrong workspace."""
        import os
        os.environ["SLACK_USER_TOKEN"] = "xoxp-ao"
        try:
            with mock.patch("pathlib.Path.exists", return_value=True), \
                 mock.patch("pathlib.Path.read_text", return_value="xoxb-fs\n"), \
                 mock.patch("automations.shared.slack_metrics_post._client",
                            return_value=object()):
                rp._client_for("trang", object())
            self.assertEqual(os.environ["SLACK_USER_TOKEN"], "xoxp-ao")
        finally:
            os.environ.pop("SLACK_USER_TOKEN", None)

    def test_a_missing_token_file_falls_back_and_stays_honest(self):
        """No FS token on this machine -> the read genuinely fails -> the org is
        reported unreadable. That is the truthful answer, not a fake gap."""
        sentinel = object()
        with mock.patch("pathlib.Path.exists", return_value=False):
            self.assertIs(rp._client_for("trang", sentinel), sentinel)

    def test_an_explicit_client_is_never_re_routed(self):
        """A caller that handed us a client (the tests) must not have a token
        file read out from under it."""
        with mock.patch.object(rp, "_client_for") as cf:
            run_reconcile({c: set() for c in _chans("elevate")}, ["elevate"])
        self.assertFalse(cf.called)


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
