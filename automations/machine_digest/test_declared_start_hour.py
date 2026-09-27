"""When the 'didn't run today' deadline is DECLARED instead of guessed.

Regression cover for Sun 2026-09-27. Every mode of New-Start Follow-Up publishes
under the ONE card id `new-start-followup`: the Tue-Fri daily reminder at ~09:00,
the Saturday roll call at 08:00, and Raf's Sunday ✅ checklist at 13:00
(com.alphalete.new-start-followup-sun, Weekday 0). `_historical_expected` carries
ONE start_hour per card, read off the most recent same-weekday — so a stray
read-only `--mode status` row at 09:44 on Sun 2026-09-20 made last-Sunday's
EARLIEST hour 9, and at 11:07 the watcher posted "New-Start Follow-Up — didn't
run today on the mini · usually starts ~9:00" about a report that was not due for
another two hours, on a mini whose 30-minute thread scan had run clean all
morning (08:00 … 11:30, every one exit 0).

`standalone_weekdays` pins WHICH DAYS. `standalone_start_hour` pins WHAT TIME on
each of them — the other half of the same guess. It exempts nothing: a report
that really is missing still alerts, just never before its own start time.
"""
import datetime as dt
import unittest

from automations.machine_digest.run import (_declared_start_hours,
                                            _historical_expected,
                                            _offday_standalone_ids)


class _Cfg:
    def __init__(self, reports):
        self.raw = {"reports": reports}


SUN = dt.date(2026, 9, 27)
SAT = dt.date(2026, 9, 26)
MON = dt.date(2026, 9, 28)
TUE = dt.date(2026, 9, 29)


class DeclaredStartHours(unittest.TestCase):
    NSF = _Cfg({"new_start_followup": {
        "standalone_start_hour": {"1": 9, "2": 9, "3": 9, "4": 9, "5": 8, "6": 13}}})

    def test_the_declared_hour_is_todays_hour(self):
        self.assertEqual(_declared_start_hours(self.NSF, SUN)["new_start_followup"], 13)
        self.assertEqual(_declared_start_hours(self.NSF, SAT)["new_start_followup"], 8)
        self.assertEqual(_declared_start_hours(self.NSF, TUE)["new_start_followup"], 9)

    def test_it_answers_under_the_card_id_too(self):
        """Activity rows are written under the CARD id, so the didn't-run branch
        looks the hour up by `new-start-followup`, not the registry id."""
        self.assertEqual(_declared_start_hours(self.NSF, SUN)["new-start-followup"], 13)

    def test_a_weekday_left_out_keeps_the_guess(self):
        self.assertNotIn("new_start_followup", _declared_start_hours(self.NSF, MON))

    def test_a_plain_int_declares_every_day(self):
        cfg = _Cfg({"r": {"standalone_start_hour": 13}})
        for d in (SUN, SAT, MON, TUE):
            self.assertEqual(_declared_start_hours(cfg, d)["r"], 13)

    def test_undeclared_report_keeps_the_guess(self):
        self.assertEqual(_declared_start_hours(_Cfg({"plain": {}}), SUN), {})

    def test_junk_is_ignored_rather_than_believed(self):
        """A typo must fall back to the historical guess, never to hour 0 —
        hour 0 + 2h grace would page at 02:00 about every report on the list."""
        for bad in (True, False, "13", 24, -1, None, {"6": "13"}, {"6": True}):
            cfg = _Cfg({"r": {"standalone_start_hour": bad}})
            self.assertEqual(_declared_start_hours(cfg, SUN), {}, bad)


class TheSundayFalseAlarm(unittest.TestCase):
    """The 2026-09-27 post, end to end: the log really does say 9, the
    declaration really does move the deadline to 13, and the guess is what the
    watcher would otherwise have used."""

    def _sunday_rows(self):
        rows = []
        for w in (1, 2, 3):
            d = (SUN - dt.timedelta(days=7 * w)).isoformat()
            rows.append({"Started At": f"{d}T13:00:04", "Report ID": "new-start-followup",
                         "Report Name": "New-Start Follow-Up",
                         "Machine": "Alphaletes-Mac-mini.local"})
        # the stray read-only status run, Sun 2026-09-20 09:44
        rows.append({"Started At": "2026-09-20T09:44:57", "Report ID": "new-start-followup",
                     "Report Name": "New-Start Follow-Up — who's sent?",
                     "Machine": "Alphaletes-Mac-mini.local"})
        return rows

    def test_one_stray_morning_row_drags_the_guess_to_nine(self):
        exp = _historical_expected(self._sunday_rows(), SUN)
        self.assertEqual(exp["new-start-followup"]["start_hour"], 9)   # the bug

    def test_the_declaration_puts_the_deadline_back_at_one_pm(self):
        cfg = _Cfg({"new_start_followup": {"standalone_start_hour": {"6": 13}}})
        self.assertEqual(_declared_start_hours(cfg, SUN)["new-start-followup"], 13)


class LiveConfig(unittest.TestCase):
    """Pins the real schedule_config — keep these in step with the plists."""

    def _cfg(self):
        from automations.day_orchestrator import registry as _reg
        return _reg.load_config()

    def test_new_start_followup_is_due_at_one_on_sunday_and_eight_on_saturday(self):
        cfg = self._cfg()
        self.assertEqual(_declared_start_hours(cfg, SUN)["new-start-followup"], 13)
        self.assertEqual(_declared_start_hours(cfg, SAT)["new-start-followup"], 8)
        for d in (TUE, dt.date(2026, 9, 30), dt.date(2026, 10, 1), dt.date(2026, 10, 2)):
            self.assertEqual(_declared_start_hours(cfg, d)["new-start-followup"], 9)

    def test_monday_is_an_off_day_for_new_start_followup(self):
        """No mode of this report runs Monday: the daily reminder is Tue-Fri, the
        roll call/texts/nudge are Saturday, the checklist is Sunday."""
        off = _offday_standalone_ids(self._cfg(), MON)
        self.assertIn("new-start-followup", off)

    def test_it_stays_watched_every_day_it_really_runs(self):
        cfg = self._cfg()
        for d in (SAT, SUN, TUE, dt.date(2026, 9, 30), dt.date(2026, 10, 1),
                  dt.date(2026, 10, 2)):
            self.assertNotIn("new-start-followup", _offday_standalone_ids(cfg, d),
                             d.strftime("%a"))


if __name__ == "__main__":
    unittest.main()
