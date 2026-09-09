"""A phase that finished is not a report that delivered (Megan 2026-09-09).

THE CASE THIS FIXES. leaders_call is a two-phase Monday card — hub_cards
`daily_runs {"0": 2}`: the 2pm run pulls the campaigns and writes the tab, the
7:30pm --finalize pass builds the recognition deck and posts it to
#top-leaders-alphalete-org and #alphalete-gp-sales. Both phases publish
`success`, and hub_publish._clear_failure fired on the FIRST one, closing
whatever alert thread the report had open.

On 2026-09-08 that produced two "✅ RESOLVED. It just ran clean." posts in
#claudecorrections (13:39 and 14:34) on a Monday when the deck reached NEITHER
channel. Both greens were false and the "didn't run today" ticket that should
have carried the morning was rolled over unfixed underneath them.

Every daily_runs > 1 card had this — about twenty of them.

    python -m unittest automations.day_orchestrator.test_phase_close_gate
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.day_orchestrator import hub_publish as hp
from automations.day_orchestrator import reconcile


class ExpectedRunsToday(unittest.TestCase):
    """The phase count is READ from the card, never guessed — the same
    declaration the Hub's own pill counts against."""

    def _with_card(self, card_id, rec):
        return (mock.patch.object(hp, "hub_card_id", return_value=card_id),
                mock.patch("automations.hub_cards.AUTOMATED_REPORTS", [rec]))

    def test_a_weekday_keyed_count_reads_that_weekday(self):
        card, cards = self._with_card(
            "leaders-call", {"id": "leaders-call", "daily_runs": {"0": 2}})
        with card, cards:
            monday, tuesday = dt.date(2026, 9, 7), dt.date(2026, 9, 8)
            self.assertEqual(hp.expected_runs_today("leaders_call", monday), 2)
            # Not scheduled Tuesday: nothing declared, so nothing is held back.
            self.assertEqual(hp.expected_runs_today("leaders_call", tuesday), 1)

    def test_a_flat_count_reads_as_is(self):
        card, cards = self._with_card("x", {"id": "x", "daily_runs": 3})
        with card, cards:
            self.assertEqual(hp.expected_runs_today("x", dt.date(2026, 9, 8)), 3)

    def test_an_ordinary_card_is_one_pass(self):
        card, cards = self._with_card("x", {"id": "x"})
        with card, cards:
            self.assertEqual(hp.expected_runs_today("x", dt.date(2026, 9, 8)), 1)

    def test_an_unknown_card_never_holds_a_close_back(self):
        """Answering 1 keeps today's behaviour. This gate may only ever BLOCK a
        close on a declaration it can read — never invent one from a guess."""
        with mock.patch.object(hp, "hub_card_id", return_value=None):
            self.assertEqual(hp.expected_runs_today("nope"), 1)


class PhaseCompleteGate(unittest.TestCase):

    def test_phase_one_of_two_does_not_close_the_ticket(self):
        with mock.patch.object(hp, "expected_runs_today", return_value=2), \
             mock.patch.object(hp, "successful_runs_today", return_value=1):
            self.assertFalse(hp._phase_complete("leaders_call"))

    def test_the_final_phase_closes_it(self):
        with mock.patch.object(hp, "expected_runs_today", return_value=2), \
             mock.patch.object(hp, "successful_runs_today", return_value=2):
            self.assertTrue(hp._phase_complete("leaders_call"))

    def test_a_one_pass_report_never_pays_for_a_hub_read(self):
        """The overwhelming majority of publishes. Reading the Activity log on
        every one of them would put a sheet call on the hot path."""
        with mock.patch.object(hp, "expected_runs_today", return_value=1), \
             mock.patch.object(hp, "successful_runs_today") as counted:
            self.assertTrue(hp._phase_complete("daily_metrics"))
        counted.assert_not_called()


class PublishDoneHonoursIt(unittest.TestCase):
    """The wiring, end to end through publish_done."""

    def _publish(self, *, phase_done: bool):
        ws = mock.MagicMock()
        ws.find.return_value = None
        with mock.patch.object(hp, "_resolve_card", return_value="leaders-call"), \
             mock.patch.object(hp, "_ws", return_value=ws), \
             mock.patch.object(hp, "_find_open_row_for_card", return_value=None), \
             mock.patch.object(hp, "_phase_complete", return_value=phase_done), \
             mock.patch.object(hp, "_clear_failure") as cleared:
            hp.publish_done("leaders_call", "Leader's Call - Weekly Recognition",
                            status="success")
        return cleared

    def test_the_2pm_tab_fill_publishes_but_closes_nothing(self):
        self._publish(phase_done=False).assert_not_called()

    def test_the_730pm_deck_post_closes_it(self):
        self._publish(phase_done=True).assert_called_once()

    def test_an_explicit_clear_failure_false_still_wins(self):
        """A caller that KNOWS it delivered nothing (a dry run, a probe, a
        report's own phase 1) is believed without a Hub read."""
        ws = mock.MagicMock()
        ws.find.return_value = None
        with mock.patch.object(hp, "_resolve_card", return_value="leaders-call"), \
             mock.patch.object(hp, "_ws", return_value=ws), \
             mock.patch.object(hp, "_find_open_row_for_card", return_value=None), \
             mock.patch.object(hp, "_phase_complete") as gate, \
             mock.patch.object(hp, "_clear_failure") as cleared:
            hp.publish_done("leaders_call", "Leader's Call", status="success",
                            clear_failure=False)
        cleared.assert_not_called()
        gate.assert_not_called()


class LeadersCallSaysItItself(unittest.TestCase):
    """Belt and braces: the phase gate holds the line off the card, and the
    report's own phase-1 publishes declare it too — no Hub read needed, and the
    rule stays visible at the place the phase actually is."""

    def test_both_phase_one_publishes_pass_clear_failure_false(self):
        import re
        from pathlib import Path
        src = Path(__file__).resolve().parents[1] / "leaders_call" / "run.py"
        # The CALLS, not the word: the comments explaining the rule say it too.
        calls = re.findall(r"publish_done\((?:[^()]|\([^()]*\))*\)",
                           src.read_text(encoding="utf-8"))
        self.assertEqual(len(calls), 3, "2pm --no-pdf, 2pm PDF-DM, 7:30pm deck")
        held = [c for c in calls if "clear_failure=False" in c]
        self.assertEqual(len(held), 2,
                         "the 2pm --no-pdf publish and the 2pm PDF-DM publish "
                         "are both phase 1 and must not close the ticket; only "
                         "the --finalize deck post may")


class SlackDeliveredVerifier(unittest.TestCase):
    """Reads the channel the way a member does — the only claim that matters."""

    DAY = dt.date(2026, 9, 8)
    # `match` is the FILENAME stem, not the comment's prose. The deck's comment
    # says "Leader's Call" with an apostrophe and the file is
    # alphalete_leaders_call_<sunday>.pdf — matching the prose would have missed
    # every real deck ever posted, which is what this fixture is copied from.
    CFG = {"type": "slack_delivered", "channels": ["C1", "C2"],
           "match": "leaders_call", "files_only": True}

    def _client(self, per_channel):
        c = mock.MagicMock()

        def _hist(*, channel, oldest=None, limit=200, **_kw):
            got = per_channel.get(channel)
            if got is None:
                raise RuntimeError("not_in_channel")
            return {"messages": got}
        c.conversations_history.side_effect = _hist
        return c

    def _run(self, per_channel, cfg=None):
        with mock.patch("automations.shared.slack_metrics_post._client",
                        return_value=self._client(per_channel)):
            return reconcile.verify(
                type("R", (), {"verify": cfg or self.CFG})(), self.DAY,
                dry_run=False)

    def _deck(self):
        # Shaped like the real thing: Slack renders initial_comment as the
        # message text and hangs the upload off the same message.
        return [{"text": "🐺 Alphalete Leader's Call — Weekly Recognition",
                 "files": [{"name": "alphalete_leaders_call_2026-09-06.pdf"}]}]

    def test_the_deck_in_both_channels_is_delivered(self):
        r = self._run({"C1": self._deck(), "C2": self._deck()})
        self.assertTrue(r.ok)
        self.assertFalse(r.unknown)

    def test_a_channel_with_no_deck_is_not_delivered(self):
        """2026-09-08: chatter all day in both channels, no deck in either."""
        chatter = [{"text": "Todays Goals!! A&T - 6/30", "files": []}]
        r = self._run({"C1": self._deck(), "C2": chatter})
        self.assertFalse(r.ok)
        self.assertEqual(r.missing, ["C2"])

    def test_a_message_about_the_deck_is_not_the_deck(self):
        """files_only: somebody TALKING about the call is not the deck landing.
        The match would hit its text; the attachment is the claim."""
        r = self._run({"C1": self._deck(),
                       "C2": [{"text": "leaders_call deck coming shortly",
                               "files": []}]})
        self.assertFalse(r.ok)
        self.assertEqual(r.missing, ["C2"])

    def test_a_channel_we_cannot_read_is_unknown_never_missing(self):
        """Several of these channels are no-history-read for our token. "I am
        not allowed to look" must never be reported as "it wasn't sent"."""
        r = self._run({"C1": None, "C2": None})
        self.assertTrue(r.ok)
        self.assertTrue(r.unknown)

    def test_an_unreadable_channel_does_not_sink_a_confirmed_one(self):
        r = self._run({"C1": self._deck(), "C2": None})
        self.assertTrue(r.ok)
        self.assertFalse(r.unknown)

    def test_any_of_accepts_one_channel(self):
        cfg = dict(self.CFG, any_of=True)
        r = self._run({"C1": self._deck(), "C2": []}, cfg)
        self.assertTrue(r.ok)

    def test_leaders_call_is_actually_wired_to_it(self):
        """The verifier existing is not the fix; the report using it is."""
        import json
        from pathlib import Path
        cfg = json.loads(
            (Path(__file__).resolve().parent / "schedule_config.json")
            .read_text(encoding="utf-8"))
        v = cfg["reports"]["leaders_call"]["verify"]
        self.assertEqual(v["type"], "slack_delivered")
        self.assertEqual(sorted(v["channels"]), ["C067TTGFEFR", "C07J46MQNUX"])
        # …and pointed at the channels the deck actually goes to.
        from automations.leaders_call.run import FINAL_CHANNELS
        self.assertEqual(sorted(cid for _n, cid in FINAL_CHANNELS),
                         sorted(v["channels"]))
        # …with a needle that matches a real deck's filename.
        self.assertIn(v["match"],
                      "alphalete_leaders_call_2026-09-06.pdf".lower())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
