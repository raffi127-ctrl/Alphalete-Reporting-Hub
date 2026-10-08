"""Looking up the day's B2B Metrics thread must never post.

2026-09-21 08:08: a laptop checking whether a board had landed called the old
`metrics_thread_ts`, which CREATED the parent whenever this machine's
thread_state.json had no entry (it only lives on the Lucy that posted) — two
empty "*B2B Metrics 09/21/2026*" posts went up on top of Lucy's real threads.

The Verizon Metrics thread (Carlos 2026-10-08) is held to the same rule, off
its OWN state file: the lookup never posts, the opener posts one parent per
channel per day, and neither ever reads or writes the B2B state.

Offline: a fake Slack client, the state files patched. Nothing is sent.

    python -m unittest automations.sales_boards.test_b2b_thread_lookup
"""
import contextlib
import datetime as dt
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import automations.b2b_quality.run as bq
from automations.sales_boards import render as render
from automations.sales_boards import run as sb
from automations.vantura_boards import canon_campaign, tab_for

DAY = dt.date(2026, 9, 21)
HEADER = "*B2B Metrics 09/21/2026*"
VZ_HEADER = "*Verizon Metrics 09/21/2026*"


class FakeSlack:
    def __init__(self, messages=()):
        self.messages = list(messages)
        self.posted = []

    def conversations_history(self, **kw):
        return {"messages": self.messages}

    def chat_postMessage(self, **kw):
        self.posted.append(kw)
        return {"ts": "9999.0001"}


class LookupNeverPosts(unittest.TestCase):

    def setUp(self):
        self.state = {}
        self.saved = []
        p1 = mock.patch.object(bq, "_load_state",
                               lambda day, chan: dict(self.state))
        p2 = mock.patch.object(bq, "_save_state",
                               lambda *a, **k: self.saved.append(a))
        p3 = mock.patch.object(sb, "_b2b_header", lambda today: HEADER)
        for p in (p1, p2, p3):
            p.start()
            self.addCleanup(p.stop)

    def test_no_state_no_thread_returns_none_and_posts_nothing(self):
        # The 08:08 case: laptop, no local state, and (here) no thread.
        slack = FakeSlack()
        self.assertIsNone(sb.find_b2b_metrics_thread_ts(slack, "C1", DAY))
        self.assertEqual(slack.posted, [])
        self.assertEqual(self.saved, [])

    def test_no_state_finds_lucys_thread_in_slack(self):
        # The laptop has no state file, but Lucy's 05:11 thread is there.
        slack = FakeSlack([{"ts": "1789985472.675019", "text": HEADER}])
        self.assertEqual(sb.find_b2b_metrics_thread_ts(slack, "C1", DAY),
                         "1789985472.675019")
        self.assertEqual(slack.posted, [])
        self.assertEqual(self.saved, [])

    def test_the_oldest_parent_wins_over_a_stray_duplicate(self):
        # History comes newest-first; the real thread is the earliest one.
        slack = FakeSlack([{"ts": "1789996106.872179", "text": HEADER},
                           {"ts": "1789985472.675019", "text": HEADER}])
        self.assertEqual(sb.find_b2b_metrics_thread_ts(slack, "C1", DAY),
                         "1789985472.675019")

    def test_a_reply_quoting_the_title_is_not_a_parent(self):
        slack = FakeSlack([{"ts": "5.0", "thread_ts": "4.0", "text": HEADER}])
        self.assertIsNone(sb.find_b2b_metrics_thread_ts(slack, "C1", DAY))

    def test_state_file_answers_without_asking_slack(self):
        self.state = {"thread_ts": "1.1"}
        slack = FakeSlack()
        slack.conversations_history = mock.Mock(side_effect=AssertionError)
        self.assertEqual(sb.find_b2b_metrics_thread_ts(slack, "C1", DAY), "1.1")

    def test_old_creating_name_is_gone(self):
        # Anything still calling it should fail loudly, not post.
        self.assertFalse(hasattr(sb, "metrics_thread_ts"))


class OpenerPostsOnlyWhenNothingExists(unittest.TestCase):

    def setUp(self):
        self.saved = []
        p1 = mock.patch.object(bq, "_load_state", lambda day, chan: {})
        p2 = mock.patch.object(bq, "_save_state",
                               lambda *a, **k: self.saved.append(a))
        p3 = mock.patch.object(sb, "_b2b_header", lambda today: HEADER)
        for p in (p1, p2, p3):
            p.start()
            self.addCleanup(p.stop)

    def test_missing_state_but_thread_in_slack_reuses_it(self):
        slack = FakeSlack([{"ts": "1789985472.675019", "text": HEADER}])
        ts = sb.open_b2b_metrics_thread(slack, "C1", DAY)
        self.assertEqual(ts, "1789985472.675019")
        self.assertEqual(slack.posted, [])
        self.assertEqual(self.saved[0][2], "1789985472.675019")

    def test_nothing_anywhere_opens_one(self):
        slack = FakeSlack()
        ts = sb.open_b2b_metrics_thread(slack, "C1", DAY)
        self.assertEqual(ts, "9999.0001")
        self.assertEqual(len(slack.posted), 1)
        self.assertEqual(slack.posted[0]["text"], HEADER)


# ---------------------------------------------------------------- Verizon --
class _VerizonFixture(unittest.TestCase):
    """The Verizon state helpers stand in for a file (a dict keyed by
    day|channel, so a save is visible to the next load — a retry pass);
    the B2B state helpers RECORD every call, and a Verizon path making one
    is a failure."""

    def setUp(self):
        self.store = {}
        self.b2b_calls = []

        def load(day, chan):
            return dict(self.store.get((day, chan), {}))

        def save(day, chan, ts, posted):
            self.store[(day, chan)] = {"thread_ts": ts, "posted": list(posted)}

        def b2b_load(*a, **k):
            self.b2b_calls.append(("load", a))
            return {}

        def b2b_save(*a, **k):
            self.b2b_calls.append(("save", a))

        for p in (mock.patch.object(sb, "_load_verizon_state", load),
                  mock.patch.object(sb, "_save_verizon_state", save),
                  mock.patch.object(bq, "_load_state", b2b_load),
                  mock.patch.object(bq, "_save_state", b2b_save),
                  mock.patch.object(sb, "_b2b_header", lambda today: HEADER)):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.assertEqual(self.b2b_calls, [],
                         "a Verizon path touched the B2B thread state")


class VerizonLookupNeverPosts(_VerizonFixture):

    def test_header_mirrors_the_b2b_parent(self):
        self.assertEqual(sb.verizon_header_title(DAY), "Verizon Metrics 09/21/2026")
        self.assertEqual(sb._verizon_header(DAY), VZ_HEADER)
        # The B2B parent for Carlos's office is the bare bold title+date;
        # the Verizon one is that exact shape with the title swapped.
        try:
            from automations.b2b_metrics import offices as MO
            from automations.b2b_metrics import runner as MR
        except Exception as e:  # noqa: BLE001 — hermetic elsewhere
            self.skipTest(f"b2b_metrics runner not importable here: {e}")
        b2b = MR.header_text(MO.OFFICES["carlos"], DAY)
        self.assertEqual(b2b, HEADER)
        self.assertEqual(sb._verizon_header(DAY),
                         b2b.replace("B2B Metrics", "Verizon Metrics"))

    def test_no_state_no_thread_returns_none_and_posts_nothing(self):
        slack = FakeSlack()
        self.assertIsNone(sb.find_verizon_metrics_thread_ts(slack, "C1", DAY))
        self.assertEqual(slack.posted, [])
        self.assertEqual(self.store, {})

    def test_no_state_finds_lucys_thread_in_slack(self):
        slack = FakeSlack([{"ts": "1789985472.675019", "text": VZ_HEADER}])
        self.assertEqual(sb.find_verizon_metrics_thread_ts(slack, "C1", DAY),
                         "1789985472.675019")
        self.assertEqual(slack.posted, [])
        self.assertEqual(self.store, {})          # a lookup writes nothing

    def test_the_oldest_parent_wins_over_a_stray_duplicate(self):
        slack = FakeSlack([{"ts": "1789996106.872179", "text": VZ_HEADER},
                           {"ts": "1789985472.675019", "text": VZ_HEADER}])
        self.assertEqual(sb.find_verizon_metrics_thread_ts(slack, "C1", DAY),
                         "1789985472.675019")

    def test_a_reply_quoting_the_title_is_not_a_parent(self):
        slack = FakeSlack([{"ts": "5.0", "thread_ts": "4.0", "text": VZ_HEADER}])
        self.assertIsNone(sb.find_verizon_metrics_thread_ts(slack, "C1", DAY))

    def test_the_b2b_parent_is_not_the_verizon_thread(self):
        # Only today's B2B thread exists: Verizon must NOT reuse it.
        slack = FakeSlack([{"ts": "1789985472.675019", "text": HEADER}])
        self.assertIsNone(sb.find_verizon_metrics_thread_ts(slack, "C1", DAY))

    def test_the_verizon_parent_is_not_the_b2b_thread(self):
        slack = FakeSlack([{"ts": "1789985472.675019", "text": VZ_HEADER}])
        self.assertIsNone(sb.find_b2b_metrics_thread_ts(slack, "C1", DAY))
        self.assertEqual(len(self.b2b_calls), 1)    # the B2B lookup reads ITS state
        self.b2b_calls.clear()

    def test_state_file_answers_without_asking_slack(self):
        self.store[(DAY, "C1")] = {"thread_ts": "1.1", "posted": []}
        slack = FakeSlack()
        slack.conversations_history = mock.Mock(side_effect=AssertionError)
        self.assertEqual(sb.find_verizon_metrics_thread_ts(slack, "C1", DAY), "1.1")

    def test_history_failure_degrades_to_none_not_a_post(self):
        slack = FakeSlack()
        slack.conversations_history = mock.Mock(side_effect=RuntimeError("missing_scope"))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(sb.find_verizon_metrics_thread_ts(slack, "C1", DAY))
        self.assertEqual(slack.posted, [])


class VerizonOpenerPostsOneParentPerChannelPerDay(_VerizonFixture):

    def test_nothing_anywhere_opens_one_and_remembers_it(self):
        slack = FakeSlack()
        with contextlib.redirect_stdout(io.StringIO()):
            ts = sb.open_verizon_metrics_thread(slack, "C1", DAY)
        self.assertEqual(ts, "9999.0001")
        self.assertEqual(slack.posted, [{"channel": "C1", "text": VZ_HEADER}])
        self.assertEqual(self.store[(DAY, "C1")]["thread_ts"], "9999.0001")

    def test_a_retry_pass_reuses_the_parent_without_asking_slack(self):
        slack = FakeSlack()
        with contextlib.redirect_stdout(io.StringIO()):
            sb.open_verizon_metrics_thread(slack, "C1", DAY)
        slack.conversations_history = mock.Mock(side_effect=AssertionError)
        self.assertEqual(sb.open_verizon_metrics_thread(slack, "C1", DAY),
                         "9999.0001")
        self.assertEqual(len(slack.posted), 1)

    def test_exactly_one_parent_per_channel(self):
        slack = FakeSlack()
        with contextlib.redirect_stdout(io.StringIO()):
            for chan in ("C07J46MQNUX", "C0AJQA8P716"):
                for _pass in range(3):
                    sb.open_verizon_metrics_thread(slack, chan, DAY)
        self.assertEqual([p["channel"] for p in slack.posted],
                         ["C07J46MQNUX", "C0AJQA8P716"])
        self.assertEqual(sorted(self.store), [(DAY, "C07J46MQNUX"),
                                              (DAY, "C0AJQA8P716")])

    def test_missing_state_but_thread_in_slack_reuses_it(self):
        # Lucy posted at 05:11; this machine has no state: adopt, don't open.
        slack = FakeSlack([{"ts": "1789985472.675019", "text": VZ_HEADER}])
        ts = sb.open_verizon_metrics_thread(slack, "C1", DAY)
        self.assertEqual(ts, "1789985472.675019")
        self.assertEqual(slack.posted, [])
        self.assertEqual(self.store[(DAY, "C1")]["thread_ts"], "1789985472.675019")

    def test_a_b2b_parent_does_not_stop_the_verizon_opener(self):
        slack = FakeSlack([{"ts": "1789985472.675019", "text": HEADER}])
        with contextlib.redirect_stdout(io.StringIO()):
            ts = sb.open_verizon_metrics_thread(slack, "C1", DAY)
        self.assertEqual(ts, "9999.0001")
        self.assertEqual(len(slack.posted), 1)


class VerizonStateFileIsItsOwn(unittest.TestCase):
    """The real helpers, on a temp dir: a sibling of b2b_quality's
    thread_state.json, never that file."""

    def test_default_paths_differ(self):
        self.assertNotEqual(sb.VERIZON_STATE_FILE.resolve(), bq.STATE_FILE.resolve())
        self.assertEqual(sb.VERIZON_STATE_FILE.name, "verizon_thread_state.json")
        self.assertEqual(sb.VERIZON_STATE_FILE.parent, sb.OUT_DIR)

    def test_round_trip_leaves_the_b2b_file_alone(self):
        with tempfile.TemporaryDirectory() as t:
            vz, b2b = Path(t) / "verizon_thread_state.json", Path(t) / "thread_state.json"
            with mock.patch.object(sb, "VERIZON_STATE_FILE", vz), \
                    mock.patch.object(bq, "STATE_FILE", b2b):
                self.assertEqual(sb._load_verizon_state(DAY, "C1"), {})
                sb._save_verizon_state(DAY, "C1", "1.1", [])
                self.assertEqual(sb._load_verizon_state(DAY, "C1"),
                                 {"thread_ts": "1.1", "posted": []})
                self.assertEqual(sb._load_verizon_state(DAY, "C2"), {})
                self.assertEqual(sb._load_verizon_state(DAY + dt.timedelta(days=1), "C1"), {})
                self.assertTrue(vz.exists())
                self.assertFalse(b2b.exists())
                self.assertEqual(bq._load_state(DAY, "C1"), {})

    def test_a_corrupt_file_reads_as_no_state(self):
        with tempfile.TemporaryDirectory() as t:
            vz = Path(t) / "verizon_thread_state.json"
            vz.write_text("{not json")
            with mock.patch.object(sb, "VERIZON_STATE_FILE", vz):
                self.assertEqual(sb._load_verizon_state(DAY, "C1"), {})
                sb._save_verizon_state(DAY, "C1", "2.2", ["x"])   # must not raise
                self.assertEqual(sb._load_verizon_state(DAY, "C1"),
                                 {"thread_ts": "2.2", "posted": ["x"]})


class VerizonJoinsThePostingSet(unittest.TestCase):

    def test_program_list(self):
        self.assertEqual(sb.PROGRAMS, ["B2B", "BOX", "Verizon"])
        self.assertIn("Verizon", render.PROGRAMS)
        self.assertIn("Verizon", render.PROGRAM_CAMPAIGNS)   # rep rows on the Verizon tab
        self.assertEqual(tab_for("Verizon"), "Verizon Sales Board")
        self.assertEqual(canon_campaign("Verizon"), "Verizon")
        # The 5:10 ladder (main's default) posts B2B + Verizon; BOX rides 7:25.
        self.assertEqual([p for p in sb.PROGRAMS if p != "BOX"], ["B2B", "Verizon"])

    def test_zero_streaks_stay_nds_plus_box(self):
        self.assertEqual(sb.ZEROS_PROGRAMS, ["B2B", "BOX"])

    def test_emoji_captions_and_filenames(self):
        self.assertEqual(sb.PROGRAM_EMOJI["Verizon"], ":satellite_antenna:")
        imgs = {"B2B": {"a": Path("b-a.png"), "b": Path("b-b.png")},
                "Verizon": {"a": Path("v-a.png"), "b": Path("v-b.png")}}
        out = sb._replies(imgs, {}, "9.20", want_zeros=False)
        self.assertEqual([plain for plain, _c, _u in out],
                         ["B2B Sales Board 9.20", "Verizon Sales Board 9.20"])
        plain, caption, ups = out[1]
        self.assertEqual(caption, ":satellite_antenna: *Verizon Sales Board 9.20*")
        self.assertEqual([f for _, f in ups], ["Verizon Sales Board 9.20 (a).png",
                                               "Verizon Sales Board 9.20 (b).png"])
        plain, caption, ups = sb._replies(imgs, {}, "9.20", False, corrected=True)[1]
        self.assertEqual(plain, "Verizon Sales Board 9.20 (corrected)")

    def test_thread_kind(self):
        self.assertEqual(sb.thread_kind("Verizon Sales Board 9.20"), "verizon")
        self.assertEqual(sb.thread_kind("BOX Sales Board 9.20"), "box")
        self.assertEqual(sb.thread_kind("B2B Sales Board 9.20"), "b2b")
        self.assertEqual(sb.thread_kind("Zero Streak 9.20 — 1 Day"), "b2b")

    def test_dry_run_routing_lists_the_verizon_reply(self):
        imgs = {"Verizon": {"a": Path("v-a.png"), "b": Path("v-b.png")}}
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("SALES_BOARD_CHANNEL_ID", None)
            out = sb.post_thread(imgs, {}, DAY, DAY - dt.timedelta(days=1), dry_run=True)
        self.assertEqual([r["id"] for r in out], [c for _n, c, _z in sb.TARGETS])
        for r in out:
            self.assertEqual(r["replies"],
                             [(":satellite_antenna: *Verizon Sales Board 9.20*",
                               ["Verizon Sales Board 9.20 (a).png",
                                "Verizon Sales Board 9.20 (b).png"])])

    def test_program_flag_accepts_verizon_and_dry_run_is_spelled_out(self):
        """main()'s own parser: `--program Verizon` (and `--dry-run`) parse,
        an unknown program is refused before any sheet is opened."""
        class Stop(Exception):
            pass
        with mock.patch.object(sb, "open_by_key", side_effect=Stop):
            with self.assertRaises(Stop):
                sb.main(["--program", "Verizon"])
            with self.assertRaises(Stop):
                sb.main(["--dry-run", "--program", "Verizon"])
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    sb.main(["--program", "Nope"])


if __name__ == "__main__":
    unittest.main()
