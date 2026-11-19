"""The 5am Octo Browser phone lookups: who gets looked up, where each
account lives, what the walk reads afterwards, when the tick fires, and that
the whole thing ships to the office computers.

Touches nothing outside a temp dir: no browser, no Octo, no relay.

    python -m unittest automations.oat_processing.test_octo_lookup
"""
from __future__ import annotations  # the office machines run Python 3.9

import ast
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.oat_processing import octo_lookup as OL
from automations.oat_processing import phone_lookups as PL

REPO = Path(__file__).resolve().parents[2]


def _tmp() -> Path:
    d = Path(tempfile.mkdtemp(prefix="octo-lookup-test-"))
    return d


PROFS = [
    {"title": "Peak Sales Strategies", "uuid": "a" * 32, "domains": ["peaksalesstrategiestx.com"]},
    {"title": "Riot Specialized Marketing", "uuid": "b" * 32, "domains": []},
    {"title": "VividReach - Active", "uuid": "c" * 32, "domains": []},
    {"title": "W Edge", "uuid": "d" * 32, "domains": ["wedgestrategies.com"]},
]


class WhichProfile(unittest.TestCase):
    def test_a_listed_domain_wins(self):
        self.assertEqual(OL.profile_for("team@peaksalesstrategiestx.com", profs=PROFS)["title"],
                         "Peak Sales Strategies")
        self.assertEqual(OL.profile_for("wedgestrategies.com", profs=PROFS)["title"], "W Edge")

    def test_a_title_that_reads_like_the_domain(self):
        self.assertEqual(OL.profile_for("jobs@riotspecializedmarketing.com", profs=PROFS)["title"],
                         "Riot Specialized Marketing")
        self.assertEqual(OL.profile_for("hr@vividreach.com", profs=PROFS)["title"],
                         "VividReach - Active")

    def test_nobody_is_guessed(self):
        self.assertIsNone(OL.profile_for("hr@nobody-knows.com", profs=PROFS))
        self.assertIsNone(OL.profile_for("Indeed", profs=PROFS))
        self.assertIsNone(OL.profile_for("", profs=PROFS))
        self.assertIsNone(OL.profile_for("w@edge.com", profs=PROFS), "a short stem matches nothing")

    def test_the_shipped_map_has_carlos(self):
        profs = OL.profiles("11580")
        self.assertGreaterEqual(len(profs), 17)
        self.assertEqual(len({p["uuid"] for p in profs}), len(profs), "two titles share a uuid")
        for p in profs:
            self.assertRegex(p["uuid"], r"^[0-9a-f]{32}$")
        self.assertEqual(OL.profile_for("hr@titanium-tx.com", "11580")["title"], "Titanium TX")
        self.assertIn("11580", OL.offices_with_profiles())

    def test_a_local_file_overrides_a_title(self):
        tmp = _tmp()
        (tmp / "octo-profiles.json").write_text(json.dumps({"11580": {"profiles": [
            {"title": "Titanium TX", "uuid": "f" * 32, "domains": ["titanium-tx.com", "titaniumtx.com"]}]}}))
        with mock.patch.object(OL, "_app_dir", return_value=tmp):
            pr = OL.profile_for("hr@titaniumtx.com", "11580")
        self.assertEqual(pr["uuid"], "f" * 32)
        self.assertEqual(OL.profile_for("hr@titanium-tx.com", "11580")["uuid"],
                         "ab337ac01a384c1b9d4a76661776aa6c", "the shipped one, without the file")


class WhoGetsLookedUp(unittest.TestCase):
    def setUp(self):
        self.tmp = _tmp()
        self.today = dt.date(2026, 11, 17)
        self.p = mock.patch.object(OL, "_out_dir", return_value=self.tmp)
        self.p.start()
        self.addCleanup(self.p.stop)

    def _snap(self, day, nophone, suffix=""):
        (self.tmp / ("oat-flagged-%s%s.json" % (day.isoformat(), suffix))).write_text(
            json.dumps({"nophone": nophone, "retext": [], "date": day.isoformat(), "at": "20:59"}))

    def test_the_newest_snapshot_this_week_minus_this_weeks_rows(self):
        self._snap(dt.date(2026, 11, 16), [
            {"name": "Edgar Hendricks", "account": "admin@revoltconsultingmarketing.com", "days": None},
            {"name": "Jose Gonzalez Toledo", "account": "hr@titanium-tx.com"},
            {"name": "Edgar Hendricks", "account": "admin@revoltconsultingmarketing.com"},  # twice
            "Bare Name",
            {"name": "someone@indeedemail.com", "account": "hr@titanium-tx.com"},           # unreadable
        ])
        self._snap(dt.date(2026, 11, 10), [{"name": "Old News", "account": "hr@titanium-tx.com"}])
        rows = [{"name": "Jose Gonzalez Toledo", "phone": "+52 55 1234 5678",
                 "account_email": "titanium-tx.com", "found_at": "2026-11-16"},
                {"name": "Bare Name", "phone": "817-555-0000", "account_email": "",
                 "found_at": "2026-11-01"}]                                              # too old
        items, info = OL.wanted("11580", self.today, csv_rows=rows)
        self.assertEqual([(i["name"], i["domain"]) for i in items],
                         [("Edgar Hendricks", "revoltconsultingmarketing.com"), ("Bare Name", "")])
        self.assertEqual(info["snapshot"], "oat-flagged-2026-11-16.json")
        self.assertEqual((info["listed"], info["skipped_recent"], info["unreadable"]), (3, 1, 1))

    def test_a_row_under_another_account_is_somebody_else(self):
        self._snap(dt.date(2026, 11, 16), [{"name": "Rogelio C", "account": "hr@titanium-tx.com"}])
        rows = [{"name": "Rogelio C", "phone": "682-555-0000",
                 "account_email": "info@fasttrack-strategies.com", "found_at": "2026-11-16"}]
        items, _ = OL.wanted("11580", self.today, csv_rows=rows)
        self.assertEqual(len(items), 1)

    def test_an_old_snapshot_is_history(self):
        self._snap(dt.date(2026, 11, 13), [{"name": "Stale", "account": "hr@titanium-tx.com"}])
        items, info = OL.wanted("11580", self.today, csv_rows=[])
        self.assertEqual(items, [])
        self.assertIsNone(info["snapshot"])

    def test_the_offices_own_suffixed_file_wins_and_anothers_is_ignored(self):
        self._snap(dt.date(2026, 11, 16), [{"name": "Plain", "account": "hr@titanium-tx.com"}])
        self._snap(dt.date(2026, 11, 16), [{"name": "Mine", "account": "hr@titanium-tx.com"}], "-11580")
        self._snap(dt.date(2026, 11, 17), [{"name": "Theirs", "account": "hr@titanium-tx.com"}], "-23467")
        items, _ = OL.wanted("11580", self.today, csv_rows=[])
        self.assertEqual([i["name"] for i in items], ["Mine"])


class WhatTheWalkReads(unittest.TestCase):
    def test_found_rows_land_in_the_walks_own_csv(self):
        tmp = _tmp()
        today = dt.date(2026, 11, 17)
        existing = [
            {"name": "Hand Typed", "phone": "817-555-1111", "account_email": "team@peaksalesstrategiestx.com"},
            {"name": "Last Week", "phone": "817-555-2222", "account_email": "titanium-tx.com",
             "found_at": "2026-11-09", "source": "octo-lookup"},
            {"name": "Edgar Hendricks", "phone": "000-000-0000", "account_email": "revoltconsultingmarketing.com",
             "found_at": "2026-11-16", "source": "octo-lookup"},
            {"name": "", "phone": "817-555-3333"},
        ]
        found = [{"name": "Edgar Hendricks", "phone": "754-555-4444", "domain": "revoltconsultingmarketing.com",
                  "shown_as": "Edgar H.", "office_id": "11580", "status": "found"},
                 {"name": "Jose Gonzalez Toledo", "phone": "+52 55 1234 5678", "domain": "titanium-tx.com",
                  "office_id": "11580", "status": "found"},
                 {"name": "Nobody", "phone": "", "domain": "titanium-tx.com", "status": "not_in_list"}]
        rows = OL.merge_rows(existing, found, today)
        names = {r["name"]: r for r in rows}
        self.assertEqual(set(names), {"Hand Typed", "Edgar Hendricks", "Jose Gonzalez Toledo"})
        self.assertEqual(names["Edgar Hendricks"]["phone"], "754-555-4444", "today's find replaces")
        self.assertEqual(names["Edgar Hendricks"]["indeed_name"], "Edgar H.")
        self.assertEqual(names["Hand Typed"]["found_at"], "", "a hand row is kept as it was")
        path = tmp / "phone-lookups.csv"
        OL.write_csv(path, rows)
        back = PL.rows_from_csv(path)
        got = {r["name"]: r for r in back}
        self.assertEqual(got["Edgar Hendricks"]["phone"], "7545554444")
        self.assertEqual(got["Edgar Hendricks"]["account"], "revoltconsultingmarketing.com")
        self.assertEqual(got["Edgar Hendricks"]["office_id"], "11580")
        self.assertIsNone(got["Jose Gonzalez Toledo"]["phone"], "a Mexico number is left for a person")
        self.assertEqual(got["Hand Typed"]["account"], "peaksalesstrategiestx.com")
        self.assertEqual(OL.CSV_NAME, PL.MANUAL_CSV)


class TheNumberOffThePopUp(unittest.TestCase):
    def test_us_numbers(self):
        self.assertEqual(OL.parse_phone("Call Edgar Hendricks\n+1 817 555 1234"), "817-555-1234")
        self.assertEqual(OL.parse_phone("(817) 555-1234"), "817-555-1234")
        self.assertEqual(OL.parse_phone("817.555.1234 mobile"), "817-555-1234")

    def test_a_mexico_number_is_kept_raw_for_a_person(self):
        self.assertEqual(OL.parse_phone("Call Jose\n+52 55 1234 5678"), "+52 55 1234 5678")

    def test_no_number(self):
        self.assertEqual(OL.parse_phone("Call Edgar Hendricks\nNo phone on file"), "")
        self.assertEqual(OL.parse_phone(""), "")


class WhenTheTickFires(unittest.TestCase):
    def setUp(self):
        self.tmp = _tmp()
        self.p = mock.patch.object(OL, "_app_dir", return_value=self.tmp)
        self.p.start()
        self.addCleanup(self.p.stop)

    def test_the_five_am_and_one_pm_slots(self):
        d = dt.datetime
        self.assertEqual(OL.slot_now(d(2026, 11, 17, 5, 0)), "am")
        self.assertEqual(OL.slot_now(d(2026, 11, 17, 6, 59)), "am")
        self.assertEqual(OL.slot_now(d(2026, 11, 17, 13, 0)), "pm")
        self.assertEqual(OL.slot_now(d(2026, 11, 17, 14, 59)), "pm")
        for hm in ((4, 59), (7, 0), (12, 59), (15, 0), (21, 0)):
            self.assertIsNone(OL.slot_now(d(2026, 11, 17, *hm)), hm)
            self.assertFalse(OL.in_window(d(2026, 11, 17, *hm)))
        self.assertTrue(OL.slot_has_lookups("am"))
        self.assertFalse(OL.slot_has_lookups("pm"))

    def test_once_per_slot_per_day_and_never_over_a_running_one(self):
        am, pm = dt.datetime(2026, 11, 17, 5, 2), dt.datetime(2026, 11, 17, 13, 4)
        self.assertEqual(OL.due(am), "am")
        OL._save_state({"last_day_am": "2026-11-17"})
        self.assertIsNone(OL.due(am), "the morning ran already")
        self.assertEqual(OL.due(pm), "pm", "the afternoon has not")
        OL._save_state({"last_day_am": "2026-11-17", "last_day_pm": "2026-11-17"})
        self.assertIsNone(OL.due(pm))
        OL._save_state({"last_day_am": "2026-11-16", "last_day_pm": "2026-11-16"})
        self.assertEqual(OL.due(am), "am")
        OL._lock_path().write_text(str(dt.datetime(2026, 11, 17, 5, 29).timestamp()))   # a run started at 5:29
        self.assertIsNone(OL.due(dt.datetime(2026, 11, 17, 5, 30)))
        OL._clear_lock()
        self.assertEqual(OL.due(am), "am")

    def test_the_kick_starts_its_own_process_and_marks_the_slot(self):
        with mock.patch.object(OL, "enabled", return_value=["11580"]), \
             mock.patch.object(OL, "due", return_value="am"), \
             mock.patch.object(OL.subprocess, "Popen") as popen:
            self.assertTrue(OL.maybe_kick(log=lambda m: None))
        argv = popen.call_args[0][0]
        self.assertEqual(argv[1:], ["-m", "automations.oat_processing.octo_lookup",
                                    "--scheduled", "--office", "11580"])
        self.assertEqual(OL._state().get("last_day_am"), dt.date.today().isoformat())

    def test_the_afternoon_kick_reads_billing_only(self):
        with mock.patch.object(OL, "enabled", return_value=["11580"]), \
             mock.patch.object(OL, "due", return_value="pm"), \
             mock.patch.object(OL.subprocess, "Popen") as popen:
            self.assertTrue(OL.maybe_kick(log=lambda m: None))
        argv = popen.call_args[0][0]
        self.assertEqual(argv[1:], ["-m", "automations.oat_processing.octo_lookup",
                                    "--scheduled", "--billing-only", "--office", "11580"])
        self.assertEqual(OL._state().get("last_day_pm"), dt.date.today().isoformat())
        self.assertIsNone(OL._state().get("last_day_am"))

    def test_nothing_on_a_machine_without_profiles_or_a_push(self):
        with mock.patch.object(OL, "enabled", return_value=[]), \
             mock.patch.object(OL.subprocess, "Popen") as popen:
            self.assertFalse(OL.maybe_kick(log=lambda m: None))
        popen.assert_not_called()

    def test_enabled_is_the_pushed_offices_with_profiles(self):
        from automations.icd_alerts import resume_push as RP
        with mock.patch.object(RP, "push_record", return_value={}):
            self.assertEqual(OL.enabled(), [])
        with mock.patch.object(RP, "push_record", return_value={"office_key": "carlos", "push_resumes": True}), \
             mock.patch.object(RP, "office_ids", return_value=("11580",)):
            self.assertEqual(OL.enabled(), ["11580"])
        with mock.patch.object(RP, "push_record", return_value={"office_key": "x", "push_resumes": True}), \
             mock.patch.object(RP, "office_ids", return_value=("99999",)):
            self.assertEqual(OL.enabled(), [])
        with mock.patch.dict(OL.os.environ, {"OAT_OCTO_LOOKUP": "0"}):
            self.assertEqual(OL.enabled(), [])


class TheTallyNeverCarriesANumber(unittest.TestCase):
    def test_no_enrollment_no_relay(self):
        lines = []
        with mock.patch.object(OL, "_push_office_key", return_value=""):
            OL._report("11580", {"found": [["A", "x.com"]], "missing": []}, log=lines.append)
        self.assertTrue(any("not filed" in l for l in lines))

    def test_the_quiet_row_is_names_and_statuses_only(self):
        from automations.icd_alerts import relay as R
        summary = {"office": "11580", "date": "2026-11-17", "at": "05:03", "found": [["A", "x.com"]],
                   "missing": [["B", "y.com", "not_in_list"]], "accounts": {"X": "1 of 1 found"},
                   "csv_rows": 3, "elapsed_min": 4.0, "phone": "817-555-1234"}
        with mock.patch.object(OL, "_push_office_key", return_value="carlos"), \
             mock.patch.object(R, "report_fault", return_value=True) as rf:
            OL._report("11580", summary, log=lambda m: None)
        stage, text, detail = rf.call_args[0][:3]
        self.assertEqual(stage, "probe-octo-lookup")
        self.assertIn("1 found, 1 not", text)
        self.assertNotIn("817", detail)
        self.assertIn('"A"', detail)

    def test_the_tally_says_what_ran_it(self):
        from automations.icd_alerts import relay as R
        summary = {"office": "11580", "found": [], "missing": [], "accounts": {}, "billing": {},
                   "billing_problems": [], "ran": {"argv": ["--scheduled", "--billing-only"],
                                                   "release": "2026.11.18.1", "lookups": False, "billing": True}}
        with mock.patch.object(OL, "_push_office_key", return_value="carlos"), \
             mock.patch.object(R, "report_fault", return_value=True) as rf:
            OL._report("11580", summary, log=lambda m: None)
        self.assertIn('"argv":["--scheduled","--billing-only"]', rf.call_args_list[0][0][2])


class EveryAccountsBilling(unittest.TestCase):
    CLEAN = ("Jobs\nAdd billing identifiers to your account\nView billing history\nUpdate payment method\n"
             "Manage billing details\nOpen and paused jobs\nAccount Manager - Full Time\nSponsored\n"
             "View performance report\n")

    def test_a_clean_all_jobs_page_has_no_alert(self):
        self.assertEqual(OL.billing_hits(self.CLEAN), [])

    def test_a_payment_alert_is_quoted_with_its_neighbours(self):
        page = self.CLEAN + "Your jobs are paused\nYour payment was declined. Update your payment method.\nFix now\n"
        hits = OL.billing_hits(page)
        self.assertEqual(len(hits), 1)
        self.assertIn("payment was declined", hits[0])
        self.assertIn("Your jobs are paused", hits[0])
        self.assertIn("Fix now", hits[0])

    def test_the_alert_is_a_loud_fault_to_the_office(self):
        from automations.icd_alerts import relay as R
        from automations.icd_alerts import post as P
        summary = {"office": "11580", "date": "2026-11-17", "at": "05:20", "found": [], "missing": [],
                   "accounts": {}, "billing": {"Peak Sales Strategies": "PROBLEM: Your payment was declined"},
                   "billing_problems": [["Peak Sales Strategies", "Your payment was declined"]]}
        with mock.patch.object(OL, "_push_office_key", return_value="carlos"), \
             mock.patch.object(R, "report_fault", return_value=True) as rf:
            OL._report("11580", summary, log=lambda m: None)
        stages = [c[0][0] for c in rf.call_args_list]
        self.assertEqual(stages, ["probe-octo-lookup", "octo-billing"])
        text = rf.call_args_list[1][0][1]
        self.assertIn("Peak Sales Strategies", text)
        self.assertIn("Your payment was declined", text)
        self.assertIn("send this to Carlos's Local Office", P.what_to_do("Carlos's Local Office", text))

    def test_a_clean_sweep_files_only_the_tally(self):
        from automations.icd_alerts import relay as R
        summary = {"office": "11580", "found": [], "missing": [], "accounts": {},
                   "billing": {"Peak Sales Strategies": "ok"}, "billing_problems": []}
        with mock.patch.object(OL, "_push_office_key", return_value="carlos"), \
             mock.patch.object(R, "report_fault", return_value=True) as rf:
            OL._report("11580", summary, log=lambda m: None)
        self.assertEqual([c[0][0] for c in rf.call_args_list], ["probe-octo-lookup"])
        self.assertIn('"Peak Sales Strategies":"ok"', rf.call_args_list[0][0][2])

    def test_the_cli_can_run_either_half_alone(self):
        with mock.patch.object(OL, "run", return_value={"result": "x"}) as run:
            OL.main(["--office", "11580", "--billing-only"])
            self.assertEqual((run.call_args[1]["billing"], run.call_args[1]["lookups"]), (True, False))
            OL.main(["--office", "11580", "--no-billing"])
            self.assertEqual((run.call_args[1]["billing"], run.call_args[1]["lookups"]), (False, True))


class TheWholeMorning(unittest.TestCase):
    """run() end to end with the browser, Octo and the relay faked: the plan
    (names first, then every other account for billing), the CSV, the
    results file, the tally. The 11/16 laptop sweep crashed after the last
    account on a line no unit touched -- this is that line's test."""

    def test_lookups_then_billing_for_every_account(self):
        tmp = _tmp()
        profs = [{"title": "Peak Sales Strategies", "uuid": "a" * 32, "domains": ["peaksalesstrategiestx.com"]},
                 {"title": "W Edge", "uuid": "d" * 32, "domains": ["wedgestrategies.com"]}]
        want = ([{"name": "Edgar Hendricks", "account": "team@peaksalesstrategiestx.com",
                  "domain": "peaksalesstrategiestx.com"}],
                {"snapshot": "oat-flagged-2026-11-16.json", "listed": 1, "skipped_recent": 0})
        order = []

        def fake_lookup(ws, items, log, deadline=None):
            order.append(("names", [i["name"] for i in items]))
            return [dict(items[0], status="found", phone="817-555-1234", shown_as="Edgar H")]

        def fake_billing(ws, title, shot_dir, log):
            order.append(("billing", title))
            return ({"title": title, "status": "problem", "hits": ["Action required | add payment information"],
                     "shot": "", "error": ""} if title == "W Edge"
                    else {"title": title, "status": "ok", "hits": [], "shot": "", "error": ""})

        reported = []
        with mock.patch.object(OL, "_out_dir", return_value=tmp), \
             mock.patch.object(OL, "_app_dir", return_value=tmp), \
             mock.patch.object(OL, "profiles", return_value=profs), \
             mock.patch.object(OL, "wanted", return_value=want), \
             mock.patch.object(OL, "ensure_octo", return_value=(True, "", False)), \
             mock.patch.object(OL, "octo_active", return_value=[]), \
             mock.patch.object(OL, "octo_start", return_value="ws://fake"), \
             mock.patch.object(OL, "octo_stop") as stop, \
             mock.patch.object(OL, "lookup_names", side_effect=fake_lookup), \
             mock.patch.object(OL, "check_billing", side_effect=fake_billing), \
             mock.patch.object(OL, "_report", side_effect=lambda *a, **k: reported.append((a, k))), \
             mock.patch.object(OL.time, "sleep"):
            s = OL.run("11580", scheduled=True)
            state_after = OL._state()          # read while _app_dir is still the temp dir
        self.assertEqual(order, [("names", ["Edgar Hendricks"]), ("billing", "Peak Sales Strategies"),
                                 ("billing", "W Edge")])
        self.assertEqual(stop.call_count, 2, "every profile started here is stopped")
        self.assertEqual(s["found"], [["Edgar Hendricks", "peaksalesstrategiestx.com"]])
        self.assertEqual(s["billing"], {"Peak Sales Strategies": "ok",
                                        "W Edge": "PROBLEM: Action required | add payment information"})
        self.assertEqual(s["billing_problems"], [["W Edge", "Action required | add payment information"]])
        self.assertEqual(s["accounts"], {"Peak Sales Strategies": "1 of 1 found", "W Edge": "billing only"})
        self.assertEqual(s["result"], "1 found, 0 not; billing: 2 account(s) read, 1 alert(s)")
        self.assertEqual(s["csv_rows"], 1)
        self.assertEqual((s["ran"]["lookups"], s["ran"]["billing"]), (True, True))
        self.assertIn("argv", s["ran"])
        self.assertIn("release", s["ran"])
        back = PL.rows_from_csv(tmp / "phone-lookups.csv")
        self.assertEqual((back[0]["name"], back[0]["phone"]), ("Edgar Hendricks", "8175551234"))
        self.assertTrue((tmp / ("octo-lookup-%s.json" % dt.date.today().isoformat())).exists())
        self.assertEqual(len(reported), 1)
        self.assertEqual(reported[0][1].get("loud", ""), "")
        self.assertEqual(state_after.get("last_result"), s["result"])
        self.assertFalse((tmp / "octo-lookup.lock").exists())


class OctoSaysWhy(unittest.TestCase):
    def test_a_refusal_comes_back_with_its_reason_and_is_not_retried(self):
        import io
        import urllib.error
        def err(*a, **k):      # a fresh error each call: its body can be read once
            raise urllib.error.HTTPError("http://127.0.0.1:58888/api/profiles/start", 409, "Conflict", {},
                                         io.BytesIO(b'{"error":"profile is running on another device"}'))
        lines = []
        with mock.patch.object(OL.urllib.request, "urlopen", side_effect=err), \
             mock.patch.object(OL.time, "sleep") as slept:
            d = OL._api("start", {"uuid": "a" * 32})
            self.assertEqual((d["http"], d["error"]), (409, "profile is running on another device"))
            self.assertIsNone(OL.octo_start("a" * 32, log=lines.append))
        self.assertEqual(len(lines), 1, "a refusal is said once, not three times")
        self.assertIn("another device", lines[0])
        slept.assert_not_called()

    def test_octos_already_started_means_another_computer(self):
        """11/16 22:20: Peak and Fast Track answered HTTP 400 profiles.already_started
        while this computer's active list showed neither -- Carlos had them open
        on another computer, paying the bills."""
        import io
        import urllib.error
        err = urllib.error.HTTPError("http://127.0.0.1:58888/api/profiles/start", 400, "Bad Request", {},
                                     io.BytesIO(b'{"code":"profiles.already_started","error":"Profile is already started","error_code":2}'))
        with mock.patch.object(OL.urllib.request, "urlopen", side_effect=err), \
             mock.patch.object(OL.time, "sleep"):
            self.assertIsNone(OL.octo_start("a" * 32, log=lambda m: None))
        self.assertEqual(OL.last_start_error(), "in use on another computer")

    def test_a_hiccup_is_retried(self):
        import urllib.error
        err = urllib.error.URLError("connection reset")
        lines = []
        with mock.patch.object(OL.urllib.request, "urlopen", side_effect=err), \
             mock.patch.object(OL.time, "sleep"):
            self.assertIsNone(OL.octo_start("a" * 32, log=lines.append))
        self.assertEqual(len(lines), OL.OCTO_START_TRIES)


class TheBillingMail(unittest.TestCase):
    ROWS = [{"subject": "Payment declined: Update your billing information", "when": "Wed, Nov 18, 2026, 7:05 PM"},
            {"subject": "We received your payment of $533.37", "when": "Tue, Nov 17, 2026, 7:35 PM"},
            {"subject": "Payment declined: Update your billing information", "when": "Mon, Nov 16, 2026, 7:33 PM"},
            {"subject": "Your Customer Service & Sales - AT&T job is live on Indeed", "when": "Tue, Nov 17, 2026, 2:25 PM"},
            {"subject": "Action required to make your job visible on Indeed", "when": "Thu, Nov 19, 2026, 9:14 AM"},
            {"subject": "[Action required] New application for AT&T Wireless Associate", "when": "Thu, Nov 19, 2026, 11:10 AM"},
            {"subject": "We received your payment of $77.74", "when": "Nov 1, 2026, 9:27 PM"}]

    def test_newest_of_each_kind(self):
        t = OL.mail_times(self.ROWS)
        self.assertEqual(t, {"declined": "2026-11-18 19:05", "paid": "2026-11-17 19:35", "live": "2026-11-19 09:14"})

    def test_unreadable_dates_are_skipped(self):
        self.assertEqual(OL.mail_times([{"subject": "Payment declined", "when": "7:05 PM"}]), {})
        self.assertIsNone(OL._mail_when("yesterday"))

    def test_the_tally_carries_the_mail_times(self):
        from automations.icd_alerts import relay as R
        summary = {"office": "11580", "found": [], "missing": [], "accounts": {}, "billing": {"X": "ok"},
                   "billing_problems": [], "billing_mail": {"X": {"declined": "2026-11-18 19:05", "signed_in": True}}}
        with mock.patch.object(OL, "_push_office_key", return_value="carlos"), \
             mock.patch.object(R, "report_fault", return_value=True) as rf:
            OL._report("11580", summary, log=lambda m: None)
        self.assertIn('"billing_mail":{"X":{"declined":"2026-11-18 19:05"', rf.call_args_list[0][0][2])


class ItShips(unittest.TestCase):
    def test_both_files_are_in_both_lists(self):
        from automations.icd_alerts.package import AGENT_FILES
        listed = (REPO / "automations/icd_alerts/agent_files.txt").read_text()
        for rel in ("automations/oat_processing/octo_lookup.py",
                    "automations/oat_processing/octo_profiles.json"):
            self.assertIn(rel, AGENT_FILES)
            self.assertIn(rel + "\n", listed)
            self.assertTrue((REPO / rel).exists())

    def test_the_module_reaches_for_nothing_an_office_machine_lacks(self):
        tree = ast.parse((REPO / "automations/oat_processing/octo_lookup.py").read_text())
        top = [n.module for n in tree.body if isinstance(n, ast.ImportFrom) and n.module]
        self.assertEqual([m for m in top if m.startswith("automations")], [])
        lazy = {n.module for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("automations")}
        self.assertEqual(lazy, {"automations.icd_alerts"}, "config, relay, resume_push: all shipped")

    def test_the_agents_tick_kicks_it_inside_a_try(self):
        src = (REPO / "automations/icd_alerts/run.py").read_text()
        i = src.index("octo_lookup.maybe_kick(log=_log)")
        self.assertIn("try:", src[i - 200:i])
        self.assertIn("except Exception", src[i:i + 200])

    def test_an_octo_fault_goes_to_the_office(self):
        from automations.icd_alerts import post as P
        line = P.what_to_do("Carlos's Local Office",
                            "Octo Browser is not installed on this computer, so the 5am phone "
                            "lookups did not run.")
        self.assertIn("send this to Carlos's Local Office", line)


if __name__ == "__main__":
    unittest.main()
