"""When this email goes out, and what day it tells people to turn up on.

HISTORY, because it explains the shape. This was one 8am Monday BCC to the
whole week's cohort, and the body said "orientation today". Megan moved it to
two days before each person's own start (2026-11-18), which made that sentence
false -- so the lead was built and held behind a copy guard for one session.
She then changed the words ("do 1 to change the day to be correct for when
they actually start"), and the send became one BCC per start date so each
group can be told its own day.

What these pin:
  * the copy carries a day placeholder and the build REFUSES without a day;
  * the day reads correctly from two days out, the day before, and the day;
  * one group per start date, and nobody in two groups;
  * the re-send guard is per PERSON, because a per-day guard would silently
    drop the second group due on one morning.

    python -m unittest automations.slack_skool_email.test_send_timing
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.slack_skool_email import config, message, run

MON = dt.date(2026, 11, 23)


class _P:
    """Just enough of a blueink_docs.roster.NewStart for the grouping."""

    def __init__(self, name, email, chart_date, eligible=True):
        self.name = name
        self.email = email
        self.chart_date = chart_date
        self._ok = eligible
        self.skip_reason = "" if eligible else "not starting"

    @property
    def eligible(self):
        return self._ok


def _code_only(src: str) -> str:
    """`src` with comments and string literals removed.

    A source-reading test that greps the raw text matches the prose explaining
    why something is NOT done, which is the opposite of what it meant to
    assert.
    """
    import io
    import tokenize
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    except (tokenize.TokenError, IndentationError):
        # An indented method body is not a whole module; fall back to a
        # line-wise strip rather than giving up on the assertion.
        return "\n".join(l.split("#")[0] for l in src.splitlines())
    return " ".join(out)


class TheCopyCarriesTheDay(unittest.TestCase):
    def test_the_placeholder_is_in_the_body(self):
        self.assertIn(config.WHEN_TOKEN, config.BODY)

    def test_the_body_no_longer_says_today(self):
        # The sentence that made an early send a lie.
        self.assertNotIn("orientation today", config.BODY.lower())

    def test_the_lead_is_on(self):
        self.assertEqual(config.SEND_LEAD_DAYS, 2)

    def test_nothing_blocks_the_early_send_now(self):
        self.assertEqual(config.early_send_blocked_by_copy(), "")

    def test_putting_today_back_in_the_copy_blocks_it_again(self):
        real = config.BODY
        try:
            config.BODY = "We're excited to have you at orientation today."
            why = config.early_send_blocked_by_copy(2)
            self.assertIn("orientation today", why)
        finally:
            config.BODY = real

    def test_dropping_the_placeholder_blocks_it_too(self):
        # Somebody rewording the sentence and losing {when} would otherwise
        # mail people two days early with no day in it at all.
        real = config.BODY
        try:
            config.BODY = "We're excited to have you at orientation."
            why = config.early_send_blocked_by_copy(2)
            self.assertIn(config.WHEN_TOKEN, why)
        finally:
            config.BODY = real


class HowTheDayReads(unittest.TestCase):
    def test_two_days_out_names_the_weekday_and_the_date(self):
        self.assertEqual(config.when_phrase(MON, dt.date(2026, 11, 21)),
                         "on Monday, November 23")

    def test_the_day_before_says_tomorrow(self):
        self.assertEqual(config.when_phrase(MON, dt.date(2026, 11, 22)),
                         "tomorrow")

    def test_the_day_itself_says_today(self):
        self.assertEqual(config.when_phrase(MON, MON), "today")

    def test_no_leading_zero_on_the_date(self):
        # %-d is not portable (macOS AND Windows), so this is done by hand.
        got = config.when_phrase(dt.date(2026, 12, 7), dt.date(2026, 12, 5))
        self.assertIn("December 7", got)
        self.assertNotIn("December 07", got)

    def test_an_unknown_date_still_reads_as_a_sentence(self):
        self.assertEqual(config.when_phrase(None), "on your first day")

    def test_a_datetime_is_narrowed_not_crashed_on(self):
        self.assertEqual(
            config.when_phrase(dt.datetime(2026, 11, 23), dt.date(2026, 11, 21)),
            "on Monday, November 23")


class TheBuildRefusesWithoutADay(unittest.TestCase):
    LINKS = {"slack_link": "https://slack.example", "skool_link": "https://skool.example"}

    def test_the_day_reaches_the_plain_text_part(self):
        got = message.render_text(when="on Monday, November 23", **self.LINKS)
        self.assertIn("orientation on Monday, November 23", got)

    def test_the_day_reaches_the_html_part_too(self):
        # The classic HTML-email bug is one part updated and the other stale.
        got = message.render_html(when="on Monday, November 23", **self.LINKS)
        self.assertIn("orientation on Monday, November 23", got)

    def test_no_day_is_a_refusal_not_a_blank(self):
        with self.assertRaises(message.CopyError):
            message.render_text(**self.LINKS)
        with self.assertRaises(message.CopyError):
            message.build(["a@x.com"], **self.LINKS)

    def test_a_built_message_carries_the_day_in_both_parts(self):
        msg = message.build(["a@x.com"], when="tomorrow", **self.LINKS)
        bodies = [p.get_content() for p in msg.walk()
                  if p.get_content_maintype() == "text"]
        self.assertEqual(len(bodies), 2)
        for b in bodies:
            self.assertIn("orientation tomorrow", b)


class OneGroupPerStartDate(unittest.TestCase):
    def test_two_start_dates_are_two_groups(self):
        people = [_P("Mon One", "mon@x.com", MON),
                  _P("Mon Two", "mon2@x.com", MON),
                  _P("Wed One", "wed@x.com", dt.date(2026, 11, 25))]
        got = run._groups(people, today=dt.date(2026, 11, 23))
        self.assertEqual([d for d, _a in got],
                         [MON, dt.date(2026, 11, 25)])
        self.assertEqual(got[0][1], ["mon@x.com", "mon2@x.com"])

    def test_groups_come_back_earliest_first(self):
        people = [_P("Late", "l@x.com", dt.date(2026, 11, 25)),
                  _P("Early", "e@x.com", MON)]
        got = run._groups(people, today=dt.date(2026, 11, 23))
        self.assertEqual([d for d, _a in got], [MON, dt.date(2026, 11, 25)])

    def test_nobody_due_later_is_included(self):
        people = [_P("Next Week", "n@x.com", dt.date(2026, 12, 7))]
        self.assertEqual(run._groups(people, today=MON), [])

    def test_a_late_bob_starting_tomorrow_is_due_now(self):
        # Their floor fell yesterday, so they go on this run rather than never.
        people = [_P("Late BOB", "lb@x.com", dt.date(2026, 11, 19))]
        got = run._groups(people, today=dt.date(2026, 11, 18))
        self.assertEqual(len(got), 1)

    def test_a_late_bob_and_the_main_cohort_are_separate_groups(self):
        # The case that broke the old per-day guard: two groups, one morning.
        people = [_P("Tomorrow", "t@x.com", dt.date(2026, 11, 22)),
                  _P("Monday", "m@x.com", MON)]
        got = run._groups(people, today=dt.date(2026, 11, 21))
        self.assertEqual(len(got), 2)

    def test_an_ineligible_person_is_not_grouped(self):
        people = [_P("Quit", "q@x.com", MON, eligible=False)]
        self.assertEqual(run._groups(people, today=MON), [])

    def test_the_same_address_twice_is_one_recipient(self):
        # Someone on both of Monday's charts must not get two copies.
        people = [_P("Dup A", "d@x.com", MON), _P("Dup B", "D@X.com", MON)]
        got = run._groups(people, today=MON)
        self.assertEqual(got[0][1], ["d@x.com"])

    def test_nobody_appears_in_two_groups(self):
        people = [_P("A", "a@x.com", MON),
                  _P("B", "b@x.com", dt.date(2026, 11, 25))]
        got = run._groups(people, today=dt.date(2026, 11, 25))
        allseen = [a for _d, g in got for a in g]
        self.assertEqual(len(allseen), len(set(allseen)))


class AnUndatedChartGetsNoEmail(unittest.TestCase):
    def test_it_is_left_out_of_every_group(self):
        people = [_P("No Date", "nd@x.com", None)]
        self.assertEqual(run._groups(people, today=MON), [])

    def test_and_it_is_reported_rather_than_silently_dropped(self):
        people = [_P("No Date", "nd@x.com", None)]
        self.assertEqual([p.name for p in run._undated(people)], ["No Date"])

    def test_not_yet_is_reported_apart_from_undated(self):
        people = [_P("Later", "l@x.com", dt.date(2026, 12, 7)),
                  _P("No Date", "nd@x.com", None)]
        self.assertEqual([p.name for p in run._not_yet(people, today=MON)],
                         ["Later"])
        self.assertEqual([p.name for p in run._undated(people)], ["No Date"])


class TheWeekGate(unittest.TestCase):
    def test_todays_tab_is_fine(self):
        self.assertIsNone(run._wrong_week("D2D OBCL 11.23", today=MON))

    def test_next_weeks_tab_is_allowed_within_the_lead(self):
        # On the 21st the people who are due sit on the 11.23 tab; one-tab
        # "must be dated today" could not see them.
        self.assertIsNone(run._wrong_week("D2D OBCL 11.23",
                                          today=dt.date(2026, 11, 21)))

    def test_a_tab_further_out_than_the_lead_is_still_refused(self):
        self.assertTrue(run._wrong_week("D2D OBCL 11.23",
                                        today=dt.date(2026, 11, 20)))

    def test_last_weeks_tab_is_still_refused(self):
        # The fault this gate exists for: mailing people who started a week
        # ago. The lead must never open it backwards.
        why = run._wrong_week("D2D OBCL 11.16", today=MON)
        self.assertTrue(why)
        self.assertIn("hasn't been built yet", why)

    def test_an_unreadable_tab_name_is_refused(self):
        self.assertIn("can't read a date",
                      run._wrong_week("Sheet1", today=MON))

    def test_this_weeks_tab_is_fine_later_in_its_week(self):
        # 2026-11-19, Thursday: the daily run called 'D2D OBCL 11.16' unbuilt
        # and opened a ticket, with this week's lineup sitting right there.
        for day in (17, 19, 22):
            self.assertIsNone(run._wrong_week(
                "D2D OBCL 11.16", today=dt.date(2026, 11, day)), day)


class ANobodyDueDayIsNotAFailure(unittest.TestCase):
    """The daily timer means most mornings nobody is due. That must exit 0,
    or the card goes red six days a week and the real refusal drowns."""

    def _send(self, tab_title, today):
        from unittest import mock

        class _WS:
            title = tab_title

        real = run._wrong_week
        with mock.patch.object(run.config, "early_send_blocked_by_copy",
                               return_value=None), \
                mock.patch.object(run, "_resolve_links",
                                  return_value=("s", "k", "src", [])), \
                mock.patch.object(run, "_people",
                                  return_value=(_WS(), [], [])), \
                mock.patch.object(run, "_wrong_week",
                                  lambda t, explicit=False: real(
                                      t, explicit=explicit, today=today)), \
                mock.patch("builtins.print"):
            return run.send()

    def test_a_tab_not_due_yet_exits_clean(self):
        self.assertEqual(self._send("D2D OBCL 11.23", dt.date(2026, 11, 18)), 0)

    def test_last_weeks_tab_still_fails(self):
        self.assertEqual(self._send("D2D OBCL 11.16", MON), 1)


class TheResendGuardIsPerPerson(unittest.TestCase):
    def test_the_per_person_check_exists_and_asks_gmail(self):
        import inspect

        from automations.slack_skool_email import gmail_reception as gm
        src = inspect.getsource(gm.already_sent_to)
        self.assertIn("in:sent", src)
        self.assertIn("bcc:", src)      # BCC-only sends, so To: alone misses

    def test_a_broken_guard_never_means_send_anyway(self):
        import inspect

        from automations.slack_skool_email import gmail_reception as gm
        self.assertIn("GuardUnavailable",
                      inspect.getsource(gm.already_sent_to))

    def test_the_send_no_longer_uses_the_whole_day_guard(self):
        # It would send the first group due this morning and swallow the
        # second. Asserted on the source because the alternative is a live
        # Gmail call -- and asserted on the CODE, with comments and docstrings
        # stripped: the first version of this test failed on the comment that
        # explains why the old guard is gone
        # ([[reference_source_assertions_strip_prose]]).
        import inspect
        code = _code_only(inspect.getsource(run.send))
        self.assertNotIn("already_sent_today", code)
        self.assertIn("already_sent_to", code)

    def test_it_looks_back_a_month_not_a_day(self):
        import inspect

        from automations.slack_skool_email import gmail_reception as gm
        sig = inspect.signature(gm.already_sent_to)
        self.assertEqual(sig.parameters["days"].default, 30)


if __name__ == "__main__":
    unittest.main()


class AFutureTabIsNotTheMissingLineupFault(unittest.TestCase):
    """A tab further out than the lead must not read as "nobody built it".

    Introduced by the lead itself: before it, any tab not dated today WAS
    last week's, so one message covered it. Now next week's tab is the normal
    state for most of the week, and the old wording sent somebody hunting for
    a lineup that had already been built.
    """

    def test_it_says_nobody_is_due_yet(self):
        why = run._wrong_week("D2D OBCL 11.23", today=dt.date(2026, 11, 18))
        self.assertTrue(why)
        self.assertIn("Nobody is due", why)
        self.assertIn("2026-11-21", why)        # when theirs goes

    def test_it_does_not_claim_the_lineup_is_missing(self):
        why = run._wrong_week("D2D OBCL 11.23", today=dt.date(2026, 11, 18))
        self.assertNotIn("hasn't been built", why)

    def test_a_past_tab_still_gets_the_real_warning(self):
        why = run._wrong_week("D2D OBCL 11.16", today=dt.date(2026, 11, 23))
        self.assertIn("hasn't been built yet", why)


class APastStartDayGetsNoWelcome(unittest.TestCase):
    """The one place this email differs from the paperwork.

    `new_start_timing.due` stays true after somebody's start, which is right
    for an unsigned I-9 and wrong for "we're excited to have you at
    orientation on Monday, November 16" sent on the Wednesday after. Found by
    the live preview on 2026-11-18: the newest tab was still dated 11.16 and
    46 people were lined up for exactly that email.
    """

    def test_somebody_whose_day_has_passed_is_not_grouped(self):
        people = [_P("Started", "s@x.com", dt.date(2026, 11, 16))]
        self.assertEqual(run._groups(people, today=dt.date(2026, 11, 18)), [])

    def test_they_are_reported_rather_than_vanishing(self):
        people = [_P("Started", "s@x.com", dt.date(2026, 11, 16))]
        got = run._already_started(people, today=dt.date(2026, 11, 18))
        self.assertEqual([p.name for p in got], ["Started"])

    def test_their_own_start_day_still_counts_as_due(self):
        # The day itself is not "passed" -- a same-day send says "today".
        day = dt.date(2026, 11, 23)
        self.assertEqual(len(run._groups([_P("A", "a@x.com", day)],
                                         today=day)), 1)

    def test_the_paperwork_rule_is_deliberately_unchanged(self):
        # Blue Ink still sends after a start; only this email stops.
        from automations.shared import new_start_timing as timing
        self.assertTrue(timing.due(dt.date(2026, 11, 16),
                                   dt.date(2026, 11, 18), 2))
