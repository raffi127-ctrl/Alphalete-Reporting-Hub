"""Telling a drug screen from a background check when the email does not say.

Raf, Loom ba6bf293febd4e4baf4dbb01c9912ecc (2026-11-25, 1:36): "that's the
only email we get when I do their back or their drug tests, so it doesn't
actually say drug tests on it."

The danger is one-directional and that shapes every test here: writing a drug
result into the BG Status column is a compliance answer taken off the wrong
evidence, while holding a real background-check result is a row that stops
moving and gets named in Slack. So where there is doubt, hold.
"""
from __future__ import annotations

import datetime as dt
import json
import unittest

from automations.bg_check_sync import which_order as W
from automations.bg_check_sync.parse import BGEvent, TAKEN_PENDING


def _ev(first, last, date="2026-11-20"):
    return BGEvent(last=last, first=first, status=TAKEN_PENDING, date=date,
                   subject="E-Invite for %s %s is Complete" % (first, last))


def _row(action, people, at="2026-11-10 09:00:00", result=""):
    return {"Action": action, "Requested At": at, "Result": result,
            "Details": json.dumps({"people": [
                {"first_name": f, "last_name": l} for f, l in people]})}


class AnOfficeThatSendsNoDrugTestsIsUnaffected(unittest.TestCase):
    """The property that lets this ship: attribution keys off the DRUG invite,
    so nothing changes for anybody who has never sent one."""

    def test_no_invites_at_all_means_every_result_is_a_background_check(self):
        self.assertEqual(W.attribute(_ev("Ada", "Fournier"), []), W.BGC)

    def test_a_background_invite_alone_is_a_background_check(self):
        inv = W.invites_from_requests([_row("send_bgc", [("Ada", "Fournier")])])
        self.assertEqual(W.attribute(_ev("Ada", "Fournier"), inv), W.BGC)

    def test_somebody_elses_drug_invite_does_not_touch_this_person(self):
        inv = W.invites_from_requests([_row("send_drug", [("Kip", "Wilson")])])
        self.assertEqual(W.attribute(_ev("Ada", "Fournier"), inv), W.BGC)


class ADrugInviteChangesTheAnswer(unittest.TestCase):

    def test_a_drug_invite_alone_makes_it_a_drug_result(self):
        inv = W.invites_from_requests([_row("send_drug", [("Kip", "Wilson")])])
        self.assertEqual(W.attribute(_ev("Kip", "Wilson"), inv), W.DRUG)

    def test_both_sent_is_held_never_guessed(self):
        """THE BUG THIS EXISTS FOR. Before today this email was written into
        the BG Status column with no doubt expressed at all."""
        inv = W.invites_from_requests([
            _row("send_bgc", [("Kip", "Wilson")], at="2026-11-01 09:00:00"),
            _row("send_drug", [("Kip", "Wilson")], at="2026-11-18 09:00:00")])
        self.assertEqual(W.attribute(_ev("Kip", "Wilson"), inv), W.UNKNOWN)

    def test_a_drug_invite_placed_after_the_email_cannot_explain_it(self):
        """An order placed on the 25th did not produce an email on the 20th."""
        inv = W.invites_from_requests(
            [_row("send_drug", [("Kip", "Wilson")], at="2026-11-25 09:00:00")])
        self.assertEqual(W.attribute(_ev("Kip", "Wilson", "2026-11-20"), inv),
                         W.BGC)

    def test_an_undateable_email_with_a_drug_invite_is_not_assumed_innocent(self):
        """Treating it as "before the drug invite" is the assumption that
        files a drug screen as a background check."""
        inv = W.invites_from_requests([
            _row("send_bgc", [("Kip", "Wilson")]),
            _row("send_drug", [("Kip", "Wilson")])])
        self.assertEqual(W.attribute(_ev("Kip", "Wilson", "not a date"), inv),
                         W.UNKNOWN)

    def test_names_are_matched_tolerantly(self):
        """Same folding the rest of the module uses -- accents and case must
        not make a drug invite invisible."""
        inv = W.invites_from_requests([_row("send_drug", [("Anh", "Durañona")])])
        self.assertEqual(W.attribute(_ev("anh", "Duranona"), inv), W.DRUG)


class ADryRunOrderedNothing(unittest.TestCase):
    """drug_mode ships "dry" everywhere. A dry send fills the form and stops
    before Send Invites, so no email can ever come back from it."""

    def test_a_dry_drug_send_is_not_an_invite(self):
        inv = W.invites_from_requests([
            _row("send_drug", [("Kip", "Wilson")],
                 result=json.dumps({"status": "dry_run",
                                    "would_send": ["Kip Wilson"]}))])
        self.assertEqual(inv, [])
        self.assertEqual(W.attribute(_ev("Kip", "Wilson"), inv), W.BGC)

    def test_a_failed_send_still_counts_as_an_invite(self):
        """judge_job's own words for an unanswered send: "UNCONFIRMED ...
        check Sterling before pressing Send again". It may well have gone."""
        inv = W.invites_from_requests([
            _row("send_drug", [("Kip", "Wilson")],
                 result=json.dumps({"status": "error", "error": "lost track"}))])
        self.assertEqual(len(inv), 1)
        self.assertEqual(W.attribute(_ev("Kip", "Wilson"), inv), W.DRUG)

    def test_a_dry_BACKGROUND_send_is_not_an_invite_either(self):
        """Symmetry matters: a dry BGC send next to a real drug send leaves
        only the drug one, so the answer is DRUG and not "both"."""
        inv = W.invites_from_requests([
            _row("send_bgc", [("Kip", "Wilson")],
                 result=json.dumps({"status": "dry_run"})),
            _row("send_drug", [("Kip", "Wilson")])])
        self.assertEqual(W.attribute(_ev("Kip", "Wilson"), inv), W.DRUG)


class RowsThatCannotBeRead(unittest.TestCase):

    def test_unreadable_details_are_skipped_not_guessed(self):
        bad = {"Action": "send_drug", "Requested At": "2026-11-10 09:00:00",
               "Details": "{not json", "Result": ""}
        self.assertEqual(W.invites_from_requests([bad]), [])

    def test_a_row_with_no_date_is_skipped(self):
        row = _row("send_drug", [("Kip", "Wilson")], at="")
        self.assertEqual(W.invites_from_requests([row]), [])

    def test_other_actions_are_ignored(self):
        self.assertEqual(
            W.invites_from_requests([_row("apex_send", [("Kip", "Wilson")])]), [])


class SplittingTheStream(unittest.TestCase):

    def setUp(self):
        self.inv = W.invites_from_requests([
            _row("send_bgc", [("Ada", "Fournier")]),
            _row("send_drug", [("Kip", "Wilson")]),
            _row("send_bgc", [("Mia", "Reyes")], at="2026-11-01 09:00:00"),
            _row("send_drug", [("Mia", "Reyes")], at="2026-11-18 09:00:00")])
        self.events = [_ev("Ada", "Fournier"), _ev("Kip", "Wilson"),
                       _ev("Mia", "Reyes")]

    def test_only_the_background_check_reaches_the_sheet(self):
        keep, held = W.split(self.events, self.inv)
        self.assertEqual([(e.first, e.last) for e in keep], [("Ada", "Fournier")])
        self.assertEqual(len(held), 2)

    def test_the_held_list_says_which_kind_of_doubt(self):
        """"this is their drug test" needs nothing doing; "we can't tell"
        is a result sitting unapplied. One message for both hides the
        second inside the first."""
        _, held = W.split(self.events, self.inv)
        said = dict(W.held_names(held, self.inv))
        self.assertIn("drug test, not their background check", said["Kip Wilson"])
        self.assertIn("can't tell", said["Mia Reyes"])

    def test_nothing_held_when_nobody_has_a_drug_invite(self):
        inv = W.invites_from_requests([_row("send_bgc", [("Ada", "Fournier")])])
        keep, held = W.split(self.events, inv)
        self.assertEqual(len(keep), 3)
        self.assertEqual(held, [])


class ItReachesTheThread(unittest.TestCase):
    """Holding an event means match.decide sees no email for that person, and
    a non-terminal row with no email produces NO flag -- so without this the
    row would just stop moving and nothing would say why."""

    def test_render_names_them(self):
        from automations.bg_check_sync import slack_post
        body = slack_post.render(
            "11/23/2026", [("Mia Reyes", "Sent")], [], "Nov 25, 9:00 AM",
            unsure=[("Mia Reyes", "a result came back and we can't tell "
                                  "whether it's the background check or the "
                                  "drug test — both were sent")])
        self.assertIn("background check or the drug test", body)
        self.assertIn("Mia Reyes", body)

    def test_render_is_unchanged_when_there_is_nothing_to_say(self):
        from automations.bg_check_sync import slack_post
        plain = slack_post.render("11/23/2026", [("Ada Fournier", "Passed")],
                                  [], "Nov 25, 9:00 AM")
        with_empty = slack_post.render("11/23/2026", [("Ada Fournier", "Passed")],
                                       [], "Nov 25, 9:00 AM", unsure=[])
        self.assertEqual(plain, with_empty)
        self.assertNotIn("drug test", plain)


if __name__ == "__main__":
    unittest.main()
