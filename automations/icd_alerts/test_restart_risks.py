"""Will an office's machine come back by itself? Pins the whole chain.

Carlos's Mac went quiet at 11:01 on 2026-09-30 and stayed dark all day. The
machine had been reporting whether it would survive a restart on every relay,
and the relay threw the answer away -- so nobody could say. These pin: the
machine sends the answers, the poster reads them, the daily machines post
names them, and the quiet notice says when a dark machine was already known.

No network: the workbook is a fake, Slack is never called.
"""
import datetime as dt
import json
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import finish_setup, post as P, relay, stay_awake

DAY = dt.date(2026, 10, 1)


class _Sheet:
    def __init__(self, rows):
        self._rows = rows

    def get_all_values(self):
        return self._rows


class _Book:
    def __init__(self, relay_rows=(), knock_rows=()):
        self.tabs = {
            P.RELAY_TAB: [["Office", "Day"] + [""] * 9] + list(relay_rows),
            P.KNOCKS_TAB: [["Office", "Day"] + [""] * 8] + list(knock_rows),
        }

    def worksheet(self, name):
        return _Sheet(self.tabs[name])


def relay_row(office, day, machines):
    row = [office, day] + [""] * 9
    row[P.COL_MACHINES] = json.dumps(machines)
    return row


def knock_row(office, day, machines):
    row = [office, day] + [""] * 8
    row[P.KN_MACHINES] = json.dumps(machines)
    return row


class _Office:
    def __init__(self, key):
        self.key = key


def _risks(book, active=("carlos", "kash", "cyrus")):
    with mock.patch.object(P.O, "active",
                           return_value=[_Office(k) for k in active]):
        return P.restart_risks(DAY, book=book)


class RestartRisksTest(unittest.TestCase):
    def test_a_machine_that_stops_at_the_login_screen_is_named(self):
        book = _Book(knock_rows=[knock_row("carlos", "2026-10-01", {
            "a1": {"name": "Mac", "starts_itself": False,
                   "never_sleeps": True}})])
        got = _risks(book)
        self.assertEqual([(r["office"], r["why"]) for r in got],
                         [("carlos", ["restart"])])

    def test_sleep_and_power_are_their_own_reasons(self):
        book = _Book(knock_rows=[knock_row("kash", "2026-10-01", {
            "b1": {"name": "iMac", "starts_itself": True,
                   "never_sleeps": True, "sleep_off": False,
                   "powers_back_on": False}})])
        self.assertEqual(_risks(book)[0]["why"], ["sleep", "power"])

    def test_unknown_is_never_a_risk(self):
        """An agent too old to answer must not read as one that answered no."""
        book = _Book(knock_rows=[knock_row("carlos", "2026-10-01", {
            "a1": {"name": "Mac", "desktop": True, "never_sleeps": True}})])
        self.assertEqual(_risks(book), [])

    def test_the_newest_answer_wins(self):
        """Fixed yesterday -> off the list today, not stuck on last week."""
        book = _Book(knock_rows=[
            knock_row("carlos", "2026-09-30", {"a1": {"starts_itself": False}}),
            knock_row("carlos", "2026-10-01", {"a1": {"starts_itself": True}}),
        ])
        self.assertEqual(_risks(book), [])

    def test_both_tabs_merge_on_the_same_day(self):
        """The relay tab may carry only a name; the knocks tab the answer."""
        book = _Book(
            relay_rows=[relay_row("carlos", "2026-10-01",
                                  {"a1": {"name": "Mac", "desktop": True}})],
            knock_rows=[knock_row("carlos", "2026-10-01",
                                  {"a1": {"starts_itself": False}})])
        got = _risks(book)
        self.assertEqual(got[0]["name"], "Mac")
        self.assertEqual(got[0]["why"], ["restart"])

    def test_old_rows_and_retired_offices_are_ignored(self):
        book = _Book(knock_rows=[
            knock_row("carlos", "2026-09-20", {"a1": {"starts_itself": False}}),
            knock_row("gone", "2026-10-01", {"z": {"starts_itself": False}}),
        ])
        self.assertEqual(_risks(book), [])

    def test_the_accepted_laptop_is_not_nagged_about_sleep(self):
        book = _Book(knock_rows=[knock_row("cyrus", "2026-10-01", {
            "c1": {"never_sleeps": False, "starts_itself": True}})])
        self.assertIn("cyrus", P.LAPTOP_ACKNOWLEDGED)
        self.assertEqual(_risks(book), [])


class TheDailyMachinesPostNamesThem(unittest.TestCase):
    def test_restart_risk_is_said_with_the_fix(self):
        with mock.patch.object(P, "laptop_offices", return_value=[]), \
                mock.patch.object(P, "restart_risks", return_value=[
                    {"office": "carlos", "id": "a1", "name": "Mac",
                     "why": ["restart", "power"]}]):
            out = P.warn_machine_facts(send=False, log=lambda *_: None)
        text = "\n".join(out)
        self.assertIn("Won't come back after a restart", text)
        self.assertIn("Stays off after a power cut", text)
        self.assertIn("carlos — Mac", text)
        self.assertIn("setup.html", text)
        self.assertNotIn("startup.html", text,
                         "startup.html installs only the boot job")

    def test_a_broken_read_never_costs_the_laptop_line(self):
        with mock.patch.object(P, "laptop_offices", return_value=[
                    {"office": "x", "name": "MacBook Air"}]), \
                mock.patch.object(P, "restart_risks",
                                  side_effect=RuntimeError("429")):
            out = P.warn_machine_facts(send=False, log=lambda *_: None)
        self.assertTrue(any("MacBook Air" in l for l in out))


class TheQuietNoticeSaysItWasKnown(unittest.TestCase):
    def test_risk_note_names_every_reason(self):
        note = P._risk_note({"restart", "power"})
        self.assertIn("login screen", note)
        self.assertIn("power cut", note)
        self.assertIn("setup.html", note)


class TheMachineSendsTheAnswers(unittest.TestCase):
    def test_not_a_mac_means_unknown_never_false(self):
        with mock.patch.object(relay.platform, "system", return_value="Windows"):
            facts = relay._recovery_facts()
        self.assertEqual(facts, {"starts_itself": None, "sleep_off": None,
                                 "powers_back_on": None})

    def test_a_working_boot_job_counts_without_auto_login(self):
        """We never turn auto-login on; the boot job is the answer."""
        from automations.icd_alerts import boot_schedule
        with mock.patch.object(relay.platform, "system", return_value="Darwin"), \
                mock.patch.object(boot_schedule, "loaded", return_value=True), \
                mock.patch.object(boot_schedule, "runs_the_right_python",
                                  return_value=True), \
                mock.patch.object(relay, "_auto_login", return_value=False):
            self.assertTrue(relay._starts_itself())

    def test_a_loaded_but_broken_boot_job_does_not_count(self):
        from automations.icd_alerts import boot_schedule
        with mock.patch.object(relay.platform, "system", return_value="Darwin"), \
                mock.patch.object(boot_schedule, "loaded", return_value=True), \
                mock.patch.object(boot_schedule, "runs_the_right_python",
                                  return_value=False), \
                mock.patch.object(relay, "_auto_login", return_value=False):
            self.assertFalse(relay._starts_itself())

    def test_powers_back_on_reads_autorestart(self):
        out = mock.Mock(stdout=b"AC Power:\n sleep 0\n autorestart 1\n")
        with mock.patch.object(stay_awake.platform, "system",
                               return_value="Darwin"), \
                mock.patch.object(stay_awake, "_run", return_value=out):
            self.assertTrue(stay_awake.powers_back_on())
        out = mock.Mock(stdout=b"AC Power:\n sleep 0\n")
        with mock.patch.object(stay_awake.platform, "system",
                               return_value="Darwin"), \
                mock.patch.object(stay_awake, "_run", return_value=out):
            self.assertIsNone(stay_awake.powers_back_on(),
                              "a Mac that does not list it cannot say no")


class TheRelayKeepsThem(unittest.TestCase):
    """The .gs is deployed by hand, so its source is the only thing to pin."""

    def test_the_relay_script_stores_every_fact(self):
        gs = (Path(__file__).resolve().parents[2]
              / "resources" / "icd-alerts-relay.gs").read_text()
        for key in ("starts_itself", "sleep_off", "powers_back_on",
                    "auto_login", "filevault"):
            self.assertIn("body." + key, gs, key)
        self.assertIn("_restartFacts(body)", gs)


class OneLineFixesIt(unittest.TestCase):
    def test_finish_setup_has_the_sleep_step(self):
        import inspect
        src = inspect.getsource(finish_setup.run)
        self.assertIn("_never_sleeps", src)

    def test_sleep_step_asks_only_when_the_answer_is_no(self):
        with mock.patch("platform.system", return_value="Darwin"), \
                mock.patch.object(stay_awake, "pmset_ok", return_value=True), \
                mock.patch.object(stay_awake, "powers_back_on",
                                  return_value=True), \
                mock.patch.object(stay_awake, "apply_pmset") as ask:
            self.assertEqual(finish_setup._never_sleeps(lambda *_: None),
                             "already done")
        ask.assert_not_called()


if __name__ == "__main__":
    unittest.main()
