"""The schedule is the whole point of this module, so it is pinned hard.

The case that matters most is the one that motivated office-local times at all:
at a single instant, a Central office and an Eastern office are owed DIFFERENT
slots — an org-wide clock would have been wrong for one of them. That is
`test_eastern_and_central_are_due_an_hour_apart`.

    PYTHONPATH=. python -m unittest \
        automations.knocks_intraday.test_schedule -v
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.knocks_intraday import schedule as S
from automations.office_metrics.offices import OFFICES

UTC = dt.timezone.utc


class FakeOffice:
    """Just the two attributes `schedule` reads."""

    def __init__(self, key, timezone):
        self.key = key
        self.timezone = timezone


CODY = FakeOffice("cody", "America/Chicago")                # Corpus Christi, TX
AYA = FakeOffice("aya", "America/Indiana/Indianapolis")     # Indianapolis, IN


def at(y, m, d, hh, mm=0):
    """An aware UTC instant."""
    return dt.datetime(y, m, d, hh, mm, tzinfo=UTC)


# 2026-08-25 is a Monday. In August: Central = UTC-5, Eastern = UTC-4.
MON = (2026, 8, 25)


class Schedule(unittest.TestCase):

    def test_eastern_and_central_are_due_an_hour_apart(self):
        """THE reason the times are office-local. 19:00 UTC is 2:00 PM in Corpus
        Christi and 3:00 PM in Indianapolis: Cody is owed his first-knocks
        board; Aya was owed hers an hour ago and her window has closed."""
        due = {(d.office.key, d.slot.key)
               for d in S.due(at(*MON, 19, 0), [CODY, AYA])}
        self.assertIn(("cody", "first"), due)
        self.assertNotIn(("aya", "first"), due)

        # An hour earlier it is Aya's turn, not Cody's.
        due = {(d.office.key, d.slot.key)
               for d in S.due(at(*MON, 18, 0), [CODY, AYA])}
        self.assertIn(("aya", "first"), due)
        self.assertNotIn(("cody", "first"), due)

    def test_all_three_slots_fire_on_the_local_clock(self):
        # 9 PM CDT is 02:00 UTC the NEXT day.
        for slot_key, day, utc_hour, utc_min in (("first", 25, 19, 0),
                                                 ("money", 25, 22, 15),
                                                 ("eod", 26, 2, 0)):
            now = at(2026, 8, day, utc_hour, utc_min)
            keys = {d.slot.key for d in S.due(now, [CODY])}
            self.assertEqual(keys, {slot_key}, f"{slot_key} at {now}")

    def test_grace_window_opens_and_closes(self):
        first = S.SLOTS_BY_KEY["first"]
        self.assertTrue(S.is_due(CODY, first, at(*MON, 19, 0)))
        self.assertTrue(S.is_due(CODY, first, at(*MON, 19, 14)))
        # A 2 PM board is not posted at 6 PM — the moment has passed.
        self.assertFalse(S.is_due(CODY, first, at(*MON, 19, 15)))
        self.assertFalse(S.is_due(CODY, first, at(*MON, 18, 59)))

    def test_sunday_is_skipped(self):
        """2026-08-30 is a Sunday. Mon-Sat (Megan 2026-08-25)."""
        self.assertEqual(S.due(at(2026, 8, 30, 19, 0), [CODY]), [])
        self.assertNotEqual(S.due(at(2026, 8, 29, 19, 0), [CODY]), [])

    def test_sunday_is_judged_where_the_office_is(self):
        """03:00 UTC Monday is still Sunday 10 PM in Central. An office must not
        be posted to just because the runner's calendar has flipped."""
        sunday_night = at(2026, 8, 31, 3, 0)          # Sun 22:00 CDT
        self.assertEqual(S.local_now(CODY, sunday_night).weekday(), 6)
        self.assertEqual(S.due(sunday_night, [CODY]), [])

    def test_marker_blocks_a_repeat_in_the_same_window(self):
        now = at(*MON, 19, 0)
        due = S.due(now, [CODY])
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].marker, "cody:first:2026-08-25")
        self.assertEqual(S.due(now, [CODY], done={due[0].marker}), [])

    def test_eod_marker_uses_the_local_date_not_utc(self):
        """9 PM Central on the 25th is 02:00 UTC on the 26th. The marker — and
        the board — belong to the 25th, the day the office actually knocked."""
        due = S.due(at(2026, 8, 26, 2, 0), [CODY])[0]
        self.assertEqual(due.slot.key, "eod")
        self.assertEqual(due.local_date, dt.date(2026, 8, 25))
        self.assertEqual(due.marker, "cody:eod:2026-08-25")

    def test_naive_datetime_is_refused(self):
        with self.assertRaises(ValueError):
            S.local_now(CODY, dt.datetime(2026, 8, 25, 14, 0))

    def test_quiet_tick_returns_nothing(self):
        self.assertEqual(S.due(at(*MON, 16, 0), [CODY, AYA]), [])

    def test_next_fire_skips_sunday(self):
        # Saturday 10 PM Central, after the last slot -> Monday 2 PM.
        nxt = S.next_fire(CODY, at(2026, 8, 30, 3, 0))
        self.assertEqual(nxt.weekday(), 0)
        self.assertEqual((nxt.hour, nxt.minute), (14, 0))

    def test_against_the_real_registry(self):
        """The real offices carry usable timezones — and the Central/Eastern
        split shows up in the actual table, not just in fakes."""
        due = S.due(at(*MON, 19, 0), list(OFFICES.values()))
        keys = {d.office.key for d in due}
        self.assertIn("cody", keys)          # Central: 2 PM local
        self.assertNotIn("aya", keys)        # Eastern: already 3 PM
        for d in due:
            self.assertEqual(d.local_date, dt.date(2026, 8, 25))


if __name__ == "__main__":
    unittest.main()


class RosterIsaiah(unittest.TestCase):
    """2026-08-25: isaiah sat in roster.BLOCKED as "gaps-only rows still render
    as no-rows (785ad46)". The render path had since learned the shape, so the
    entry outlived its cause and quietly cost him every board (Megan: "Isaiah
    should post just like the others just with more limited data")."""

    def test_isaiah_is_enrolled_in_the_eod_slot(self):
        from automations.knocks_intraday import roster
        self.assertIn("isaiah", {o.key for o in roster.enrolled("eod")})

    def test_nothing_is_blocked_without_a_reason_string(self):
        """A BLOCKED entry must carry WHY. An empty dict is fine; a key with a
        blank reason is the stale-entry failure mode all over again."""
        from automations.knocks_intraday import roster
        for key, why in roster.BLOCKED.items():
            self.assertTrue(str(why).strip(), "%s is blocked with no reason" % key)

    def test_a_gaps_only_office_renders_one_real_board(self):
        """The claim the old block rested on, pinned: gaps-only rows must route
        to the TeleMapper board and produce ONE image, not a 'no rows' render."""
        import datetime as _dt, tempfile
        from pathlib import Path
        from automations.total_knocks import render as R
        rows = [{"ID": "9402597", "Rep": "Lorena Valverde",
                 "First Knock": "2:57 PM", "Last Knock": "6:20 PM",
                 "Breaks (min)": "", "Gaps": "3", "Total Gaps (min)": "113",
                 "Sales Time (min)": "", "Sales": ""}]
        self.assertEqual(R.knocks_shape(rows), R.SHAPE_GAPS_ONLY)
        pngs, shape = R.render_knocks_boards(
            _dt.date(2026, 8, 21), rows=rows, out_dir=Path(tempfile.mkdtemp()),
            title_suffix="isaiah", date_text="8/21")
        self.assertEqual(shape, R.SHAPE_GAPS_ONLY)
        self.assertEqual(len(pngs), 1)          # merged, not a pair
        self.assertGreater(pngs[0].stat().st_size, 5000)


class RosterRaf(unittest.TestCase):
    """Megan 2026-08-25, on the roster looking short: "Raf gets metrics every
    morning so I feel like we're missing something." He was never in
    office_metrics.OFFICES — folded onto the shared metrics CARD in July but not
    the office TABLE — so everything built on that table, this module included,
    could not see him."""

    def test_raf_is_in_the_eod_slot(self):
        from automations.knocks_intraday import roster
        self.assertIn("raf", {o.key for o in roster.enrolled("eod")})

    def test_raf_is_not_in_the_afternoon_slots(self):
        """2 PM and 5:15 PM stay Cody's alone."""
        from automations.knocks_intraday import roster
        for slot in ("first", "money"):
            self.assertEqual([o.key for o in roster.enrolled(slot)], ["cody"], slot)

    def test_raf_routes_to_the_master_pull(self):
        """His knocks_office must match what is_master_office compares against,
        or pull_offices_days tries to IMPERSONATE office 11280 — which is the
        login itself — and fails with "name not found in ownerville", a string
        the handler reads as an access gap."""
        from automations.knocks_intraday import roster
        from automations.rashad_metrics.knocks_pull import is_master_office
        raf = [o for o in roster.enrolled("eod") if o.key == "raf"][0]
        self.assertTrue(is_master_office(raf.knocks_office))

    def test_raf_stays_out_of_the_shared_office_table(self):
        """Adding him to office_metrics.OFFICES would enrol him in every report
        built on it and double-post the metrics he already gets from
        daily_metrics. He must exist ONLY in this roster."""
        from automations.office_metrics.offices import OFFICES
        self.assertNotIn("raf", OFFICES)

    def test_raf_has_a_channel_and_a_timezone(self):
        from automations.knocks_intraday import roster
        raf = [o for o in roster.enrolled("eod") if o.key == "raf"][0]
        self.assertTrue(raf.channel_id)
        self.assertEqual(raf.timezone, "America/Chicago")


class MissingCrossWorkspaceToken(unittest.TestCase):
    """Megan 2026-08-25: "it should fail loudly".

    A cross-workspace office (Trang -> FRESH SUCCESS) whose token file isn't on
    this machine used to count as `skipped`: the run exited 0, the wrapper
    published SUCCESS and the card went green while she got no board. That is
    the silent drop, and it is the likeliest failure here — push_slack_tokens
    moves only the MAIN workspace pair, so every new machine starts without the
    cross-workspace ones (Lucy 3, 2026-08-23)."""

    def _rec(self, key, token_file):
        from automations.office_metrics.offices import Office
        import datetime as _dt
        return {"office": key, "key": key, "day": _dt.date(2026, 8, 25),
                "abbr": "CST",
                "label": key.title(), "channel_id": "C1",
                "channel_name": "#" + key, "header_label": "",
                "token_file": token_file, "png": "/tmp/x.png",
                "rows": [{"Rep": "A"}], "error": None}

    def _post(self, recs):
        import datetime as _dt
        from automations.knocks_intraday import run as intraday, schedule as S
        lines = []
        # dry_run=False would post; token_path returns a path that does NOT
        # exist, so the guard fires before any Slack call is reached.
        code = intraday.post(recs, S.SLOTS_BY_KEY["eod"], dry_run=False,
                             logfn=lines.append)
        return code, lines

    def test_a_missing_token_is_a_nonzero_exit(self):
        code, _ = self._post([self._rec("trang", "slack-token-does-not-exist")])
        self.assertEqual(code, 1, "a missing token must not exit clean")

    def test_it_says_so_loudly_in_the_log(self):
        _, lines = self._post([self._rec("trang", "slack-token-does-not-exist")])
        blob = "\n".join(lines)
        self.assertIn("❌", blob)
        self.assertIn("trang", blob)
        self.assertIn("NOT posting with Lucy's token", blob)

    def test_it_never_falls_back_to_the_default_token(self):
        """The dangerous fix is worse than the outage: Lucy's token against a
        FRESH SUCCESS channel id could land the board in a different org."""
        _, lines = self._post([self._rec("trang", "slack-token-does-not-exist")])
        self.assertNotIn("posted trang", "\n".join(lines))
