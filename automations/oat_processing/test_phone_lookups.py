"""Numbers a person looked up reach the walk, and the walk types them in. Run:

    PYTHONPATH=. .venv/bin/python -m unittest automations.oat_processing.test_phone_lookups -v

WHY THIS EXISTS (2026-11-16). Thirty of Carlos's applicants were on the no-number
to-do list; a person found every number in Indeed's Call pop-up, and there was
no way to hand them to the office computer that does the pushing -- it holds no
Google access, and it would have re-read the same resumes and found nothing
again. phone_lookups.py is that hand-over. These pin what must stay true:

  * the walk consults the list BEFORE the settled cache can skip the applicant
    (the cache is exactly why the number was looked up);
  * a number is typed in and sent the same way a resume number is, and the row
    is marked sent; a refused send marks the row and keeps the number;
  * a number that is not ten digits is never typed in and nobody is removed;
  * an office only ever gets its own rows; a relay that has not been redeployed,
    or is unreachable, costs nothing (last pull, or no list);
  * the shipped module imports nothing an office machine lacks, and the drop
    tool (our side) never ships.

Touches nothing outside a temp dir: no browser, no relay, no Sheet.
"""
from __future__ import annotations  # Lucy 2 / the office machines run Python 3.9

import ast
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.oat_processing import phone_lookups as PL
from automations.oat_processing import run

REPO = Path(__file__).resolve().parents[2]

CSV_HEAD = "account_email,account,name,indeed_name,phone,email,source\n"
CSV_ROWS = (
    'team@peaksalesstrategiestx.com,Peak Sales Strategies,Karina Escalera,'
    'Karina Escalera,469-569-5144,escalera.karina@yahoo.com,"resume header"\n'
    'team@peaksalesstrategiestx.com,Peak Sales Strategies,Genesis Lee-Chin,'
    'Genesis Lee-Chin,754-274-3233,,Indeed Call pop-up\n'
    'hr@titanium-tx.com,Titanium TX,Jose Gonzalez Toledo,Jose Andrés Gonzalez Toledo,'
    '+52 55 8233 5205,josegonzalez1im2@gmail.com,"Indeed Call pop-up (Mexico number)"\n'
    'info@ironsalesteam.com,Iron Sales Team,Harold Vivaa,Harold Vivaa,'
    '1 (214) 541-5077,info@ironsalesteam.com,Indeed Call pop-up\n'
    'info@ironsalesteam.com,Iron Sales Team,No Number,No Number,,,blank phone is skipped\n'
)


def _tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="oat-lookups-"))


def _reset_module(tmp: Path, *, enrolled=True):
    """Point every path the module touches at a scratch dir; no relay."""
    PL.reset()
    patches = [
        mock.patch.object(PL, "_cache_path", lambda: tmp / "cache.json"),
        mock.patch.object(PL, "_csv_path", lambda: tmp / "phone-lookups.csv"),
        mock.patch.object(PL, "_sent_path", lambda: tmp / "sent.jsonl"),
        mock.patch.object(PL, "_enrollment",
                          lambda: {"office_key": "carlos"} if enrolled else {}),
        mock.patch.dict(os.environ, {"OAT_NO_PHONE_LOOKUPS": ""}),
    ]
    for p in patches:
        p.start()
    return patches


RELAY_ROWS = [
    {"row": 2, "office_id": "11580", "name": "Karina Escalera",
     "account": "peaksalesstrategiestx.com", "phone": "469-569-5144"},
    {"row": 3, "office_id": "", "name": "Genesis Lee-Chin",
     "account": "team@peaksalesstrategiestx.com", "phone": "754-274-3233"},
    {"row": 4, "office_id": "11580", "name": "Jose Gonzalez Toledo",
     "account": "hr@titanium-tx.com", "phone": "+52 55 8233 5205"},
    {"row": 5, "office_id": "23467", "name": "Someone Elses", "account": "", "phone": "2145551212"},
]


class Shapes(unittest.TestCase):
    def test_a_name_folds_like_the_walks_allowlist(self):
        self.assertEqual(PL.fold("Genesis Lee-Chin"), "genesis lee chin")
        self.assertEqual(PL.fold("  José Andrés  GONZALEZ "), "jose andres gonzalez")
        self.assertEqual(PL.fold("Willy Jean - Felix"), PL.fold("Willy Jean-Felix"))
        self.assertEqual(PL.fold(None), "")

    def test_an_account_is_its_domain_or_nothing(self):
        self.assertEqual(PL.domain("team@peaksalesstrategiestx.com"), "peaksalesstrategiestx.com")
        self.assertEqual(PL.domain("PeakSalesStrategiesTX.com"), "peaksalesstrategiestx.com")
        self.assertEqual(PL.domain("Peak Sales Strategies"), "")
        self.assertEqual(PL.domain("Indeed"), "")
        self.assertEqual(PL.domain(""), "")

    def test_only_ten_us_digits_are_ever_typed(self):
        self.assertEqual(PL.digits10("469-569-5144"), "4695695144")
        self.assertEqual(PL.digits10("1 (214) 541-5077"), "2145415077")
        self.assertEqual(PL.digits10("+1 214 555 1212"), "2145551212")
        self.assertIsNone(PL.digits10("+52 55 8233 5205"), "a Mexico number is not typed in")
        self.assertIsNone(PL.digits10("555-1212"))
        self.assertIsNone(PL.digits10(""))


class TheCsv(unittest.TestCase):
    def test_the_lookup_sessions_file_reads_as_is(self):
        tmp = _tmp()
        p = tmp / "no-phone-lookups.csv"
        p.write_text(CSV_HEAD + CSV_ROWS, encoding="utf-8")
        rows = PL.rows_from_csv(p)
        self.assertEqual([r["name"] for r in rows],
                         ["Karina Escalera", "Genesis Lee-Chin", "Jose Gonzalez Toledo",
                          "Harold Vivaa"], "the blank-phone row is skipped")
        self.assertEqual(rows[0]["account"], "peaksalesstrategiestx.com")
        self.assertEqual(rows[0]["phone"], "4695695144")
        self.assertEqual(rows[3]["phone"], "2145415077")
        self.assertIsNone(rows[2]["phone"])
        self.assertEqual(rows[2]["raw_phone"], "+52 55 8233 5205")
        self.assertEqual(rows[2]["note"], "Jose Andrés Gonzalez Toledo")
        self.assertIsNone(rows[0]["row"], "a CSV row has nothing upstream to mark")


class Matching(unittest.TestCase):
    ROWS = [PL._row("Dana Reyes", "4695550001", "team@a.com"),
            PL._row("Dana Reyes", "4695550002", "jobs@b.com"),
            PL._row("Al Burke", "4695550003", ""),
            PL._row("Pat Lee", "4695550004", "x@c.com"),
            PL._row("Pat Lee", "4695550005", "")]

    def find(self, name, account):
        return PL.find(name, account, rows=self.ROWS)

    def test_name_and_account_pick_the_right_dana(self):
        self.assertEqual(self.find("Dana Reyes", "team@a.com")["phone"], "4695550001")
        self.assertEqual(self.find("dana  reyes", "JOBS@B.COM")["phone"], "4695550002")

    def test_the_same_name_under_another_account_is_somebody_else(self):
        self.assertIsNone(self.find("Dana Reyes", "hr@zzz.com"))

    def test_a_row_with_no_account_matches_any_account(self):
        self.assertEqual(self.find("Al Burke", "hr@zzz.com")["phone"], "4695550003")
        self.assertEqual(self.find("Pat Lee", "hr@zzz.com")["phone"], "4695550005",
                         "the exact account first, then the account-less row")

    def test_no_account_on_the_record_needs_one_row_of_that_name(self):
        self.assertEqual(self.find("Al Burke", "")["phone"], "4695550003")
        self.assertIsNone(self.find("Dana Reyes", ""), "two Danas: not guessing")
        self.assertIsNone(self.find("", "team@a.com"))
        self.assertIsNone(self.find("Nobody Here", "team@a.com"))


class Loading(unittest.TestCase):
    def setUp(self):
        self.tmp = _tmp()
        self.patches = _reset_module(self.tmp)
        self.lines = []
        PL.set_logger(self.lines.append)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        PL.reset()
        PL.set_logger(print)

    def test_the_relay_is_asked_for_this_office_only_and_the_pull_is_cached(self):
        calls = []

        def fake_call(body):
            calls.append(body)
            return {"ok": True, "lookups": RELAY_ROWS}
        with mock.patch.object(PL, "_call", fake_call):
            rows = PL.load("11580")
        self.assertEqual(calls, [{"phone_lookups": {"office_id": "11580"}}])
        self.assertEqual([r["name"] for r in rows],
                         ["Karina Escalera", "Genesis Lee-Chin", "Jose Gonzalez Toledo"],
                         "a row for another office id never comes back; a blank id is everyone's")
        self.assertEqual(rows[0]["phone"], "4695695144")
        self.assertEqual(rows[1]["account"], "peaksalesstrategiestx.com")
        self.assertIsNone(rows[2]["phone"])
        cached = json.loads((self.tmp / "cache.json").read_text())
        self.assertEqual(len(cached["rows"]), 4, "the pull is cached as it came")
        self.assertTrue(any("3 number(s) waiting for office 11580 (relay)" in l
                            and "1 not ten digits" in l for l in self.lines), self.lines)

    def test_a_relay_not_redeployed_yet_means_the_last_pull(self):
        with mock.patch.object(PL, "_call", lambda body: {"ok": True, "lookups": RELAY_ROWS}):
            PL.load("11580")
        PL.reset()
        with mock.patch.object(PL, "_call", lambda body: {"ok": False, "error": "bad day"}):
            rows = PL.load("11580")
        self.assertEqual(len(rows), 3)
        self.assertEqual(PL._LOADED["source"], "cache")
        self.assertTrue(any("does not take phone lookups yet" in l for l in self.lines))

    def test_a_relay_that_does_not_answer_means_the_last_pull(self):
        with mock.patch.object(PL, "_call", lambda body: {"ok": True, "lookups": RELAY_ROWS}):
            PL.load("11580")
        PL.reset()

        def boom(body):
            raise OSError("offline")
        with mock.patch.object(PL, "_call", boom):
            rows = PL.load("11580")
        self.assertEqual(len(rows), 3)
        self.assertTrue(any("relay did not answer" in l for l in self.lines))

    def test_an_old_pull_is_not_a_list(self):
        (self.tmp / "cache.json").write_text(json.dumps({
            "at": (dt.datetime.now() - dt.timedelta(days=4)).isoformat(timespec="seconds"),
            "rows": [PL._row("Dana Reyes", "4695550001")]}))

        def boom(body):
            raise OSError("offline")
        with mock.patch.object(PL, "_call", boom):
            self.assertEqual(PL.load("11580"), [])

    def test_a_hand_run_reads_its_own_csv(self):
        for p in self.patches:
            p.stop()
        self.patches = _reset_module(self.tmp, enrolled=False)
        (self.tmp / "phone-lookups.csv").write_text(CSV_HEAD + CSV_ROWS, encoding="utf-8")
        with mock.patch.object(PL, "_call", side_effect=AssertionError("no relay here")):
            rows = PL.load("11580")
        self.assertEqual(len(rows), 4)
        self.assertEqual(PL._LOADED["source"], "output/phone-lookups.csv")

    def test_the_off_switch_reads_as_no_list(self):
        with mock.patch.dict(os.environ, {"OAT_NO_PHONE_LOOKUPS": "1"}), \
                mock.patch.object(PL, "_call", side_effect=AssertionError("must not ask")):
            self.assertEqual(PL.load("11580"), [])
            self.assertIsNone(PL.find("Karina Escalera", "team@peaksalesstrategiestx.com", "11580"))

    def test_one_process_walking_two_offices_reloads_per_office(self):
        asked = []

        def fake_call(body):
            asked.append(body["phone_lookups"]["office_id"])
            return {"ok": True, "lookups": RELAY_ROWS}
        with mock.patch.object(PL, "_call", fake_call):
            PL.load("11580")
            PL.load("11580")
            rows = PL.load("23467")
        self.assertEqual(asked, ["11580", "23467"], "read once per office, not per applicant")
        self.assertEqual([r["name"] for r in rows], ["Genesis Lee-Chin", "Someone Elses"])

    def test_not_enrolled_and_no_csv_is_quietly_nothing(self):
        for p in self.patches:
            p.stop()
        self.patches = _reset_module(self.tmp, enrolled=False)
        with mock.patch.object(PL, "_call", side_effect=AssertionError("no relay here")):
            self.assertEqual(PL.load("11580"), [])
        self.assertEqual(self.lines, [], "no list, no noise")


class Marking(unittest.TestCase):
    def setUp(self):
        self.tmp = _tmp()
        self.patches = _reset_module(self.tmp)
        PL.set_logger(lambda *a: None)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        PL.reset()
        PL.set_logger(print)

    def test_a_sent_row_is_reported_once_with_its_row_and_name(self):
        hit = PL._row("Karina Escalera", "4695695144", "team@x.com", "11580", row=2)
        calls = []

        def fake_call(body):
            calls.append(body)
            return {"ok": True, "marked": 1}
        with mock.patch.object(PL, "_call", fake_call):
            self.assertTrue(PL.mark(hit, "sent"))
            self.assertTrue(PL.mark(hit, "sent"))
        self.assertEqual(calls, [{"phone_lookups": {"sent": [
            {"row": 2, "name": "Karina Escalera", "status": "sent"}]}}])
        lines = (self.tmp / "sent.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["status"], "sent")

    def test_a_csv_row_has_nothing_upstream_but_is_still_remembered(self):
        hit = PL._row("Karina Escalera", "4695695144")
        with mock.patch.object(PL, "_call", side_effect=AssertionError("no row to mark")):
            self.assertFalse(PL.mark(hit, "sent"))
        self.assertIn("Karina", (self.tmp / "sent.jsonl").read_text())

    def test_a_lost_report_never_raises(self):
        hit = PL._row("Karina Escalera", "4695695144", row=2)

        def boom(body):
            raise OSError("offline")
        with mock.patch.object(PL, "_call", boom):
            self.assertFalse(PL.mark(hit, "sent"))
        with mock.patch.object(PL, "_call", lambda body: {"ok": True, "marked": 0}):
            self.assertFalse(PL.mark(hit, "no_button"))


class _Page:
    url = "https://applicantstream.com/index.cfm?p=604"

    def __init__(self):
        self.waits = 0

    def wait_for_timeout(self, _ms):
        self.waits += 1

    def evaluate(self, _js):
        return {"url": "p=604", "smsOpen": False, "hasSendToAI": True, "btns": []}


class TheWalk(unittest.TestCase):
    """flag_no_phone with the list in hand, no browser."""

    def setUp(self):
        tmp = _tmp()
        self.tmp = tmp
        run._NOPHONE_CHECKED = None
        run._NOPHONE_BLOCKED = None
        self.saved = {k: getattr(run, k) for k in (
            "_nophone_checked_path", "_nophone_blocked_path", "_nophone_settled_path",
            "_fill_phone_field", "do_send_ai", "_bring_front", "_close_sms_panel",
            "_persist_phone", "lookup_resume_phone", "_rd_mod", "_log")}
        run._nophone_checked_path = lambda: tmp / "checked.json"
        run._nophone_blocked_path = lambda: tmp / "blocked.json"
        run._nophone_settled_path = lambda: tmp / "settled.json"
        self.typed, self.sent, self.persisted, self.marked, self.lines = [], [], [], [], []
        run._fill_phone_field = lambda page, phone: (self.typed.append(phone), True)[1]
        run.do_send_ai = lambda page, a, live: (self.sent.append(a.first_name), self.outcome)[1]
        run._bring_front = lambda page: None
        run._close_sms_panel = lambda page: None
        run._persist_phone = lambda page, phone: (self.persisted.append(phone), True)[1]

        def no_read(page):
            raise AssertionError("the resume must not be read when a number was looked up")
        run.lookup_resume_phone = no_read

        class _Rd:
            @staticmethod
            def phone_from_attachment(page):
                raise AssertionError("the attachment must not be read either")
        run._rd_mod = lambda: _Rd
        run._log = self.lines.append
        self.outcome = "sent"
        self.cfg = (getattr(run.config, "AUTOMATE_PHONE_LOOKUP", False), run.config.OFFICE_ID)
        run.config.AUTOMATE_PHONE_LOOKUP = True
        run.config.OFFICE_ID = "11580"
        run.reset_cf_session()
        self.rows = [PL._row("Karina Escalera", "469-569-5144",
                             "team@peaksalesstrategiestx.com", "11580", row=2),
                     PL._row("Jose Gonzalez Toledo", "+52 55 8233 5205",
                             "hr@titanium-tx.com", "11580", row=4)]
        self.pl_patches = [
            mock.patch.object(PL, "load", lambda office_id=None, refresh=False: self.rows),
            mock.patch.object(PL, "_call", self._relay),
            mock.patch.object(PL, "_sent_path", lambda: tmp / "sent.jsonl"),
        ]
        for p in self.pl_patches:
            p.start()
        PL.reset()

    def _relay(self, body):
        self.marked.append(body["phone_lookups"]["sent"][0])
        return {"ok": True, "marked": 1}

    def tearDown(self):
        for p in self.pl_patches:
            p.stop()
        for k, v in self.saved.items():
            setattr(run, k, v)
        run.config.AUTOMATE_PHONE_LOOKUP, run.config.OFFICE_ID = self.cfg
        run._NOPHONE_CHECKED = None
        run._NOPHONE_BLOCKED = None
        run.reset_cf_session()
        PL.reset()
        PL.set_logger(print)

    def karina(self):
        return run.Applicant(first_name="Karina", last_name="Escalera",
                             account="team@peaksalesstrategiestx.com", email="k@x.com")

    def test_a_settled_applicant_is_sent_with_the_looked_up_number(self):
        a = self.karina()
        run._mark_nophone_checked(run._nophone_key(a), confirmed=True)
        self.assertIn(run._nophone_key(a), run._load_nophone_checked(), "settled: the resume had no number")
        out = run.flag_no_phone(_Page(), a, live=True)
        self.assertEqual(out, "sent")
        self.assertEqual(self.typed, ["4695695144"])
        self.assertEqual(self.sent, ["Karina"])
        self.assertEqual(self.marked, [{"row": 2, "name": "Karina Escalera", "status": "sent"}])
        self.assertEqual(self.persisted, [], "a landed send keeps nothing to save")
        self.assertTrue(any("looked-up phone 4695695144" in l and "filled + sending" in l
                            for l in self.lines), self.lines)

    def test_a_dry_run_types_nothing_and_says_what_it_would_do(self):
        a = self.karina()
        run._mark_nophone_checked(run._nophone_key(a), confirmed=True)
        out = run.flag_no_phone(_Page(), a, live=False)
        self.assertEqual(out, "flag_no_phone")
        self.assertEqual(self.typed, [])
        self.assertEqual(self.marked, [])
        self.assertTrue(any("[dry-run] would type the looked-up number 4695695144" in l
                            for l in self.lines), self.lines)

    def test_a_refused_send_marks_the_row_and_keeps_the_number(self):
        self.outcome = "no_button"
        out = run.flag_no_phone(_Page(), self.karina(), live=True)
        self.assertEqual(out, "no_button")
        self.assertEqual(self.marked[0]["status"], "no_button")
        self.assertEqual(self.persisted, ["4695695144"])

    def test_a_number_that_is_not_ten_digits_is_never_typed_and_nobody_is_removed(self):
        a = run.Applicant(first_name="Jose", last_name="Gonzalez Toledo",
                          account="hr@titanium-tx.com")
        run._mark_nophone_checked(run._nophone_key(a), confirmed=True)
        removed = []
        with mock.patch.object(run, "_perform_remove", lambda *x, **k: removed.append(x) or True):
            out = run.flag_no_phone(_Page(), a, live=True)
        self.assertEqual(out, "flag_no_phone")
        self.assertEqual(self.typed, [])
        self.assertEqual(removed, [])
        self.assertEqual(self.marked, [{"row": 4, "name": "Jose Gonzalez Toledo", "status": "bad_number"}])
        self.assertTrue(any("not a ten-digit US number" in l for l in self.lines), self.lines)

    def test_a_name_not_on_the_list_walks_exactly_as_before(self):
        a = run.Applicant(first_name="Nicole", last_name="Lucido", account="team@x.com")
        run._mark_nophone_checked(run._nophone_key(a), confirmed=True)
        out = run.flag_no_phone(_Page(), a, live=True)
        self.assertEqual(out, "flag_no_phone")
        self.assertEqual((self.typed, self.sent, self.marked), ([], [], []))
        self.assertTrue(any("already checked today" in l for l in self.lines))

    def test_the_same_name_under_another_account_is_left_alone(self):
        a = run.Applicant(first_name="Karina", last_name="Escalera", account="hr@other.com")
        run._mark_nophone_checked(run._nophone_key(a), confirmed=True)
        self.assertEqual(run.flag_no_phone(_Page(), a, live=True), "flag_no_phone")
        self.assertEqual(self.typed, [])

    def test_a_number_that_will_not_type_flags_as_before(self):
        run._fill_phone_field = lambda page, phone: False
        a = self.karina()
        run._mark_nophone_checked(run._nophone_key(a), confirmed=True)
        self.assertEqual(run.flag_no_phone(_Page(), a, live=True), "flag_no_phone")
        self.assertEqual(self.sent, [])
        self.assertEqual(self.marked[0]["status"], "fill_failed")

    def test_a_list_that_cannot_be_read_costs_nothing(self):
        def boom(*a, **k):
            raise RuntimeError("relay exploded")
        with mock.patch.object(PL, "find", boom):
            a = self.karina()
            run._mark_nophone_checked(run._nophone_key(a), confirmed=True)
            self.assertEqual(run.flag_no_phone(_Page(), a, live=True), "flag_no_phone")
        self.assertTrue(any("list unavailable (RuntimeError)" in l for l in self.lines))

    def test_the_consult_sits_before_the_settled_cache_in_the_source(self):
        import inspect
        src = inspect.getsource(run.flag_no_phone)
        self.assertLess(src.index("_looked_up_number(a)"),
                        src.index("already_checked = key in _load_nophone_checked()"))
        self.assertIn('_send_with_number(page, a, phone, live, "resume")', src,
                      "the resume path and the lookup path share one send")
        hunk = src[src.index("_looked_up_number(a)"):src.index("already_checked = key")]
        self.assertNotIn("_perform_remove", hunk)


class Shipping(unittest.TestCase):
    def test_the_module_ships_and_the_drop_tool_does_not(self):
        from automations.icd_alerts.package import AGENT_FILES
        self.assertIn("automations/oat_processing/phone_lookups.py", AGENT_FILES)
        self.assertNotIn("automations/oat_processing/phone_lookups_add.py", AGENT_FILES)
        listed = (REPO / "automations/icd_alerts/agent_files.txt").read_text()
        self.assertIn("automations/oat_processing/phone_lookups.py\n", listed)

    def test_the_shipped_module_reaches_for_nothing_an_office_machine_lacks(self):
        tree = ast.parse((REPO / "automations/oat_processing/phone_lookups.py").read_text())
        top = [n.module for n in tree.body if isinstance(n, ast.ImportFrom) and n.module]
        self.assertEqual([m for m in top if m.startswith("automations")], [])
        lazy = {n.module for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("automations")}
        self.assertEqual(lazy, {"automations.icd_alerts"}, "relay + resume_push only, both shipped")


class TheDropTool(unittest.TestCase):
    def test_the_csv_becomes_rows_the_relay_takes(self):
        from automations.oat_processing import phone_lookups_add as ADD
        tmp = _tmp()
        p = tmp / "lookups.csv"
        p.write_text(CSV_HEAD + CSV_ROWS, encoding="utf-8")
        rows = ADD.payload(PL.rows_from_csv(p), "11580")
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0], {"name": "Karina Escalera", "account": "peaksalesstrategiestx.com",
                                   "phone": "469-569-5144", "office_id": "11580", "note": ""})
        self.assertEqual(rows[2]["phone"], "+52 55 8233 5205", "sent as typed; the office side decides")

    def test_the_office_road_adds_for_its_own_office_only(self):
        from automations.oat_processing import phone_lookups_add as ADD
        from automations.office_admin import relay_client as RC
        calls = []

        def fake_call(office, extra):
            calls.append((office, extra))
            return {"ok": True, "added": 2, "skipped": 1}
        with mock.patch.object(RC, "configured", lambda o: o == "carlos"), \
                mock.patch.object(RC, "_call", fake_call):
            out = ADD.add("Carlos", [{"name": "A B", "phone": "1", "account": "", "office_id": "11580", "note": ""}],
                          by="test", via="auto", log=lambda *a: None)
        self.assertEqual(out, {"added": 2, "skipped": 1, "via": "office"})
        self.assertEqual(calls[0][0], "carlos")
        self.assertEqual(calls[0][1], {"phone_lookups": {"add": [
            {"name": "A B", "phone": "1", "account": "", "office_id": "11580", "note": ""}]}})

    def test_no_road_says_so(self):
        from automations.oat_processing import phone_lookups_add as ADD
        from automations.office_admin import relay_client as RC
        with mock.patch.object(RC, "configured", lambda o: False), \
                mock.patch.object(ADD, "admin_key", lambda: ""), \
                mock.patch.object(ADD, "add_via_sheet", side_effect=PermissionError("not shared")):
            with self.assertRaises(RuntimeError):
                ADD.add("carlos", [], via="auto", log=lambda *a: None)


if __name__ == "__main__":
    unittest.main()
