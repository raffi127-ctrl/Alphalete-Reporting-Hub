"""What the 'didn't run today' baseline expects to see today.

Regression cover for 2026-08-18: Applicant Push (daily, live since 8/4) died on
Mon 8/17 and NOTHING alerted for the whole day — the same-weekday baseline needs
two prior same-weekdays and Monday only had one (8/10). The alert only landed
Tuesday, once Tuesday had two. The daily-cadence path closes that hole; these
tests pin both it and the weekend false-positives it must NOT create.
"""
import datetime as dt
import unittest

from automations.machine_digest.run import (_historical_expected, _handrun_only_ids,
                                            _nudge_specs, _ran_since,
                                            _offday_standalone_ids,
                                            _event_logged_ids)


def _rows(card, days, hour=7, name=None, machine="Lucys-MacBook-Neo.local"):
    return [{"Started At": f"{d.isoformat()}T{hour:02d}:05:00", "Report ID": card,
             "Report Name": name or card, "Machine": machine} for d in days]


def _span(target, start, end):
    """Dates from `start` to `end` days before `target`, inclusive."""
    return [target - dt.timedelta(days=n) for n in range(start, end + 1)]


class HistoricalExpected(unittest.TestCase):
    def test_young_daily_report_is_expected_on_a_weekday_it_hit_only_once(self):
        """THE 8/17 MISS. Daily since 8/4; on Mon 8/17 the 3-week weekday window
        holds a single Monday (8/10), so the weekday path stays silent — the
        daily path must cover it."""
        target = dt.date(2026, 8, 17)
        rows = _rows("applicant-push", _span(target, 1, 13), name="Applicant Push")
        exp = _historical_expected(rows, target)
        self.assertIn("applicant-push", exp)
        self.assertEqual(exp["applicant-push"]["start_hour"], 7)
        self.assertEqual(exp["applicant-push"]["name"], "Applicant Push")
        # and the weekday path alone genuinely does NOT catch it (the bug)
        self.assertNotIn("applicant-push",
                         _historical_expected(rows, target, daily_min_days=99))

    def test_weekday_only_report_is_not_expected_on_the_weekend(self):
        """A Mon-Fri report also clears 5-of-7 density, so density alone would
        post 'didn't run today' every Saturday. The same-weekday proof stops it."""
        target = dt.date(2026, 8, 15)          # Saturday
        weekdays = [d for d in _span(target, 1, 21) if d.weekday() < 5]
        self.assertNotIn("daily-focus",
                         _historical_expected(_rows("daily-focus", weekdays), target))

    def test_weekday_only_report_is_still_expected_on_a_weekday(self):
        target = dt.date(2026, 8, 13)          # Thursday
        weekdays = [d for d in _span(target, 1, 21) if d.weekday() < 5]
        self.assertIn("daily-focus",
                      _historical_expected(_rows("daily-focus", weekdays), target))

    def test_still_expected_on_day_two_of_an_outage(self):
        """The watcher must not go quiet on the second dead day — that would hide
        exactly the failure it exists to report."""
        target = dt.date(2026, 8, 18)
        ran = _span(target, 2, 14)             # everything except yesterday
        self.assertIn("applicant-push", _historical_expected(_rows("applicant-push", ran), target))

    def test_retired_daily_report_drops_out(self):
        """Dead for a week+ → no same-weekday hit → it stops being expected,
        instead of alerting forever."""
        target = dt.date(2026, 8, 18)
        ran = _span(target, 8, 21)
        self.assertNotIn("applicant-push", _historical_expected(_rows("applicant-push", ran), target))

    def test_occasional_report_is_never_expected(self):
        target = dt.date(2026, 8, 18)
        ran = [target - dt.timedelta(days=n) for n in (1, 4)]
        self.assertNotIn("one-off", _historical_expected(_rows("one-off", ran), target))

    def test_start_hour_anchors_to_the_most_recent_day(self):
        """A one-off early test run days ago must not drag the alert time earlier."""
        target = dt.date(2026, 8, 18)
        rows = _rows("applicant-push", _span(target, 1, 6), hour=7)
        rows += _rows("applicant-push", [target - dt.timedelta(days=7)], hour=3)
        self.assertEqual(_historical_expected(rows, target)["applicant-push"]["start_hour"], 7)

    def test_a_daily_report_that_moved_later_is_not_flagged_at_its_old_hour(self):
        """THE 8/20-8/23 NOISE. enrollment_pending_check left the 4am pass for a
        09:00-22:00 hourly agent on 8/19. The weekday path anchors to the same
        weekday SEVEN days back — still 4:00 — so the watcher posted 'didn't run
        today · usually starts ~4:00' four mornings running, each one resolved by
        the 9:00 run that was never late. The daily anchor (most recent day it
        actually ran) has to win."""
        target = dt.date(2026, 8, 23)
        rows = _rows("enrollment_pending_check", _span(target, 5, 21), hour=4)
        rows += _rows("enrollment_pending_check", _span(target, 1, 4), hour=9)
        exp = _historical_expected(rows, target)
        self.assertIn("enrollment_pending_check", exp)
        self.assertEqual(exp["enrollment_pending_check"]["start_hour"], 9)

    def test_the_machine_refreshes_with_the_hour(self):
        """Same staleness, same fix: that agent moved to Lucy 1, and the alert
        kept saying 'on the mini'."""
        target = dt.date(2026, 8, 23)
        rows = _rows("enrollment_pending_check", _span(target, 5, 21), hour=4,
                     machine="Alphaletes-Mac-mini.local")
        rows += _rows("enrollment_pending_check", _span(target, 1, 4), hour=9,
                      machine="Lucys-MacBook-Pro.local")
        exp = _historical_expected(rows, target)
        self.assertEqual(exp["enrollment_pending_check"]["machine"],
                         "Lucys-MacBook-Pro.local")

    def test_a_stable_daily_report_keeps_its_hour(self):
        """The refresh must be a no-op for everything that didn't move."""
        target = dt.date(2026, 8, 23)
        rows = _rows("daily-metrics", _span(target, 1, 21), hour=4)
        self.assertEqual(
            _historical_expected(rows, target)["daily-metrics"]["start_hour"], 4)

    def test_a_weekly_report_is_untouched_by_the_daily_refresh(self):
        """A weekly report never clears the daily density bar, so its hour still
        comes from the same-weekday anchor — unchanged behaviour."""
        target = dt.date(2026, 8, 23)                      # Sunday
        sundays = [target - dt.timedelta(days=7 * w) for w in (1, 2, 3)]
        rows = _rows("weekly-knock-dispositions", sundays, hour=6)
        exp = _historical_expected(rows, target)
        self.assertEqual(exp["weekly-knock-dispositions"]["start_hour"], 6)

    def test_a_late_manual_rerun_does_not_move_the_hour(self):
        """A 4am run plus a 2pm re-run on the same day is still a 4am report —
        hour_by_day keeps the earliest start, so the anchor stays 4."""
        target = dt.date(2026, 8, 23)
        rows = _rows("daily-metrics", _span(target, 1, 21), hour=4)
        rows += _rows("daily-metrics", [target - dt.timedelta(days=1)], hour=14)
        self.assertEqual(
            _historical_expected(rows, target)["daily-metrics"]["start_hour"], 4)

    def test_one_midnight_outlier_day_does_not_drag_the_anchor(self):
        """THE 9/3 4AM FALSE ALARM. Rep Gap Alerts writes ONE Activity row a day,
        at its first good tick (~13:30). Three `gap_alerts --send --force` jobs
        queued 4pm on 9/1 sat behind a long job in Lucy 1's serial lane and
        drained at 00:00 the next morning, so 9/2's only row read 00:00. The
        newest-day anchor took that lone row as the schedule and posted "didn't
        run today on the mini · usually starts ~0:00" at 4am on 9/3 — for a
        report whose window does not open until 1:30pm. The median floor keeps
        the anchor at 13, so the earliest it can now be called missing is 3pm."""
        target = dt.date(2026, 9, 3)
        rows = _rows("gap-alerts", _span(target, 2, 7), hour=13)
        rows += _rows("gap-alerts", [target - dt.timedelta(days=1)], hour=0)
        exp = _historical_expected(rows, target)
        self.assertEqual(exp["gap-alerts"]["start_hour"], 13)

    def test_a_real_move_to_a_later_hour_still_wins_on_day_one(self):
        """The case the newest-day anchor exists for must survive the median
        floor: enrollment_pending_check left the 4am batch for its own 09:00
        agent, and the watcher must expect 9 the very next morning, not 4."""
        target = dt.date(2026, 8, 20)
        rows = _rows("enrollment-pending-check", _span(target, 2, 7), hour=4)
        rows += _rows("enrollment-pending-check", [target - dt.timedelta(days=1)],
                      hour=9)
        exp = _historical_expected(rows, target)
        self.assertEqual(exp["enrollment-pending-check"]["start_hour"], 9)

    def test_a_settled_move_to_an_earlier_hour_is_followed(self):
        """The floor is a floor, not a freeze: once the new earlier hour is the
        window's norm rather than one odd day, the median moves with it."""
        target = dt.date(2026, 8, 20)
        rows = _rows("some-report", _span(target, 1, 5), hour=9)
        rows += _rows("some-report", _span(target, 6, 7), hour=14)
        exp = _historical_expected(rows, target)
        self.assertEqual(exp["some-report"]["start_hour"], 9)


class _Cfg:
    def __init__(self, reports):
        self.raw = {"reports": reports}


class OffdayStandaloneIds(unittest.TestCase):
    """Regression cover for 2026-08-22: dd_gross_revenue runs the 1st & 15th at
    noon (plist Day 1/15), and in August 2026 both fell on Saturdays — so the
    weekday baseline learned 'weekly Saturday report' and posted 'didn't run
    today' on Sat 8/22 while nothing was wrong. `standalone_monthdays` pins the
    real day-of-month schedule the way `standalone_weekdays` pins vantura's
    Wednesday."""

    MONTHLY = _Cfg({"dd_gross_revenue": {"standalone_monthdays": [1, 15]}})

    def test_monthdays_report_is_exempt_on_an_off_day(self):
        # Sat 8/22 — the false-alarm day.
        self.assertIn("dd_gross_revenue",
                      _offday_standalone_ids(self.MONTHLY, dt.date(2026, 8, 22)))

    def test_monthdays_report_is_watched_on_its_run_days(self):
        for d in (dt.date(2026, 8, 15), dt.date(2026, 9, 1), dt.date(2026, 9, 15)):
            self.assertNotIn("dd_gross_revenue",
                             _offday_standalone_ids(self.MONTHLY, d))

    def test_weekday_pin_still_works_alone(self):
        cfg = _Cfg({"vantura_payroll": {"standalone_weekdays": [2]}})   # Wed
        self.assertIn("vantura_payroll", _offday_standalone_ids(cfg, dt.date(2026, 8, 20)))
        self.assertNotIn("vantura_payroll", _offday_standalone_ids(cfg, dt.date(2026, 8, 19)))

    def test_both_pins_declared_means_both_must_match(self):
        # launchd's Day+Weekday AND rule: 9/15/2026 is a Tuesday (weekday 1).
        cfg = _Cfg({"r": {"standalone_weekdays": [1], "standalone_monthdays": [15]}})
        self.assertNotIn("r", _offday_standalone_ids(cfg, dt.date(2026, 9, 15)))
        self.assertIn("r", _offday_standalone_ids(cfg, dt.date(2026, 9, 14)))   # Mon the 14th
        self.assertIn("r", _offday_standalone_ids(cfg, dt.date(2026, 9, 22)))   # Tue the 22nd

    def test_undeclared_report_keeps_the_historical_guess(self):
        cfg = _Cfg({"plain": {}})
        self.assertNotIn("plain", _offday_standalone_ids(cfg, dt.date(2026, 8, 22)))


class CadenceIsItsOwnPin(unittest.TestCase):
    """2026-09-20: icd_start_dates posted "didn't run today on the mini - usually
    starts ~8:00" on a SUNDAY. It is on_scheduler with cadence.weekdays [0..5]
    (Mon-Sat), so the orchestrator correctly wasn't running it -- which dropped
    it out of _orchestrator_ids and onto the watcher, where the only evidence
    left was an Activity log showing six 08:00 runs a week.

    A report that already declares which days it runs should not have to
    declare them a second time under standalone_weekdays: the copy is one more
    thing to keep in step, and it goes stale the day the cadence moves."""

    SIX_DAY = _Cfg({"icd_start_dates": {
        "on_scheduler": True, "cadence": {"weekdays": [0, 1, 2, 3, 4, 5]}}})

    def test_a_mon_sat_report_is_exempt_on_sunday(self):
        # Sun 2026-09-20 -- the false-alarm day.
        self.assertIn("icd_start_dates",
                      _offday_standalone_ids(self.SIX_DAY, dt.date(2026, 9, 20)))

    def test_it_is_still_watched_every_day_it_does_run(self):
        for day in range(14, 20):          # Mon 9/14 .. Sat 9/19
            self.assertNotIn(
                "icd_start_dates",
                _offday_standalone_ids(self.SIX_DAY, dt.date(2026, 9, day)))

    def test_an_explicit_pin_still_wins_over_the_cadence(self):
        """standalone_weekdays stays the override for a report whose plist and
        cadence disagree -- the cadence is only the fallback."""
        cfg = _Cfg({"r": {"on_scheduler": True,
                          "cadence": {"weekdays": [0, 1, 2, 3, 4, 5]},
                          "standalone_weekdays": [2]}})            # Wed only
        self.assertIn("r", _offday_standalone_ids(cfg, dt.date(2026, 9, 14)))   # Mon
        self.assertNotIn("r", _offday_standalone_ids(cfg, dt.date(2026, 9, 16)))  # Wed

    def test_an_empty_cadence_is_not_read_as_never_due(self):
        """weekdays [] means "the loop never runs this, its real schedule is a
        plist" -- the reports the watcher is the ONLY alert for. Reading [] as
        "due no day" would silence every one of them."""
        cfg = _Cfg({"weather": {"on_scheduler": True, "cadence": {"weekdays": []}}})
        for day in range(14, 21):
            self.assertNotIn("weather",
                             _offday_standalone_ids(cfg, dt.date(2026, 9, day)))

    def test_a_non_scheduler_report_keeps_the_historical_guess(self):
        """on_scheduler:false means cadence.weekdays isn't the real schedule --
        that lives in a plist, which is exactly why standalone_weekdays exists."""
        cfg = _Cfg({"paused": {"on_scheduler": False,
                               "cadence": {"weekdays": [0, 1, 2, 3, 4]}}})
        self.assertNotIn("paused",
                         _offday_standalone_ids(cfg, dt.date(2026, 9, 20)))


class OneshotUtilityIds(unittest.TestCase):
    """Hand-run utilities must never enter the 'expected today' baseline.

    2026-08-24: `list_agents` — a read-only LaunchAgent lister with no cadence,
    no machine and no agent — posted "didn't run today on the mini · usually
    starts ~8:00" after a week of being hand-run during debugging. Same shape as
    `disable_oat_processing_agent`, which posted every Wednesday in August."""

    class _C:
        def __init__(self, reports):
            self.raw = {"reports": reports}

    def _ids(self, reports):
        from automations.machine_digest.run import _oneshot_utility_ids
        return _oneshot_utility_ids(self._C(reports))

    def test_read_only_listers_are_exempt(self):
        ids = self._ids({
            "list_agents": {"command": ["automations.day_orchestrator.list_agents"]},
            "probe_imessage_threads": {
                "command": ["automations.day_orchestrator.imessage_thread_probe"]},
        })
        self.assertIn("list_agents", ids)
        self.assertIn("probe_imessage_threads", ids)

    def test_installers_are_still_exempt(self):
        ids = self._ids({"install_x_agent":
                         {"command": ["automations.day_orchestrator.install_agent"]}})
        self.assertIn("install_x_agent", ids)

    def test_real_reports_are_never_exempt(self):
        """The 40 reports that share list_agents' config shape but run from
        their own LaunchAgents must stay watched."""
        ids = self._ids({
            "stf_field_check": {"command": ["automations.stf_field_check.run"]},
            "org_board_slack": {"command": ["automations.org_sales_board.slack_post"]},
            "sara_down": {"command": ["automations.sara_down.run"]},
            "box_order_log": {"command": ["automations.box_order_log.run"]},
        })
        self.assertEqual(ids, set())


class HandRunOnlyIds(unittest.TestCase):
    """Regression cover for 2026-08-24: `alphalete_org_b2b` — a sub-step handle
    that exists only for `lucy rerun`, cadence.weekdays [] so the orchestrator
    never fires it — posted "didn't run today on Lucy 2 · usually starts ~16:00"
    off two Monday hand-reruns (8/10, 8/17). Nothing was ever going to run it."""

    def _ids(self, reports):
        return _handrun_only_ids(_Cfg(reports))

    def test_declared_substep_is_exempt(self):
        ids = self._ids({"alphalete_org_b2b": {
            "hand_run_only": True, "cadence": {"weekdays": []}}})
        self.assertIn("alphalete_org_b2b", ids)

    def test_undeclared_substep_keeps_the_historical_guess(self):
        """alphalete_org_je has the same config shape but a real Monday catch-up
        agent (com.alphalete.je-opt-monday-catchup.plist), so it must NOT be
        exempted just for looking like its siblings."""
        ids = self._ids({"alphalete_org_je": {"cadence": {"weekdays": []}}})
        self.assertEqual(ids, set())

    def test_flag_is_ignored_when_the_orchestrator_can_fire_it(self):
        """The narrow half of the rule: a stray hand_run_only on something with a
        real cadence must never silence it."""
        ids = self._ids({"daily_focus": {
            "hand_run_only": True, "cadence": {"weekdays": [0, 1, 2, 3, 4]}}})
        self.assertEqual(ids, set())

    def test_missing_cadence_is_not_exempt(self):
        """No cadence key at all is not the same as a declared-empty one — an
        on_scheduler:false LaunchAgent report looks like this, and its schedule
        lives in a plist we can't read. Bias to under-exempting."""
        self.assertEqual(self._ids({"stf_field_check": {"hand_run_only": True}}), set())

    def test_real_reports_are_never_exempt(self):
        ids = self._ids({
            "stf_field_check": {"cadence": {"weekdays": []}},
            "org_board_slack": {"cadence": {"weekdays": []}},
            "daily_focus": {"cadence": {"weekdays": [0, 1, 2, 3, 4]}},
        })
        self.assertEqual(ids, set())

    def test_live_config_flags_exactly_the_three_substeps(self):
        """Pins the live schedule_config: _b2b/_box/_retail carry the flag, _je
        does not (it has a real Monday agent)."""
        from automations.day_orchestrator import registry as _reg
        ids = _handrun_only_ids(_reg.load_config())
        for rid in ("alphalete_org_b2b", "alphalete_org_box", "alphalete_org_retail"):
            self.assertIn(rid, ids)
        self.assertNotIn("alphalete_org_je", ids)

    def test_live_config_flags_the_two_BOX_repair_handles(self):
        """2026-09-03: `box_order_log_repost` is a REPAIR handle — no plist ever
        fires it — but five hand-runs (Thu 8/20 x2, Fri 8/21, Wed 8/26, Thu 8/27)
        left rows on two of the last three Thursdays, so _historical_expected
        called it a "Thursday ~13:00 report on Lucy 2" and posted "did not run
        today" on Thu 9/3. Its twin `box_order_log_tier_backfill` is the same
        shape. The scheduled `box_order_log` (com.alphalete.box-order-log.plist,
        7:00 + 8:30 daily) must stay watched."""
        from automations.day_orchestrator import registry as _reg
        ids = _handrun_only_ids(_reg.load_config())
        for rid in ("box_order_log_repost", "box_order_log_tier_backfill"):
            self.assertIn(rid, ids)
        self.assertNotIn("box_order_log", ids)


class EventLoggedIds(unittest.TestCase):
    """Regression cover for 2026-09-01: `sara_down` polls #saraplus-issues every 5
    minutes 24/7 but calls publish_done ONLY on a real escalation, so the Activity
    log holds one row per ISSUE (8 in six weeks), not one per run. Escalations on
    Tue 8/11 and Tue 8/25 17:42 taught _historical_expected "Tuesday ~17:00
    report", and it posted "didn't run today on the mini · usually starts ~17:00"
    while the poller had ticked every 5 min all day, exit 0."""

    def _ids(self, reports):
        return _event_logged_ids(_Cfg(reports))

    def test_declared_poller_is_exempt(self):
        ids = self._ids({"sara_down": {
            "logs_on_event_only": True, "cadence": {"weekdays": []}}})
        self.assertIn("sara_down", ids)

    def test_undeclared_poller_keeps_the_historical_guess(self):
        ids = self._ids({"sara_down": {"cadence": {"weekdays": []}}})
        self.assertEqual(ids, set())

    def test_flag_is_ignored_when_the_orchestrator_can_fire_it(self):
        """The narrow half: a stray flag on something with a real cadence must
        never silence it."""
        ids = self._ids({"daily_focus": {
            "logs_on_event_only": True, "cadence": {"weekdays": [0, 1, 2, 3, 4]}}})
        self.assertEqual(ids, set())

    def test_missing_cadence_is_not_exempt(self):
        """Same bias-to-under-exempting rule as hand_run_only: no cadence key is
        not a declared-empty one."""
        self.assertEqual(self._ids({"sara_down": {"logs_on_event_only": True}}), set())

    def test_real_reports_are_never_exempt(self):
        ids = self._ids({
            "stf_field_check": {"cadence": {"weekdays": []}},
            "bg_check_sync": {"cadence": {"weekdays": []}},
            "daily_focus": {"cadence": {"weekdays": [0, 1, 2, 3, 4]}},
        })
        self.assertEqual(ids, set())

    def test_live_config_exempts_sara_and_nothing_scheduled(self):
        """Pins the live schedule_config: sara_down carries the flag under all
        three id spellings the Activity log can use, and no report the
        orchestrator fires ever gets swept in."""
        from automations.day_orchestrator import registry as _reg
        ids = _event_logged_ids(_reg.load_config())
        for rid in ("sara_down", "sara-plus-issues"):
            self.assertIn(rid, ids)
        for rid in ("daily_focus", "office_metrics", "stf_field_check"):
            self.assertNotIn(rid, ids)

    def test_sara_is_expected_today_which_is_why_the_flag_is_needed(self):
        """The flag is the ONLY thing standing between sara_down and a false
        alarm: the historical baseline still says "expected today", exactly as it
        did on 9/1. If this ever stops being true the flag is dead weight and the
        exemption should be reconsidered rather than left silently covering
        nothing."""
        tue = dt.date(2026, 9, 1)
        rows = (_rows("sara-plus-issues", [dt.date(2026, 8, 11)], hour=11)
                + _rows("sara-plus-issues", [dt.date(2026, 8, 25)], hour=17))
        exp = _historical_expected(rows, tue)
        self.assertIn("sara-plus-issues", exp)
        self.assertEqual(exp["sara-plus-issues"]["start_hour"], 17)


if __name__ == "__main__":
    unittest.main()


class ApexNewStartsIsAButtonNotASchedule(unittest.TestCase):
    """Regression cover for 2026-09-24. `New Starts -> Apex` is a Hub BUTTON a
    person presses on a Thursday or Friday — no LaunchAgent, no 4am batch, no
    clock of any kind, because it rides the Apex login in the operator's own
    Chrome. Megan pressed it on Thu 9/17 (first run 15:31) and on Thu 9/3
    (19:35), which is two of the last three Thursdays WITH the recency gate
    satisfied, so on Thu 9/24 the watcher posted

        "New Starts -> Apex — didn't run today on MacBook-Pro-3.local ·
         usually starts ~15:00"

    and told whoever picked it up to go check a LaunchAgent that has never
    existed. Exactly the sara_down / alphalete_org_b2b shape: the Activity log
    is not the schedule.

    It could not have been suppressed before, either — the report had NO entry
    in schedule_config at all, and `_handrun_only_ids` can only read ids that
    are in there. The declaration is the entry.

    NOTE the hand-run marker does NOT cover this. `_is_hand_run` gates the
    ERRORED branch (see test_hand_run_not_an_incident), and every row here is a
    SUCCESS — the didn't-run branch never reads the User column, because its
    whole premise is that no row exists today.
    """

    THURSDAY = dt.date(2026, 9, 24)

    def _log(self):
        """The real Activity rows, verbatim-shaped: 9/3 at 19:35, then the
        9/17 session from 15:31, then Fri 9/18 on the office iMac."""
        return (_rows("apex-new-starts", [dt.date(2026, 9, 3)], hour=19,
                      name="New Starts → Apex", machine="MacBook-Pro-3.local")
                + _rows("apex-new-starts", [dt.date(2026, 9, 17)], hour=15,
                        name="New Starts → Apex", machine="MacBook-Pro-3.local")
                + _rows("apex-new-starts", [dt.date(2026, 9, 18)], hour=11,
                        name="New Starts → Apex",
                        machine="Zacharys-iMac.attwifi.manager"))

    def test_the_baseline_really_does_expect_it_today(self):
        """The flag is the only thing standing between this card and the false
        alarm — same check sara_down carries. If this stops being true the
        exemption is covering nothing and should be reconsidered, not left."""
        info = _historical_expected(self._log(), self.THURSDAY).get("apex-new-starts")
        self.assertIsNotNone(info)
        self.assertEqual(info["start_hour"], 15)              # what the post said
        self.assertEqual(info["machine"], "MacBook-Pro-3.local")   # ditto

    def test_the_live_config_declares_it_hand_run_only(self):
        from automations.day_orchestrator import registry as _reg
        ids = _handrun_only_ids(_reg.load_config())
        # Activity rows are written under the kebab CARD id; `lucy rerun` and
        # schedule_config use the underscore one. Both must resolve.
        self.assertIn("apex-new-starts", ids)
        self.assertIn("apex_new_starts", ids)

    def test_a_scheduled_report_on_the_same_machine_is_untouched(self):
        """Don't let a broad exemption ride in on this one."""
        from automations.day_orchestrator import registry as _reg
        ids = _handrun_only_ids(_reg.load_config())
        for rid in ("daily_focus", "office_metrics", "blueink_docs"):
            self.assertNotIn(rid, ids)


class TheNotRunYetNudge(unittest.TestCase):
    """Megan, 2026-09-24, after `hand_run_only` silenced the false incident:
    *"if no one runs this - I just want the alert to say 'Heads up, no one has
    ran the Apex employee addition'"*.

    So the two declarations are halves of one answer and must not fight:
    `hand_run_only` kills the watcher's GUESS at a schedule it cannot see, and
    `nudge_if_not_run` states the real one. Step 2 skips the id via `offday`,
    step 2c picks it up here.
    """

    def _specs(self, reports):
        return _nudge_specs(_Cfg(reports))

    def test_it_is_keyed_by_the_id_THE_ACTIVITY_LOG_WRITES(self):
        """THE ONE THAT WOULD HAVE LEFT THE THREAD OPEN. Unlike the other
        declarations this dict is POSTED from, and the key becomes the incident
        key (`standalone-<id>`). Keyed by the schedule_config spelling it opened
        `standalone-apex_new_starts` while the Hub row says `apex-new-starts`,
        so _close_recovered_incidents — which looks up `standalone-<rid>` off
        the Activity row — could never find it, and the heads-up would have sat
        open right through the afternoon the work got done. ONE entry per card,
        under the kebab id; the spellings live on `aliases`."""
        specs = self._specs({"apex_new_starts": {
            "cadence": {"weekdays": []},
            "nudge_if_not_run": {"weekdays": [3, 4], "hour": 15}}})
        self.assertEqual(list(specs), ["apex-new-starts"])          # ONE, kebab
        self.assertEqual(specs["apex-new-starts"]["aliases"],
                         {"apex_new_starts", "apex-new-starts"})
        self.assertEqual(specs["apex-new-starts"]["weekdays"], [3, 4])
        self.assertEqual(specs["apex-new-starts"]["hour"], 15)

    def test_either_spelling_in_the_log_counts_as_pressed(self):
        """The aliases earn their keep here: the Hub row and the config have
        always disagreed about the separator, and a nudge that missed the run
        because of a hyphen would nag her the day she did the work."""
        specs = self._specs({"apex_new_starts": {
            "cadence": {"weekdays": []},
            "nudge_if_not_run": {"weekdays": [3, 4], "hour": 15}}})
        aliases = specs["apex-new-starts"]["aliases"]
        monday = dt.date(2026, 9, 21)
        for spelling in ("apex-new-starts", "apex_new_starts"):
            rows = _rows(spelling, [dt.date(2026, 9, 24)], hour=15)
            self.assertTrue(_ran_since(rows, aliases, monday), spelling)

    def test_flag_is_ignored_when_the_orchestrator_can_fire_it(self):
        """The narrow half, same as hand_run_only / logs_on_event_only: a card
        the 4am batch really runs already alerts for real, and a cheerful
        "nobody's run this yet" beside a genuine MISSED is worse than either."""
        self.assertEqual(self._specs({"daily_focus": {
            "cadence": {"weekdays": [0, 1, 2, 3, 4]},
            "nudge_if_not_run": {"weekdays": [3], "hour": 15}}}), {})

    def test_no_days_named_says_nothing(self):
        """Bias to quiet: an empty or missing weekday list is not 'every day'."""
        self.assertEqual(self._specs({"apex_new_starts": {
            "cadence": {"weekdays": []},
            "nudge_if_not_run": {"hour": 15}}}), {})

    def test_undeclared_cards_are_never_nudged(self):
        self.assertEqual(self._specs({"apex_payroll": {"cadence": {"weekdays": []}}}), {})

    def test_the_live_config_nudges_apex_on_thursday_and_friday(self):
        from automations.day_orchestrator import registry as _reg
        specs = _nudge_specs(_reg.load_config())
        self.assertIn("apex-new-starts", specs)
        self.assertEqual(specs["apex-new-starts"]["weekdays"], [3, 4])
        self.assertTrue(specs["apex-new-starts"]["how"])   # must say how to run it

    def test_nudging_and_silencing_are_declared_together(self):
        """THE PAIRING. A card that nudges must also be hand_run_only, or step 2
        posts the ":no_entry_sign: didn't run today on <machine>" incident and
        step 2c posts the heads-up, and the channel says both about one card."""
        from automations.day_orchestrator import registry as _reg
        cfg = _reg.load_config()
        silenced = _handrun_only_ids(cfg) | _event_logged_ids(cfg)
        for cid in _nudge_specs(cfg):
            self.assertIn(cid, silenced, f"{cid} nudges but isn't silenced")


class TheWeekWindow(unittest.TestCase):
    """The subtlety: the nudge asks about THE WEEK, not today. Apex does one
    cohort per week, so running it Thursday must leave Friday quiet — asking
    "did it run today" would nag her the morning after she did the work."""

    MONDAY = dt.date(2026, 9, 21)

    def test_thursdays_run_silences_friday(self):
        rows = _rows("apex-new-starts", [dt.date(2026, 9, 24)], hour=15)
        self.assertEqual(_ran_since(rows, {"apex-new-starts"}, self.MONDAY),
                         {"apex-new-starts"})

    def test_last_weeks_run_does_NOT_silence_this_week(self):
        """The 9/17-9/18 cohort is done and gone; WE 9.27 is still owed."""
        rows = (_rows("apex-new-starts", [dt.date(2026, 9, 17)], hour=15)
                + _rows("apex-new-starts", [dt.date(2026, 9, 18)], hour=11))
        self.assertEqual(_ran_since(rows, {"apex-new-starts"}, self.MONDAY), set())

    def test_a_failed_press_still_counts_as_pressed(self):
        """Somebody hitting a problem is not somebody forgetting — and step 1
        already alerts on the failure. Two posts arguing about one card is the
        exact noise this kind exists to avoid."""
        rows = _rows("apex-new-starts", [dt.date(2026, 9, 24)], hour=15)
        for r in rows:
            r["Status"] = "failed"
        self.assertEqual(_ran_since(rows, {"apex-new-starts"}, self.MONDAY),
                         {"apex-new-starts"})
