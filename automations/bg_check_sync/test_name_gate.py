"""The legal-name gate refuses to guess. These tests are mostly about that.

The one case it SHOULD act on is Eve's real example (checklist 'Nikki Coleman',
Sterling 'Coleman, Shomanique'); every other test here is a shape that looks
like it and must produce no question at all, because a wrong pairing staples a
background check to the wrong human.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.bg_check_sync import name_gate, parse
from automations.bg_check_sync.match import Person, _norm_key
from automations.bg_check_sync.parse import BGEvent

MONDAY = dt.date(2026, 8, 31)
WEEK = "8/31/2026"


def person(first, last, current="", locations=None, email=""):
    p = Person(first, last, _norm_key(first, last), current,
               list(locations or [("D2D OBCL", 12)]))
    p.email = email
    return p


def event(first, last, status=parse.PASSED, date="2026-08-27", subject=None):
    return BGEvent(last=last, first=first, status=status, date=date,
                   subject=subject or f"Background Check Complete - Score PASS")


def propose(roster, events, matched=None):
    matched = matched if matched is not None else {p.key: [] for p in roster}
    return name_gate.propose(roster, events, matched, MONDAY, WEEK)


class ProposeTests(unittest.TestCase):

    def test_nickname_pairs_on_surname(self):
        """The case this was built for."""
        out = propose([person("Nikki", "Coleman")], [event("Shomanique", "Coleman")])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].sheet_name, "Nikki Coleman")
        self.assertEqual(out[0].legal_name, "Shomanique Coleman")
        self.assertEqual(out[0].locations, [("D2D OBCL", 12)])

    def test_two_orphans_same_surname_asks_nothing(self):
        """Two Colemans on the roster: the result belongs to one of them and we
        cannot tell which."""
        out = propose([person("Nikki", "Coleman"), person("Dee", "Coleman")],
                      [event("Shomanique", "Coleman")])
        self.assertEqual(out, [])

    def test_several_emails_for_one_person_is_still_one_question(self):
        """Sterling sends the invite and then the score — one person, two
        emails. The most advanced one is what gets quoted."""
        out = propose([person("Nikki", "Valentine")],
                      [event("Shuminique", "Valentine", status=parse.TAKEN_PENDING,
                             date="2026-08-20",
                             subject="Background Check E-Invite for Valentine, "
                                     "Shuminique Desrell is Complete"),
                       event("Shuminique", "Valentine", status=parse.PASSED,
                             date="2026-08-20",
                             subject="Background Check Complete - Score PASS")])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].legal_name, "Shuminique Valentine")
        self.assertIn("Score PASS", out[0].evidence)

    def test_two_results_same_surname_asks_nothing(self):
        out = propose([person("Nikki", "Coleman")],
                      [event("Shomanique", "Coleman"),
                       event("Marcus", "Coleman", date="2026-08-25")])
        self.assertEqual(out, [])

    def test_person_already_matched_is_not_a_nickname(self):
        p = person("Nikki", "Coleman")
        out = propose([p], [event("Shomanique", "Coleman")],
                      matched={p.key: [event("Nikki", "Coleman")]})
        self.assertEqual(out, [])

    def test_claimed_event_is_not_offered_again(self):
        """An event another person already matched can't also be a nickname."""
        p = person("Nikki", "Coleman")
        other = person("Marcus", "Coleman")
        ev = event("Marcus", "Coleman")
        out = propose([p, other], [ev], matched={p.key: [], other.key: [ev]})
        self.assertEqual(out, [])

    def test_a_hand_typed_passed_still_gets_asked(self):
        """Row 175's shape: the status was typed in by hand under the nickname,
        which is exactly when the name needs fixing."""
        out = propose([person("Nikki", "Valentine", current=parse.PASSED)],
                      [event("Shuminique", "Valentine")])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].current, parse.PASSED)

    def test_result_from_a_different_cohort_is_ignored(self):
        """Far outside any hiring runway — somebody else's check entirely."""
        out = propose([person("Nikki", "Coleman")],
                      [event("Shomanique", "Coleman", date="2026-01-05")])
        self.assertEqual(out, [])

    def test_same_first_name_is_not_a_mismatch(self):
        out = propose([person("Nikki", "Coleman")], [event("Nikki", "Coleman")])
        self.assertEqual(out, [])

    def test_different_surname_is_never_paired(self):
        out = propose([person("Nikki", "Coleman")], [event("Shomanique", "Colvin")])
        self.assertEqual(out, [])

    def test_pid_is_stable_across_runs(self):
        a = propose([person("Nikki", "Coleman")], [event("Shomanique", "Coleman")])
        b = propose([person("Nikki", "Coleman")], [event("Shomanique", "Coleman")])
        self.assertEqual(a[0].pid, b[0].pid)

    def test_unanswered_skips_anything_already_asked(self):
        out = propose([person("Nikki", "Coleman")], [event("Shomanique", "Coleman")])
        state = {out[0].pid: {"status": "pending"}}
        self.assertEqual(name_gate.unanswered(out, state), [])


class EmailEvidenceTests(unittest.TestCase):
    """The four live 8/24 pairs plus the counter-example, as they really read."""

    def test_email_backs_the_legal_name(self):
        self.assertTrue(name_gate.backed_by_email(
            "Shuminiquevalentine@yahoo.com", "Shuminique"))

    def test_stem_is_enough_for_a_shortened_first_name(self):
        self.assertTrue(name_gate.backed_by_email(
            "Tavavasquez.81@gmail.com", "Tavaiesha"))

    def test_a_different_person_gets_no_backing(self):
        self.assertFalse(name_gate.backed_by_email("Angiep8k@gmail.com", "Gabriel"))
        self.assertFalse(name_gate.backed_by_email("jmgarcia.mini@gmail.com", "Robert"))
        self.assertFalse(name_gate.backed_by_email(
            "jesuseduardo.gmartinez@gmail.com", "Berenice"))

    def test_no_backing_still_gets_asked(self):
        """Advisory, not a filter — Lanequa Simpson really does use
        nikki.creative@zohomail.com."""
        out = propose([person("Nikki", "Simpson", email="nikki.creative@zohomail.com")],
                      [event("Lanequa", "Simpson")])
        self.assertEqual(len(out), 1)
        self.assertFalse(out[0].corroborated)
        line = name_gate.render_line(out[0])
        self.assertIn("nikki.creative@zohomail.com", line)
        self.assertNotIn("matches the Sterling name", line)

    def test_corroborated_questions_come_first(self):
        out = propose(
            [person("Juan", "Garcia", email="jmgarcia.mini@gmail.com"),
             person("Nikki", "Valentine", email="Shuminiquevalentine@yahoo.com")],
            [event("Robert", "Garcia"), event("Shuminique", "Valentine")])
        self.assertEqual([p.sheet_name for p in out],
                         ["Nikki Valentine", "Juan Garcia"])

    def test_shouted_sterling_name_is_title_cased(self):
        out = propose([person("Tava", "Vasquez")],
                      [event("TAVAIESHA", "VASQUEZ")])
        self.assertEqual(out[0].legal_name, "Tavaiesha Vasquez")


class TimingTests(unittest.TestCase):
    """The second opinion: does WHEN they took it fit WHEN they start?"""

    def test_taken_date_is_the_first_email_not_the_score(self):
        group = [event("Shuminique", "Valentine", status=parse.PASSED,
                       date="2026-08-22T18:14:01+00:00"),
                 event("Shuminique", "Valentine", status=parse.TAKEN_PENDING,
                       date="2026-08-20T18:10:11+00:00")]
        self.assertEqual(name_gate.taken_date(group), dt.date(2026, 8, 20))

    def test_a_check_taken_days_before_the_start_week_fits(self):
        out = propose([person("Nikki", "Valentine")],
                      [event("Shuminique", "Valentine", date="2026-08-27")])
        self.assertTrue(out[0].fresh)
        self.assertEqual(out[0].days_before_start, 4)
        self.assertIn("took the check Aug 27", name_gate.render_line(out[0]))

    def test_a_month_out_hire_is_normal_not_stale(self):
        """The link goes out at hire, and a start can be a month or more away."""
        out = propose([person("Nikki", "Valentine")],
                      [event("Shuminique", "Valentine", date="2026-07-24")])
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].fresh)
        self.assertEqual(out[0].days_before_start, 38)
        self.assertNotIn("worth a look", name_gate.render_line(out[0]))

    def test_a_check_older_than_the_hiring_runway_is_called_out(self):
        out = propose([person("Juan", "Garcia")],
                      [event("Robert", "Garcia", date="2026-05-05")])
        self.assertEqual(len(out), 1)
        self.assertFalse(out[0].fresh)
        self.assertIn("worth a look", name_gate.render_line(out[0]))

    def test_a_check_taken_just_after_they_started_is_normal(self):
        """A link that went out late — ordinary, not suspicious."""
        out = propose([person("Nikki", "Valentine")],
                      [event("Shuminique", "Valentine", date="2026-09-05")])
        self.assertTrue(out[0].fresh)
        self.assertNotIn("worth a look", name_gate.render_line(out[0]))

    def test_a_result_landing_after_they_start_is_kept_and_dated(self):
        """Sterling takes as long as it takes — taken before the start week,
        passed three weeks into the job."""
        out = propose([person("Nikki", "Valentine")],
                      [event("Shuminique", "Valentine",
                             status=parse.TAKEN_PENDING, date="2026-08-27"),
                       event("Shuminique", "Valentine",
                             status=parse.PASSED, date="2026-09-21")])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].taken_on, "2026-08-27")
        self.assertEqual(out[0].result_on, "2026-09-21")
        self.assertIn("took the check Aug 27", name_gate.render_line(out[0]))

    def test_a_check_taken_months_after_they_started_is_called_out(self):
        out = propose([person("Nikki", "Valentine")],
                      [event("Shuminique", "Valentine", date="2026-10-20")])
        self.assertEqual(len(out), 1)
        self.assertFalse(out[0].fresh)
        self.assertIn("worth a look", name_gate.render_line(out[0]))

    def test_both_signals_outrank_one(self):
        """Two agreeing checks sort above one, and one above none."""
        both = propose([person("Nikki", "Valentine",
                               email="Shuminiquevalentine@yahoo.com")],
                       [event("Shuminique", "Valentine", date="2026-08-27")])[0]
        timing_only = propose([person("Juan", "Garcia",
                                      email="jmgarcia.mini@gmail.com")],
                              [event("Robert", "Garcia", date="2026-08-27")])[0]
        neither = propose([person("Jesus", "Martinez",
                                  email="jesuseduardo.gmartinez@gmail.com")],
                          [event("Berenice", "Monzon Martinez", date="2026-05-05")])[0]
        self.assertEqual([both.signals, timing_only.signals, neither.signals], [2, 1, 0])


class AskPlacementTests(unittest.TestCase):
    """The questions go inside that week's BG status thread."""

    def _proposal(self):
        return propose([person("Nikki", "Valentine")],
                       [event("Shuminique", "Valentine")])[0]

    def test_it_finds_the_weeks_existing_thread(self):
        from automations.bg_check_sync import slack_post
        chan = slack_post.CHANNEL_IDS[0]
        orig = slack_post._load_state
        slack_post._load_state = lambda: {
            WEEK: {"channels": {chan: {"parent_ts": "111.222", "reply_ts": "1.2"}}}}
        try:
            self.assertEqual(name_gate.week_thread(WEEK, chan), "111.222")
        finally:
            slack_post._load_state = orig

    def test_no_thread_yet_is_not_an_error(self):
        from automations.bg_check_sync import slack_post
        orig = slack_post._load_state
        slack_post._load_state = lambda: {}
        try:
            self.assertIsNone(name_gate.week_thread(WEEK, slack_post.CHANNEL_IDS[0]))
        finally:
            slack_post._load_state = orig

    def test_a_far_future_week_rides_the_latest_thread(self):
        """A month-out hire has no thread yet — the question still goes up now,
        labelled with the week they actually start."""
        from automations.bg_check_sync import slack_post
        chan = slack_post.CHANNEL_IDS[0]
        orig = slack_post._load_state
        slack_post._load_state = lambda: {
            "8/24/2026": {"channels": {chan: {"parent_ts": "111.0"}}},
            "8/31/2026": {"channels": {chan: {"parent_ts": "222.0"}}}}
        try:
            self.assertEqual(name_gate.latest_thread(chan), ("8/31/2026", "222.0"))
            self.assertIsNone(name_gate.week_thread("9/28/2026", chan))
        finally:
            slack_post._load_state = orig

    def test_the_intro_names_the_start_week_when_it_rides_elsewhere(self):
        self.assertIn("starting 9/28/2026",
                      name_gate.render_parent(1, start_week="9/28/2026"))
        self.assertNotIn("starting", name_gate.render_parent(1))

    def test_a_question_reads_as_two_lines(self):
        """Megan on the first version: "wayyyy too much wording." The ✅/❌
        meanings belong in the parent, said once."""
        out = propose([person("Adriana", "Ruiz", email="adrianaruiz@icloud.com")],
                      [event("Jordan", "Ruiz", date="2026-08-27")])
        line = name_gate.render_line(out[0])
        self.assertLessEqual(len(line.splitlines()), 2)
        self.assertIn("*Adriana Ruiz* → *Jordan Ruiz*?", line)
        self.assertNotIn("✅", line)
        self.assertNotIn("❌", line)

    def test_the_parent_carries_the_meanings_and_the_tags(self):
        parent = name_gate.render_parent(2)
        self.assertIn("✅ = same person", parent)
        self.assertIn("❌ = different person", parent)
        for _name, uid in name_gate.DECIDERS:
            self.assertIn(uid, parent)

    def test_dry_run_posts_nothing_and_records_nothing(self):
        state = {}
        self.assertEqual(
            name_gate.post_proposals([self._proposal()], state, dry_run=True), 0)
        self.assertEqual(state, {})


class VoteTests(unittest.TestCase):

    def test_only_deciders_count(self):
        rx = [{"name": "white_check_mark", "users": ["U0STRANGER"]}]
        self.assertIsNone(name_gate._voted(rx, name_gate.APPROVE_EMOJI))

    def test_decider_approval_is_read(self):
        rx = [{"name": "white_check_mark", "users": ["U0B9924FHCL"]}]
        self.assertEqual(name_gate._voted(rx, name_gate.APPROVE_EMOJI), "U0B9924FHCL")

    def test_rejection_wins_over_approval(self):
        entry = {"status": "pending", "channel": "C1", "parent_ts": "1.0",
                 "reply_ts": "2.0", "sheet_first": "Nikki", "sheet_last": "Coleman",
                 "legal_first": "Shomanique", "legal_last": "Coleman",
                 "key": "coleman|nikki", "locations": [["D2D OBCL", 12]]}
        state = {"pid1": entry}
        rx = [{"name": "white_check_mark", "users": ["U0B9924FHCL"]},
              {"name": "x", "users": ["U0APVP29QSD"]}]
        orig = name_gate._client
        name_gate._client = lambda: None
        thread = name_gate._thread_reactions
        name_gate._thread_reactions = lambda cli, ch, ts: {"2.0": rx}
        try:
            approved, rejected = name_gate.collect_decisions(state)
        finally:
            name_gate._client = orig
            name_gate._thread_reactions = thread
        self.assertEqual(approved, [])
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["decided_by"], "U0APVP29QSD")


class SpellingFixTests(unittest.TestCase):
    """Already matched = identity known = no question, just make it Sterling's."""

    def test_a_dropped_second_surname_is_corrected(self):
        p = person("Erica", "Glenn")
        fixes = name_gate.spelling_fixes([p], {p.key: [event("Erica", "Glenn Jackson")]},
                                         WEEK)
        self.assertEqual(len(fixes), 1)
        self.assertEqual((fixes[0]["legal_first"], fixes[0]["legal_last"]),
                         ("Erica", "Glenn Jackson"))
        self.assertEqual(fixes[0]["decided_by"], "sterling")

    def test_an_exact_match_is_left_alone(self):
        p = person("Bianca", "Mendez")
        self.assertEqual(
            name_gate.spelling_fixes([p], {p.key: [event("Bianca", "Mendez")]}, WEEK),
            [])

    def test_nobody_with_a_result_is_left_unspelled(self):
        p = person("Carlos", "Rivera")
        fixes = name_gate.spelling_fixes([p], {p.key: [event("Carlos", "Rios Rivera")]},
                                         WEEK)
        self.assertEqual(fixes[0]["legal_last"], "Rios Rivera")

    def test_no_result_means_no_opinion(self):
        p = person("Nikki", "Valentine")
        self.assertEqual(name_gate.spelling_fixes([p], {p.key: []}, WEEK), [])

    def test_sterling_shouting_is_title_cased_before_writing(self):
        p = person("Tava", "Vasquez")
        fixes = name_gate.spelling_fixes([p], {p.key: [event("TAVAIESHA", "VASQUEZ")]},
                                         WEEK)
        self.assertEqual(fixes[0]["legal_first"], "Tavaiesha")

    def test_the_fix_writes_through_apply_renames(self):
        p = person("Erica", "Glenn")
        fixes = name_gate.spelling_fixes([p], {p.key: [event("Erica", "Glenn Jackson")]},
                                         WEEK)
        ws = _FakeWS(["Erica", "Glenn"])
        name_gate.apply_renames(_FakeSheet(ws), fixes, {}, dry_run=False)
        self.assertEqual(ws.written[0]["values"], [["Erica", "Glenn Jackson"]])


class TintTests(unittest.TestCase):
    """Green = a real Sterling check ran under this exact spelling."""

    def test_exact_match_on_both_tabs_tints_both(self):
        p = person("Bianca", "Mendez",
                   locations=[("D2D OBCL", 5), ("D2D OBCL 8.24", 12)])
        by_tab = name_gate.confirmed_locations([p], {p.key: [event("Bianca", "Mendez")]})
        self.assertEqual(by_tab, {"D2D OBCL": [(5, p.key)],
                                  "D2D OBCL 8.24": [(12, p.key)]})

    def test_case_and_spacing_are_not_a_mismatch(self):
        p = person("Bianca", "Mendez")
        by_tab = name_gate.confirmed_locations([p], {p.key: [event("BIANCA", " Mendez ")]})
        self.assertEqual(len(by_tab), 1)

    def test_a_nickname_row_is_not_confirmed(self):
        p = person("Nikki", "Valentine")
        self.assertEqual(
            name_gate.confirmed_locations([p], {p.key: [event("Shuminique", "Valentine")]}),
            {})

    def test_no_result_yet_means_no_tint(self):
        p = person("Bianca", "Mendez")
        self.assertEqual(name_gate.confirmed_locations([p], {p.key: []}), {})

    def test_a_row_is_only_painted_once(self):
        p = person("Bianca", "Mendez")
        by_tab = name_gate.confirmed_locations([p], {p.key: [event("Bianca", "Mendez")]})
        ws = _FakeWS(["Bianca", "Mendez"])
        state = {}
        first = name_gate.tint_confirmed(_FakeSheet(ws), by_tab, state, dry_run=False)
        second = name_gate.tint_confirmed(_FakeSheet(ws), by_tab, state, dry_run=False)
        self.assertEqual((first, second), (1, 0))
        self.assertEqual(len(ws.formatted), 1)

    def test_dry_run_paints_nothing_and_remembers_nothing(self):
        p = person("Bianca", "Mendez")
        by_tab = name_gate.confirmed_locations([p], {p.key: [event("Bianca", "Mendez")]})
        ws = _FakeWS(["Bianca", "Mendez"])
        state = {}
        name_gate.tint_confirmed(_FakeSheet(ws), by_tab, state, dry_run=True)
        self.assertEqual(ws.formatted, [])
        self.assertEqual(state.get(name_gate.TINTED_KEY, {}), {})


class _FakeWS:
    def __init__(self, row_vals):
        self.row_vals = row_vals
        self.written = []
        self.formatted = []

    def get(self, rng):
        return [self.row_vals]

    def batch_update(self, data, value_input_option=None):
        self.written.extend(data)

    def batch_format(self, ranges):
        self.formatted.extend(ranges)


class _FakeSheet:
    def __init__(self, ws):
        self._ws = ws

    def worksheet(self, name):
        return self._ws


class ApplyTests(unittest.TestCase):

    ENTRY = {"pid": "p1", "sheet_first": "Nikki", "sheet_last": "Coleman",
             "legal_first": "Shomanique", "legal_last": "Coleman",
             "locations": [("D2D OBCL", 12)], "decided_by": "U0B9924FHCL"}

    def test_writes_both_name_cells(self):
        ws = _FakeWS(["Nikki", "Coleman"])
        out = name_gate.apply_renames(_FakeSheet(ws), [dict(self.ENTRY)], {},
                                      dry_run=False)
        self.assertEqual(len(ws.written), 1)
        self.assertEqual(ws.written[0]["values"], [["Shomanique", "Coleman"]])
        self.assertEqual(out[0]["rows_written"], 1)

    def test_dry_run_writes_nothing(self):
        ws = _FakeWS(["Nikki", "Coleman"])
        name_gate.apply_renames(_FakeSheet(ws), [dict(self.ENTRY)], {}, dry_run=True)
        self.assertEqual(ws.written, [])

    def test_row_that_moved_is_skipped_not_overwritten(self):
        """The whole point of the read-before-write: row 12 is somebody else now."""
        ws = _FakeWS(["Jeremy", "Finley"])
        out = name_gate.apply_renames(_FakeSheet(ws), [dict(self.ENTRY)], {},
                                      dry_run=False)
        self.assertEqual(ws.written, [])
        self.assertEqual(out[0]["rows_written"], 0)
        self.assertIn("Jeremy Finley", out[0]["skipped"][0])

    def test_already_renamed_by_hand_is_skipped(self):
        ws = _FakeWS(["Shomanique", "Coleman"])
        name_gate.apply_renames(_FakeSheet(ws), [dict(self.ENTRY)], {}, dry_run=False)
        self.assertEqual(ws.written, [])


class ClaimedAnywhereTests(unittest.TestCase):
    """The 8/24 dry run's near-miss: a result whose owner starts a later week."""

    ROLLING = [
        ["8/24/2026", "", "", "", ""],
        ["#", "2ND Round Interviewer", "Start Time", "Name", "Last Name"],
        ["1", "Zoria", "12:00", "Alex", "Rivera"],
        ["9/7/2026", "", "", "", ""],
        ["#", "2ND Round Interviewer", "Start Time", "Name", "Last Name"],
        ["1", "Zoria", "12:00", "Carlos", "Rivera"],
    ]

    def test_result_owned_by_a_later_week_is_claimed(self):
        ev = event("Carlos", "Rios Rivera")
        self.assertIn(id(ev), name_gate.claimed_anywhere(self.ROLLING, [ev]))

    def test_claimed_result_is_never_proposed(self):
        ev = event("Carlos", "Rios Rivera")
        claimed = name_gate.claimed_anywhere(self.ROLLING, [ev])
        out = name_gate.propose([person("Alex", "Rivera")], [ev],
                                {_norm_key("Alex", "Rivera"): []}, MONDAY, WEEK,
                                claimed_ids=claimed)
        self.assertEqual(out, [])

    def test_a_genuine_orphan_still_gets_through(self):
        ev = event("Shomanique", "Coleman")
        claimed = name_gate.claimed_anywhere(self.ROLLING, [ev])
        out = name_gate.propose([person("Nikki", "Coleman")], [ev],
                                {_norm_key("Nikki", "Coleman"): []}, MONDAY, WEEK,
                                claimed_ids=claimed)
        self.assertEqual(len(out), 1)


if __name__ == "__main__":
    unittest.main()
