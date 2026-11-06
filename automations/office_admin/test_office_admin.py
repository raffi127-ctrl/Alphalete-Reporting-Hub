"""Office admin page: logins, request rows, send decisions, office jobs.

    python -m unittest automations.office_admin.test_office_admin

Offline: no Sheets, no relay, no browser.
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.office_admin import accounts as A
from automations.office_admin import config as C
from automations.office_admin import sheets as S
from automations.office_admin import actions as W


class Passwords(unittest.TestCase):
    def test_round_trip(self):
        h = A.hash_password("correct horse", iterations=1000)
        self.assertTrue(A.check_password("correct horse", h))
        self.assertFalse(A.check_password("wrong", h))

    def test_never_stores_the_password(self):
        self.assertNotIn("hunter22", A.hash_password("hunter22", iterations=1000))

    def test_garbage_hash_is_a_no(self):
        self.assertFalse(A.check_password("x", ""))
        self.assertFalse(A.check_password("x", "plain-text"))


class Login(unittest.TestCase):
    def _admins(self, active="Yes", office="omar"):
        return [{"Username": "Omar-Admin", "Password Hash": A.hash_password("pw123456", iterations=1000),
                 "Office Key": office, "Active": active, "_row": 2}]

    def test_good_login(self):
        a = A.authenticate(self._admins(), " omar-admin ", "pw123456")
        self.assertEqual(a["Office Key"], "omar")

    def test_wrong_password(self):
        self.assertIsNone(A.authenticate(self._admins(), "omar-admin", "nope"))

    def test_disabled_login(self):
        self.assertIsNone(A.authenticate(self._admins(active="No"), "omar-admin", "pw123456"))

    def test_office_not_set_up(self):
        self.assertIsNone(A.authenticate(self._admins(office="nobody"), "omar-admin", "pw123456"))

    def test_unknown_user(self):
        self.assertIsNone(A.authenticate(self._admins(), "someone", "pw123456"))


class Records(unittest.TestCase):
    def test_by_header_not_index(self):
        vals = [["Status", "Request ID"], ["queued", "abc"]]
        r = S.records(vals)[0]
        self.assertEqual((r["Request ID"], r["Status"], r["_row"]), ("abc", "queued", 2))

    def test_col_letter(self):
        self.assertEqual([S.col_letter(n) for n in (1, 26, 27)], ["A", "Z", "AA"])


class Candidates(unittest.TestCase):
    def test_valid_people_needs_name_and_email(self):
        got = W.valid_people([{"first_name": "A", "last_name": "B", "email": "a@b.c"},
                              {"first_name": "A", "last_name": "", "email": "a@b.c"},
                              {"first_name": "A", "last_name": "B", "email": "none"},
                              "junk"])
        self.assertEqual(len(got), 1)


class JudgeJob(unittest.TestCase):
    def test_answered_sent_is_done(self):
        v = W.judge_job({"answered": True, "result": {"status": "sent"}}, 1)
        self.assertEqual(v["Status"], C.DONE)

    def test_answered_dry_is_done(self):
        v = W.judge_job({"answered": True, "result": {"status": "dry_run"}}, 1)
        self.assertEqual(v["Status"], C.DONE)

    def test_answered_error_is_failed(self):
        v = W.judge_job({"answered": True, "result": {"status": "error"}}, 1)
        self.assertEqual(v["Status"], C.FAILED)

    def test_still_queued_waits(self):
        self.assertIsNone(W.judge_job({"status": "queued"}, 500))

    def test_offered_never_answered_is_unconfirmed_not_resent(self):
        v = W.judge_job({"status": "offered"}, C.STALE_MINUTES + 1)
        self.assertEqual(v["Status"], C.FAILED)
        self.assertIn("UNCONFIRMED", v["Result"])
        self.assertIn("twice", v["Result"])

    def test_offered_recently_waits(self):
        self.assertIsNone(W.judge_job({"status": "offered"}, 5))


class FakeWs:
    """An in-memory 'Admin Requests' tab."""
    def __init__(self):
        self.values = [list(C.REQUESTS_HEADERS)]

    def get_all_values(self):
        return [list(r) for r in self.values]

    def append_row(self, row, value_input_option=None):
        self.values.append(list(row))

    def row_values(self, n):
        return list(self.values[n - 1])

    def batch_update(self, data, value_input_option=None):
        for d in data:
            a1 = d["range"]
            col = ord(a1[0]) - 64
            row = int(a1[1:])
            r = self.values[row - 1]
            r += [""] * (col - len(r))
            r[col - 1] = d["values"][0][0]


ADMIN = {"username": "omar-admin", "office": "omar", "name": "x"}
PEOPLE = [{"first_name": "Ana", "last_name": "Lopez", "email": "a@x.com"}]
LOC = {"country": "United States", "state": "Michigan", "city": "Dearborn"}


class SendGoesToTheOfficeComputer(unittest.TestCase):
    def test_send_logs_then_queues_on_the_relay(self):
        from automations.office_admin import actions
        ws = FakeWs()
        with mock.patch("automations.office_admin.relay_client.request_job",
                        return_value="job-1") as rq:
            jid = actions.send_bgc(ws, ADMIN, C.office("omar"), PEOPLE, LOC)
        self.assertEqual(jid, "job-1")
        _, kw = rq.call_args
        self.assertEqual(kw["mode"], "dry")                 # Omar starts dry
        self.assertEqual(rq.call_args[0][:2], ("omar", "bgc_send"))
        row = S.read_requests(ws)[0]
        self.assertEqual((row["Status"], row["Job ID"]), (C.AT_OFFICE, "job-1"))

    def test_relay_down_is_a_failed_row_not_a_lost_press(self):
        from automations.office_admin import actions, relay_client
        ws = FakeWs()
        with mock.patch("automations.office_admin.relay_client.request_job",
                        side_effect=relay_client.RelayError("down")):
            with self.assertRaises(relay_client.RelayError):
                actions.send_bgc(ws, ADMIN, C.office("omar"), PEOPLE, LOC)
        self.assertEqual(S.read_requests(ws)[0]["Status"], C.FAILED)

    def test_nobody_valid_is_refused_before_anything(self):
        from automations.office_admin import actions
        ws = FakeWs()
        with self.assertRaises(ValueError):
            actions.send_bgc(ws, ADMIN, C.office("omar"), [{"first_name": "A"}], LOC)
        self.assertEqual(S.read_requests(ws), [])

    def test_refresh_copies_the_answer(self):
        from automations.office_admin import actions
        ws = FakeWs()
        with mock.patch("automations.office_admin.relay_client.request_job", return_value="j"):
            actions.send_bgc(ws, ADMIN, C.office("omar"), PEOPLE, LOC)
        req = S.read_requests(ws)[0]
        ans = {"status": "dry_run", "answered": True, "result": {"status": "dry_run", "would_send": ["Ana Lopez"]}}
        with mock.patch("automations.office_admin.relay_client.job_status", return_value=ans):
            out = actions.refresh_send(ws, req)
        self.assertEqual(out["Status"], C.DONE)
        self.assertEqual(S.read_requests(ws)[0]["Status"], C.DONE)

    def test_refresh_waits_while_relay_unreachable(self):
        from automations.office_admin import actions, relay_client
        ws = FakeWs()
        with mock.patch("automations.office_admin.relay_client.request_job", return_value="j"):
            actions.send_bgc(ws, ADMIN, C.office("omar"), PEOPLE, LOC)
        req = S.read_requests(ws)[0]
        with mock.patch("automations.office_admin.relay_client.job_status",
                        side_effect=relay_client.RelayError("timeout")):
            out = actions.refresh_send(ws, req)
        self.assertEqual(out["Status"], C.AT_OFFICE)

    def test_find_reads_todays_calendar_offers(self):
        from automations.office_admin import actions
        import contextlib
        seen = {}

        @contextlib.contextmanager
        def fake_session():
            yield "app"

        def fake_read(app, office_id, day, log=print):
            seen.update(office=office_id, day=day)
            return PEOPLE
        with mock.patch("automations.office_admin.offered.read", fake_read):
            out = actions.find_bob(C.office("omar"), today=dt.date(2026, 11, 3), session=fake_session)
        self.assertEqual(seen, {"office": "24232", "day": dt.date(2026, 11, 3)})
        self.assertEqual(out, PEOPLE)


class OfferedYes(unittest.TestCase):
    """Megan 2026-11-03: Calendar -> SECOND INTERVIEWS -> Offer Position? = Yes."""
    def row(self, first, offer, section="SECOND INTERVIEWS", phone="945-393-4079"):
        return {"first": first, "last": "X", "phone": phone, "email": first + "@x.com",
                "offer": offer, "section": section}

    def test_only_yes_in_second_interviews(self):
        from automations.office_admin import offered as O
        got = O.offered_yes([self.row("Allen", "Yes"), self.row("Alexis", "No"),
                             self.row("Pending", ""), self.row("First", "Yes", "FIRST INTERVIEWS"),
                             self.row("Unknown", "Yes", "")])
        self.assertEqual([p["first_name"] for p in got], ["Allen"])
        self.assertEqual(got[0]["phone"], "9453934079")

    def test_same_person_twice_is_one(self):
        from automations.office_admin import offered as O
        self.assertEqual(len(O.offered_yes([self.row("Allen", "Yes"), self.row("Allen", "Yes")])), 1)

    def test_namesakes_with_different_phones_are_two(self):
        from automations.office_admin import offered as O
        got = O.offered_yes([self.row("Oscar", "Yes", phone="1"), self.row("Oscar", "Yes", phone="2")])
        self.assertEqual(len(got), 2)


class CalendarV2(unittest.TestCase):
    """ApplicantStream "version 2" calendar: one Name column, Offer Position
    inside the Show Up cell of the 2nd Interview tab (Megan 2026-11-03)."""
    def test_name_split(self):
        from automations.office_admin import offered as O
        self.assertEqual(O.split_name("Porter Osborne"), ("Porter", "Osborne"))
        self.assertEqual(O.split_name("Den Rhys Amiel Ramos"), ("Den", "Rhys Amiel Ramos"))
        self.assertEqual(O.split_name(""), ("", ""))

    def test_only_yes(self):
        from automations.office_admin import offered as O
        rows = [{"name": "Porter Osborne", "phone": "+1 (214) 809-5118", "email": "p@x.com", "offer": "Yes"},
                {"name": "Nicholas Stanley", "phone": "1", "email": "n@x.com", "offer": "No"},
                {"name": "Sadaf Rahmani", "phone": "2", "email": "s@x.com", "offer": ""}]
        got = O.v2_offered_yes(rows)
        self.assertEqual([(p["first_name"], p["phone"]) for p in got], [("Porter", "2148095118")])

    def test_showed_but_no_offer_control_refuses(self):
        from automations.office_admin import offered as O
        with self.assertRaises(RuntimeError):
            O.check_v2_rows([{"show": "Showed", "has_offer_control": False}])

    def test_only_no_shows_is_a_real_zero(self):
        from automations.office_admin import offered as O
        O.check_v2_rows([{"show": "Not Showed Change Status", "has_offer_control": False}])


class OfficeLocation(unittest.TestCase):
    """Sterling's form needs the owner's city + state (Megan 2026-11-03)."""
    def _ws(self):
        ws = FakeWs()
        ws.values = [list(C.SETTINGS_HEADERS)]
        return ws

    def test_save_then_read(self):
        ws = self._ws()
        S.save_office_location(ws, "omar", "Michigan", "  Dearborn ", "omar-admin")
        self.assertEqual(S.location_of(S.office_settings(ws, "omar")),
                         {"country": "United States", "state": "Michigan", "city": "Dearborn"})

    def test_change_replaces_the_row(self):
        ws = self._ws()
        S.save_office_location(ws, "omar", "Michigan", "Dearborn", "a")
        S.save_office_location(ws, "omar", "Texas", "Plano", "a")
        self.assertEqual(len(ws.values), 2)
        self.assertEqual(S.location_of(S.office_settings(ws, "omar"))["city"], "Plano")

    def test_bad_input_refused(self):
        ws = self._ws()
        with self.assertRaises(ValueError):
            S.save_office_location(ws, "omar", "Pick your state", "Dearborn", "a")
        with self.assertRaises(ValueError):
            S.save_office_location(ws, "omar", "Michigan", "  ", "a")

    def test_unset_office_has_no_location(self):
        self.assertEqual(S.location_of(S.office_settings(self._ws(), "omar")), {})

    def test_send_refused_without_location(self):
        from automations.office_admin import actions
        ws = FakeWs()
        with mock.patch("automations.office_admin.relay_client.request_job") as rq:
            with self.assertRaises(ValueError):
                actions.send_bgc(ws, ADMIN, C.office("omar"), PEOPLE, {})
        rq.assert_not_called()

    def test_location_rides_in_the_job(self):
        from automations.office_admin import actions
        ws = FakeWs()
        with mock.patch("automations.office_admin.relay_client.request_job", return_value="j") as rq:
            actions.send_bgc(ws, ADMIN, C.office("omar"), PEOPLE, LOC)
        self.assertEqual(rq.call_args[0][2]["location"], LOC)

    def test_office_computer_refuses_without_location(self):
        from automations.icd_alerts import sterling_send
        r = sterling_send.send_invites(PEOPLE, live=False)
        self.assertEqual(r["status"], "error")


class SterlingOrderPicks(unittest.TestCase):
    """Order Information picks (Megan 2026-11-03)."""
    def test_bill_code_is_the_one_real_option(self):
        from automations.icd_alerts import sterling_send as SS
        self.assertEqual(SS.pick_bill_code(["<select billcode>", "1658411"]), "1658411")

    def test_bill_code_none_or_many_stops(self):
        from automations.icd_alerts import sterling_send as SS
        with self.assertRaises(ValueError):
            SS.pick_bill_code(["<select billcode>"])
        with self.assertRaises(ValueError):
            SS.pick_bill_code(["<select billcode>", "1658411", "999"])

    def test_job_position_is_the_elite_one(self):
        from automations.icd_alerts import sterling_send as SS
        self.assertEqual(SS.pick_elite(["<select Job Title>", "Sterling - Basic", "Sterling - Elite", "Other"]),
                         "Sterling - Elite")
        self.assertEqual(SS.pick_elite(["<select Job Title>", "Sterling Basic", "Sterling Elite / Extra", "X"]),
                         "Sterling Elite / Extra")

    def test_screening_package_same_rule(self):
        from automations.icd_alerts import sterling_send as SS
        self.assertEqual(SS.pick_elite(["<Select a package>", "Sterling Elite / Extra", "Sterling Basic"]),
                         "Sterling Elite / Extra")

    def test_job_position_none_or_two_elite_stops(self):
        from automations.icd_alerts import sterling_send as SS
        with self.assertRaises(ValueError):
            SS.pick_elite(["<select Job Title>", "Sterling - Basic"])
        with self.assertRaises(ValueError):
            SS.pick_elite(["Sterling - Elite", "Sterling Elite / Extra"])

    def test_elite_picked_by_name(self):
        from automations.icd_alerts import sterling_send as SS
        opts = ["<Select a package>", "Sterling - Basic", "Sterling  -  Elite"]
        self.assertEqual(SS.pick_option(opts, SS.SCREENING_PACKAGE), "Sterling  -  Elite")
        with self.assertRaises(ValueError):
            SS.pick_option(["<select Job Title>", "Other"], SS.JOB_POSITION)


class SterlingBulkCsv(unittest.TestCase):
    """Client Hub bulk upload, headers off Sterling's own template."""
    def test_rows_and_header(self):
        from automations.icd_alerts import sterling_send as SS
        out = SS.build_csv([{"first_name": "Lincoln", "last_name": "Peterson", "email": "p@x.com"},
                            {"first_name": "Den Rhys", "last_name": "Amiel Ramos", "email": "d@x.com"}])
        self.assertEqual(out.splitlines(), ["First,Last,Email",
                                            "Lincoln,Peterson,p@x.com",
                                            "Den Rhys,Amiel Ramos,d@x.com"])

    def test_skips_incomplete_and_duplicate_emails(self):
        from automations.icd_alerts import sterling_send as SS
        out = SS.build_csv([{"first_name": "A", "last_name": "B", "email": "a@x.com"},
                            {"first_name": "A", "last_name": "B", "email": "A@X.com"},
                            {"first_name": "C", "last_name": "", "email": "c@x.com"},
                            {"first_name": "D", "last_name": "E", "email": "none"}])
        self.assertEqual(len(out.splitlines()), 2)

    def test_header_is_byte_for_byte_sterlings_template(self):
        from pathlib import Path
        from automations.icd_alerts import sterling_send as SS
        tpl = Path(__file__).resolve().parents[2] / "resources" / "sterling" / "client-hub-template.csv"
        self.assertTrue(SS.build_csv([]).encode("utf-8").startswith(tpl.read_bytes()))

    def test_found_count_must_match_before_send(self):
        from automations.icd_alerts import sterling_send as SS
        self.assertEqual(SS.found_count("Bulk candidates uploaded: 1 found"), 1)
        SS.check_found("Bulk candidates uploaded:  12 found", 12)
        with self.assertRaises(ValueError):
            SS.check_found("Bulk candidates uploaded: 11 found", 12)
        with self.assertRaises(ValueError):
            SS.check_found("Drag here or click to browse for a file", 1)

    def test_commas_in_names_are_quoted(self):
        from automations.icd_alerts import sterling_send as SS
        out = SS.build_csv([{"first_name": "Jr, Reggie", "last_name": "Mason", "email": "r@x.com"}])
        self.assertIn('"Jr, Reggie",Mason,r@x.com', out)


class ClientHubLocation(unittest.TestCase):
    """Client Hub Location box reads 'Plano, TX, USA' (Megan screenshot 11/04)."""
    def test_text_from_saved_location(self):
        from automations.icd_alerts import sterling_send as SS
        self.assertEqual(SS.location_text({"state": "Texas", "city": "Plano"}), "Plano, TX, USA")
        self.assertEqual(SS.location_text({"state": "Michigan", "city": " Dearborn "}), "Dearborn, MI, USA")

    def test_bad_state_stops(self):
        from automations.icd_alerts import sterling_send as SS
        with self.assertRaises(ValueError):
            SS.location_text({"state": "Tejas", "city": "Plano"})

    def test_matches_what_the_box_shows(self):
        from automations.icd_alerts import sterling_send as SS
        loc = {"state": "Texas", "city": "Plano"}
        self.assertTrue(SS.location_matches("Plano, TX, USA", loc))
        self.assertTrue(SS.location_matches("plano,tx", loc))
        self.assertFalse(SS.location_matches("Plano, IL, USA", loc))
        # exactly as the live suggestion list reads (11/04)
        self.assertTrue(SS.location_matches("Plano TX, USA", loc))
        self.assertFalse(SS.location_matches("Plano IL, USA", loc))
        self.assertEqual(SS.pick_location_suggestion(
            ["Plano IL, USA", "Plano TX, USA", "Planoles Spain", "Plano IA, USA"], loc), "Plano TX, USA")

    def test_suggestion_list_picks_the_right_state(self):
        from automations.icd_alerts import sterling_send as SS
        loc = {"state": "Texas", "city": "Plano"}
        got = SS.pick_location_suggestion(["Plano, IL, USA", "Plano, TX, USA", "Plano Pkwy, TX, USA"], loc)
        self.assertEqual(got, "Plano, TX, USA")
        with self.assertRaises(ValueError):
            SS.pick_location_suggestion(["Plano, IL, USA"], loc)

    def test_every_page_state_has_a_code(self):
        from automations.icd_alerts import sterling_send as SS
        self.assertEqual(set(C.US_STATES), set(SS.STATE_CODES))


class AlreadyDone(unittest.TestCase):
    """Already-has-a-check marking (Megan 2026-11-04)."""
    def test_names_out_of_sterling_subjects(self):
        from automations.office_admin import already as AL
        self.assertEqual(AL.name_from_subject("Background Check E-Invite for Williams, Myles Gregory is Complete"),
                         "Williams, Myles Gregory")
        self.assertEqual(AL.name_from_subject("Background Check for Defrain, Jarred Paul is complete"),
                         "Defrain, Jarred Paul")
        self.assertIsNone(AL.name_from_subject("Authentication Request"))

    def test_marks_by_sterling_name_and_by_page_log(self):
        from automations.office_admin import already as AL
        sterling = AL.sterling_done([("Background Check E-Invite for Koch, Milandi , N/a is Complete", "11/4"),
                                     ("Background Check E-Invite for Williams, Myles Gregory is Complete", "11/4")])
        people = [{"first_name": "Milandi", "last_name": "Koch", "email": "m@x.com"},
                  {"first_name": "Myles", "last_name": "Williams", "email": "w@x.com"},
                  {"first_name": "Cedric", "last_name": "Ball", "email": "c@x.com"},
                  {"first_name": "Ana", "last_name": "Lopez", "email": "a@x.com"}]
        out = AL.mark(people, page_log={"a@x.com": "11/3"}, sterling=sterling)
        self.assertEqual([bool(p["already"]) for p in out], [True, True, False, True])
        self.assertIn("from here 11/3", out[3]["already"])

    def test_page_log_ignores_test_runs_and_other_offices(self):
        from automations.office_admin import already as AL
        import json
        def row(office, status, result):
            return {"Office Key": office, "Action": C.SEND_BGC, "Status": status,
                    "Requested At": "2026-11-04 10:00:00", "Result": json.dumps(result),
                    "Details": json.dumps({"people": [{"email": "A@x.com"}]})}
        reqs = [row("raf", C.DONE, {"status": "dry_run"}), row("omar", C.DONE, {"status": "sent"})]
        self.assertEqual(AL.sent_from_page(reqs, "raf", today=dt.date(2026, 11, 4)), {})
        self.assertEqual(AL.sent_from_page(reqs, "omar", today=dt.date(2026, 11, 4)), {"a@x.com": "11/4"})

    def test_unreadable_inbox_is_not_an_error(self):
        from automations.office_admin import already as AL
        with mock.patch.object(AL, "sterling_subjects", side_effect=RuntimeError("no app password")):
            out = AL.check([{"first_name": "A", "last_name": "B", "email": "a@x.com"}], [], "raf",
                           log=lambda *_: None)
        self.assertEqual(out[0]["already"], "")


class NotSentAlert(unittest.TestCase):
    """Afternoon alert: 30 min before the Daily Update, Mon-Fri (Megan 11/04)."""
    def _office(self):
        return C.office("raf")

    def test_due_only_mon_fri_after_alert_time_office_local(self):
        from automations.office_admin import bgc_alert as BA
        from zoneinfo import ZoneInfo
        ct = ZoneInfo("America/Chicago")
        o = self._office()
        self.assertTrue(BA.due(o, dt.datetime(2026, 11, 4, 16, 30, tzinfo=ct)))     # Wed 4:30
        self.assertFalse(BA.due(o, dt.datetime(2026, 11, 4, 16, 29, tzinfo=ct)))
        self.assertFalse(BA.due(o, dt.datetime(2026, 11, 7, 17, 0, tzinfo=ct)))     # Saturday
        # Omar: 5:30 PM Eastern = 4:30 PM Central
        self.assertTrue(BA.due(C.office("omar"), dt.datetime(2026, 11, 4, 16, 30, tzinfo=ct)))
        self.assertFalse(BA.due(C.office("omar"), dt.datetime(2026, 11, 4, 16, 25, tzinfo=ct)))

    def _run(self, offered, jobs, sterling=None, post=True):
        from automations.office_admin import bgc_alert as BA
        from zoneinfo import ZoneInfo
        posted = []
        rc = BA.run(self._office(), post=post, now=dt.datetime(2026, 11, 4, 16, 45, tzinfo=ZoneInfo("America/Chicago")),
                    read=lambda o, d: offered, relay_log=lambda o, s: jobs,
                    sterling=lambda: sterling or {}, poster=lambda o, p, r: posted.append((p, r)),
                    log=lambda *_: None)
        return rc, posted

    def test_posts_only_who_is_still_waiting(self):
        offered = [{"first_name": "Ana", "last_name": "Lopez", "email": "a@x.com"},
                   {"first_name": "Bo", "last_name": "Kim", "email": "b@x.com"},
                   {"first_name": "Myles", "last_name": "Williams", "email": "m@x.com"}]
        jobs = [{"people": [{"email": "A@x.com"}], "result": {"status": "sent"}},
                {"people": [{"email": "b@x.com"}], "result": {"status": "dry_run"}}]   # test run: NOT sent
        rc, posted = self._run(offered, jobs, sterling={"myles|williams": "11/4"})
        self.assertEqual(rc, 0)
        parent, reply = posted[0]
        self.assertIn("1 offered today", parent)
        self.assertIn("Bo Kim", reply)
        self.assertNotIn("Ana", reply)
        self.assertNotIn("Myles", reply)

    def test_never_posts_blank(self):
        rc, posted = self._run([], [])
        self.assertEqual((rc, posted), (0, []))
        rc, posted = self._run([{"first_name": "A", "last_name": "B", "email": "a@x.com"}],
                               [{"people": [{"email": "a@x.com"}], "result": {"status": "sent"}}])
        self.assertEqual((rc, posted), (0, []))

    def test_unreadable_calendar_is_a_failure_not_all_clear(self):
        from automations.office_admin import bgc_alert as BA
        from zoneinfo import ZoneInfo
        def boom(o, d):
            raise RuntimeError("AppStream session expired")
        rc = BA.run(self._office(), post=True, now=dt.datetime(2026, 11, 4, 16, 45, tzinfo=ZoneInfo("America/Chicago")),
                    read=boom, relay_log=lambda o, s: [], sterling=lambda: {},
                    poster=lambda *a: self.fail("posted"), log=lambda *_: None)
        self.assertEqual(rc, 1)

    def test_dry_by_default_posts_nothing(self):
        rc, posted = self._run([{"first_name": "A", "last_name": "B", "email": "a@x.com"}], [], post=False)
        self.assertEqual((rc, posted), (0, []))


class SterlingCodes(unittest.TestCase):
    def test_sterling_request_round_trips(self):
        from automations.icd_alerts import code_answer as CA
        when = dt.datetime(2026, 11, 3, 9, 30, tzinfo=dt.timezone.utc)
        s = CA.summary_for(when, CA.STERLING)
        self.assertEqual(CA.service_of(s), CA.STERLING)
        self.assertEqual(CA.since_of(s), when)
        self.assertEqual(CA.service_of(CA.summary_for(when)), CA.SARAPLUS)

    def test_sterling_query_is_codes_only(self):
        from automations.icd_alerts import code_answer as CA
        q = CA.query_for("omar@x.com", CA.STERLING)
        self.assertIn("from:noreply@us.fadv.co", q)
        self.assertIn("subject:authentication", q)
        self.assertIn("to:omar@x.com", q)

    def test_scope_check_allows_codes_not_results(self):
        from automations.icd_alerts import code_answer as CA
        q = CA.scope_query("omar@x.com")
        self.assertIn("-(from:noreply@us.fadv.co subject:authentication)", q)
        self.assertNotIn("{", q)

    def test_sterling_code_is_read(self):
        from automations.rc_contact_sync.verify_code import extract_code
        self.assertEqual(extract_code("Authentication Request\nYour authentication code is 966828."), "966828")

    def test_sterling_request_answered_from_its_own_tab(self):
        from automations.icd_alerts import code_answer as CA
        now = dt.datetime(2026, 11, 3, 10, 0, tzinfo=dt.timezone.utc)
        since = now - dt.timedelta(minutes=2)
        fault = {"office": "omar", "stage": CA.REQUEST_STAGE,
                 "summary": CA.summary_for(since, CA.STERLING), "rownum": 5}
        queries = []

        def newest(s, q):
            queries.append(q)
            return ("966828", now)
        book = mock.MagicMock()
        tabs = {CA.MAIL_TAB: [["Office", "Forwards From"]],
                CA.STERLING_MAIL_TAB: [["Office", "Forwards From"], ["omar", "omar@x.com"]]}
        book.worksheet.side_effect = lambda t: mock.MagicMock(get_all_values=lambda: tabs[t])
        with mock.patch("automations.icd_alerts.post.open_faults", return_value=[fault]):
            out = CA.answer_requests(book, send=False, now=now, newest_code=newest, log=lambda *_: None)
        self.assertEqual(out[0]["status"], CA.STATUS_READY)
        self.assertIn("fadv", queries[0])


class SterlingForward(unittest.TestCase):
    """Each ICD's Sterling codes go to their OWN email; they forward them like
    SaraPlus's (Megan 2026-11-03)."""
    def test_address_summary_round_trips_per_service(self):
        from automations.icd_alerts import code_answer as CA
        s = CA.forward_summary("omar@gmail.com", CA.STERLING)
        self.assertEqual((CA.forward_service_of(s), CA.address_of(s)), (CA.STERLING, "omar@gmail.com"))
        s = CA.forward_summary("omar@gmail.com")
        self.assertEqual((CA.forward_service_of(s), CA.address_of(s)), (CA.SARAPLUS, "omar@gmail.com"))

    def _book(self, tabs):
        book = mock.MagicMock()
        made = {}

        def ws(t):
            if t not in tabs:
                raise KeyError(t)
            m = made.setdefault(t, mock.MagicMock())
            m.get_all_values.side_effect = lambda: tabs[t]
            m.append_row.side_effect = lambda row, **k: tabs[t].append(row)
            return m
        book.worksheet.side_effect = ws
        book.add_worksheet.side_effect = lambda title, **k: tabs.setdefault(title, [list(["Office"])]) and ws(title)
        return book

    def test_sterling_address_lands_on_its_own_tab(self):
        from automations.icd_alerts import code_answer as CA
        tabs = {"ICD Faults": [], CA.MAIL_TAB: [["Office", "Forwards From", "Added", "Note"]],
                CA.STERLING_MAIL_TAB: [["Office", "Forwards From", "Added", "Note"]]}
        fault = {"office": "omar", "stage": CA.FORWARD_STAGE, "rownum": 3,
                 "summary": CA.forward_summary("omar@gmail.com", CA.STERLING)}
        with mock.patch("automations.icd_alerts.post.open_faults", return_value=[fault]):
            CA.record_forwards(self._book(tabs), send=True, log=lambda *_: None)
        self.assertEqual(tabs[CA.STERLING_MAIL_TAB][-1][:2], ["omar", "omar@gmail.com"])
        self.assertEqual(len(tabs[CA.MAIL_TAB]), 1)          # SaraPlus tab untouched

    def test_no_sterling_row_falls_back_to_the_saraplus_address(self):
        from automations.icd_alerts import code_answer as CA
        now = dt.datetime(2026, 11, 3, 10, 0, tzinfo=dt.timezone.utc)
        fault = {"office": "omar", "stage": CA.REQUEST_STAGE, "rownum": 5,
                 "summary": CA.summary_for(now - dt.timedelta(minutes=1), CA.STERLING)}
        queries = []
        tabs = {CA.MAIL_TAB: [["Office", "Forwards From"], ["omar", "omar@gmail.com"]]}
        book = mock.MagicMock()
        book.worksheet.side_effect = lambda t: mock.MagicMock(get_all_values=lambda: tabs[t]) if t in tabs else (_ for _ in ()).throw(KeyError(t))
        with mock.patch("automations.icd_alerts.post.open_faults", return_value=[fault]):
            CA.answer_requests(book, send=False, now=now, log=lambda *_: None,
                               newest_code=lambda s, q: queries.append(q) or None)
        self.assertEqual(len(queries), 1)
        self.assertIn("fadv", queries[0])
        self.assertIn("to:omar@gmail.com", queries[0])

    def test_filter_link_carries_sender_and_subject(self):
        from automations.icd_alerts import sterling_forward as SF
        self.assertIn("from=noreply%40us.fadv.co", SF.FILTER_URL)
        self.assertIn("subject=Authentication%20Request", SF.FILTER_URL)

    def _ask(self, pick):
        a = mock.MagicMock()
        a.Cancelled = type("Cancelled", (Exception,), {})
        a.choose.return_value = pick
        return a

    def test_walk_skips_gmail_forward_when_saraplus_already_did_it(self):
        from automations.icd_alerts import code_forward as F, sterling_forward as SF
        ask = self._ask(F.YES)
        with mock.patch.object(F, "_login_email", return_value="omar@gmail.com"), \
                mock.patch.object(F, "_open") as op, mock.patch.object(F, "_copy"), \
                mock.patch("automations.icd_alerts.relay.report_forward", return_value=True) as rf, \
                mock.patch("automations.icd_alerts.relay.forward_confirmed", return_value=True):
            self.assertEqual(SF.walk_through(ask, say=lambda *_: None, office_key="omar"), "done")
        rf.assert_called_once_with("omar@gmail.com", office_key="omar", service="sterling")
        # Gmail opens in the ICD's own account (code_forward.for_account, Eve 11/04).
        self.assertEqual([c.args[0] for c in op.call_args_list],
                         [F.for_account(SF.FILTER_URL, "omar@gmail.com")])   # filter only

    def test_walk_adds_gmail_forward_when_missing(self):
        from automations.icd_alerts import code_forward as F, sterling_forward as SF
        ask = self._ask(F.YES)
        with mock.patch.object(F, "_login_email", return_value="omar@gmail.com"), \
                mock.patch.object(F, "_open") as op, mock.patch.object(F, "_copy"), \
                mock.patch.object(F, "_wait_for_gmail", return_value=True), \
                mock.patch("automations.icd_alerts.relay.report_forward", return_value=True), \
                mock.patch("automations.icd_alerts.relay.forward_confirmed", return_value=False):
            self.assertEqual(SF.walk_through(ask, say=lambda *_: None, office_key="omar"), "done")
        self.assertEqual([c.args[0] for c in op.call_args_list],
                         [F.for_account(F.FORWARDING_URL, "omar@gmail.com"),
                          F.for_account(SF.FILTER_URL, "omar@gmail.com")])

    def test_skip(self):
        from automations.icd_alerts import code_forward as F, sterling_forward as SF
        with mock.patch.object(F, "_login_email", return_value="omar@gmail.com"), \
                mock.patch("automations.icd_alerts.relay.report_forward") as rf:
            self.assertEqual(SF.walk_through(self._ask(F.LATER), say=lambda *_: None), "skipped for now")
        rf.assert_not_called()


class OfficeComputer(unittest.TestCase):
    def test_no_saved_login_is_an_answer_not_a_browser(self):
        from automations.icd_alerts import sterling_send
        with mock.patch("automations.icd_alerts.config.sterling_creds", return_value={}):
            r = sterling_send.send_invites([{"first_name": "A", "last_name": "B", "email": "a@b.c"}],
                                           live=False, location={"state": "Texas", "city": "Plano"})
        self.assertEqual(r["status"], "error")
        self.assertIn("no Sterling login", r["error"])

    def test_dry_run_drives_the_route_but_never_presses_send(self):
        from automations.icd_alerts import sterling_send as SS
        page = mock.MagicMock()
        with mock.patch.object(SS, "sign_in"), \
                mock.patch.object(SS, "open_hub", return_value=page), \
                mock.patch.object(SS, "fill_order"), \
                mock.patch.object(SS, "upload", return_value=1), \
                mock.patch.object(SS, "press_send") as send:
            r = SS.run_route(page, PEOPLE, LOC, live=False, creds={"username": "u", "password": "p"})
        send.assert_not_called()
        self.assertEqual((r["status"], r["found"]), ("dry_run", 1))

    def test_live_presses_send(self):
        from automations.icd_alerts import sterling_send as SS
        page = mock.MagicMock()
        with mock.patch.object(SS, "sign_in"), \
                mock.patch.object(SS, "open_hub", return_value=page), \
                mock.patch.object(SS, "fill_order"), \
                mock.patch.object(SS, "upload", return_value=1), \
                mock.patch.object(SS, "press_send") as send:
            r = SS.run_route(page, PEOPLE, LOC, live=True, creds={"username": "u", "password": "p"})
        send.assert_called_once()
        self.assertEqual(r["status"], "sent")

    def test_unknown_kind_is_an_answer_not_a_crash(self):
        from automations.icd_alerts import office_jobs
        r = office_jobs.work({"kind": "nope", "mode": "dry"}, "omar", log=lambda *_: None)
        self.assertEqual(r["status"], "error")

    def test_computer_without_sterling_login_never_asks(self):
        from automations.icd_alerts import office_jobs
        with mock.patch("automations.icd_alerts.config.sterling_creds", return_value={}), \
                mock.patch.object(office_jobs, "run_once") as ran:
            self.assertFalse(office_jobs.maybe_run(log=lambda *_: None))
        ran.assert_not_called()

    def test_office_hours(self):
        from automations.icd_alerts import office_jobs
        self.assertFalse(office_jobs.due(dt.datetime(2026, 11, 2, 3, 0), {}))
        self.assertTrue(office_jobs.due(dt.datetime(2026, 11, 2, 12, 0), {}))


if __name__ == "__main__":
    unittest.main()
