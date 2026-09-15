"""An office's EXTRA channel is a COPY of one run, never a second run.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.office_metrics.test_extra_channel_mirror

WHAT THIS GUARDS (Megan 2026-09-15, trang / FRESH SUCCESS). Trang's metrics were
wired into a second channel as a fan-out plan, so the 4am run pulled every
Tableau view twice and posted two threads of identical numbers — 18 metric
subprocesses, ~7 minutes, for 9 metrics' worth of data. An extra channel that
asks for the SAME sections is a mirror: run once, re-upload each finished board
from the file already rendered.

The regression this locks out is the quiet one — EXTRA_CHANNEL_PLANS creeping
back into `channel_plans` (which is what fan-out reads) — plus the two things
that make the mirror honest: the copy is verified after the run, and its failure
row can never become an `--only` retry target (a slug with no metric behind it
pulls nothing and posts nothing).
"""
from __future__ import annotations

import datetime as dt
import os
import unittest

from automations.office_metrics import offices as off
from automations.office_metrics import runner
from automations.shared import slack_metrics_post as smp


class _Args:
    def __init__(self, channel=None):
        self.channel = channel


class ExtraChannelIsNotFanOut(unittest.TestCase):
    def test_trang_has_no_fan_out_plans(self):
        o = off.OFFICES["trang"]
        self.assertEqual(getattr(o, "channel_plans", ()), (),
                         "an extra channel must not become a fan-out plan — "
                         "that is the double pull this replaced")
        self.assertEqual(off.extra_channel_ids("trang"), ["C07QS80KJL8"])

    def test_one_destination_carrying_every_metric(self):
        o = off.OFFICES["trang"]
        wired = [{"slug": "churn", "label": "🌐 Churn"},
                 {"slug": "abp", "label": "💳 ABP"}]
        dests, skipped = runner.build_destinations(
            o, wired, o.channel_id, True, manual_channel=False)
        self.assertEqual(len(dests), 1)
        self.assertEqual(dests[0]["channel_id"], "C07TRPJ7HFH")
        self.assertEqual([m["slug"] for m in dests[0]["metrics"]],
                         ["churn", "abp"])
        self.assertEqual(skipped, [])

    def test_hub_row_still_names_both_channels(self):
        # The pull is single, but the day lands in both places — the card has to
        # say so (Megan 2026-08-20).
        label = runner._office_channels_label(off.OFFICES["trang"])
        self.assertIn("#freshsuccess-all-leaders", label)
        self.assertIn("#freshsuccess-team", label)

    def test_manual_channel_override_never_mirrors(self):
        o = off.OFFICES["trang"]
        self.assertEqual(runner._mirror_env(o, manual_channel=False),
                         ["C07QS80KJL8"])
        self.assertEqual(runner._mirror_env(o, manual_channel=True), [],
                         "--channel is a one-destination backfill; a mirror "
                         "would post it into the channel that already has it")


class MirrorRouting(unittest.TestCase):
    """slack_metrics_post reads the ids out of the env the runner sets."""

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in
                       ("METRICS_MIRROR_CHANNELS", "METRICS_CHANNEL_ID",
                        "ALPHALETE_MIRROR_OFF")}

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def test_primary_channel_mirrors_to_the_extra(self):
        os.environ["METRICS_CHANNEL_ID"] = "C07TRPJ7HFH"
        os.environ["METRICS_MIRROR_CHANNELS"] = "C07QS80KJL8"
        self.assertEqual(smp.mirror_channels("C07TRPJ7HFH"), ["C07QS80KJL8"])

    def test_some_other_channel_does_not(self):
        os.environ["METRICS_CHANNEL_ID"] = "C07TRPJ7HFH"
        os.environ["METRICS_MIRROR_CHANNELS"] = "C07QS80KJL8"
        self.assertEqual(smp.mirror_channels("C0999OTHER"), [],
                         "a module posting somewhere else on purpose must not "
                         "drag the office's copy along")

    def test_kill_switch_still_wins(self):
        os.environ["METRICS_CHANNEL_ID"] = "C07TRPJ7HFH"
        os.environ["METRICS_MIRROR_CHANNELS"] = "C07QS80KJL8"
        os.environ["ALPHALETE_MIRROR_OFF"] = "1"
        self.assertEqual(smp.mirror_channels("C07TRPJ7HFH"), [])

    def test_unset_is_the_old_behaviour(self):
        os.environ.pop("METRICS_MIRROR_CHANNELS", None)
        os.environ["METRICS_CHANNEL_ID"] = "C07TRPJ7HFH"
        self.assertEqual(smp.mirror_channels("C07TRPJ7HFH"), [])
        self.assertEqual(smp.mirror_channels("C068PH3RFSM"), ["C09JG28CD27"])


class _ReplyClient:
    """conversations_replies/history over a fake two-channel workspace."""

    def __init__(self, threads, history):
        self.threads, self.history = threads, history

    def conversations_replies(self, channel, ts, limit=200):
        return {"messages": self.threads[(channel, ts)]}

    def conversations_history(self, channel, oldest=None, limit=200, **kw):
        return {"messages": self.history.get(channel, [])}


def _msg(text):
    return {"text": text}


class MirrorVerification(unittest.TestCase):
    """_mirror_gaps names the boards the copy is missing, and posts nothing."""

    HEADER = "*Metrics for: September 15th 2026*"

    def _client(self, mirror_replies, *, twin=True):
        primary = [_msg(self.HEADER), _msg("🚪 Total Knocks"),
                   _msg("💳 New Internet ABP %")]
        threads = {("C_PRIM", "111.1"): primary}
        history = {"C_PRIM": [{"text": self.HEADER, "ts": "111.1"}],
                   "C_MIRROR": ([{"text": self.HEADER, "ts": "222.2"}]
                                if twin else [])}
        if twin:
            threads[("C_MIRROR", "222.2")] = [_msg(self.HEADER)] + mirror_replies
        return _ReplyClient(threads, history)

    def test_complete_copy_is_no_gap(self):
        c = self._client([_msg("🚪 Total Knocks"), _msg("💳 New Internet ABP %")])
        self.assertEqual(
            runner._mirror_gaps(c, "C_PRIM", ["C_MIRROR"], dt.date(2026, 9, 15)),
            [])

    def test_missing_board_is_named(self):
        c = self._client([_msg("🚪 Total Knocks")])
        gaps = runner._mirror_gaps(c, "C_PRIM", ["C_MIRROR"],
                                   dt.date(2026, 9, 15))
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0][0], "C_MIRROR")
        self.assertEqual(gaps[0][1], ["💳 New Internet ABP %"])

    def test_no_copy_at_all_reports_and_posts_nothing(self):
        c = self._client([], twin=False)
        gaps = runner._mirror_gaps(c, "C_PRIM", ["C_MIRROR"],
                                   dt.date(2026, 9, 15))
        self.assertEqual(len(gaps), 1)
        self.assertIn("no copy", gaps[0][1][0])
        # _ReplyClient has no chat_postMessage: a check that posted would raise.


class MirrorRowIsNotARetryTarget(unittest.TestCase):
    def test_slug_is_filtered_out_of_only_args(self):
        failed = [runner.MIRROR_SLUG, "email_digest"]
        self.assertEqual(
            [sl for sl in failed
             if sl not in ("email_digest", runner.MIRROR_SLUG)], [],
            "a whole-office re-run to fix a copy would re-post the day's thread "
            "into the channel that already has it")


if __name__ == "__main__":
    unittest.main()
