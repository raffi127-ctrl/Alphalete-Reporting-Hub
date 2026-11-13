# -*- coding: utf-8 -*-
"""python -m unittest automations.applicant_stream_card.test_card

No network, no files: every input is built here."""
from __future__ import annotations

import datetime as dt
import unittest

from automations.applicant_stream_card import card as C
from automations.applicant_stream_card import fixes as F
from automations.applicant_stream_card import stream_stats as S


def rec(slot, push, book, by, status, board="Indeed", moved=False):
    acts = [["Send to Call List", "Process Emails", push, "Jen (CC)"],
            ["Send to AI", "Call List", push, "Jen (CC)"],
            ["Assign First Interview", "Call List", book, by]]
    if moved:
        acts.append(["Reschedule First Interview", "Calendar", book, by])
    d, t = slot.split(" ", 1)
    return {"date": d, "time": t, "status": status, "board": board,
            "booked_by": "A. Messaging" if by == "AI Messaging" else by,
            "actions": repr(acts)}


def office_week():
    """40 AI bookings same day (30 show), 40 human two days late (12 show)."""
    out = []
    for i in range(40):
        out.append(rec("10-06-2026 1:00 PM", "10-06-2026 08:00 AM",
                       "10-06-2026 09:00 AM", "AI Messaging",
                       "Interview Completed" if i < 30 else "No Show"))
        out.append(rec("10-09-2026 9:00 AM", "10-06-2026 08:00 AM",
                       "10-08-2026 10:00 AM", "Jorge Pena (CC)",
                       "Interview Completed" if i < 12 else "No Show",
                       board="LinkedIn"))
    return out


class StatsTest(unittest.TestCase):
    def setUp(self):
        self.s = S.summary(office_week())

    def test_reads_the_repr_action_list(self):
        t = S.timeline(office_week()[0])
        self.assertEqual(t["booked"], dt.datetime(2026, 10, 6, 9, 0))
        self.assertTrue(t["ai"])

    def test_ai_vs_human_split(self):
        w = self.s["who"]
        self.assertEqual((w["ai_n"], w["human_n"]), (40, 40))
        self.assertAlmostEqual(w["ai_share"], 50.0)
        self.assertAlmostEqual(w["ai_show"], 75.0)
        self.assertAlmostEqual(w["human_show"], 30.0)

    def test_days_to_book(self):
        d = self.s["days"]
        # 40 at 1h, 40 at 50h -> average 25.5h
        self.assertAlmostEqual(d["push_to_book"]["avg_h"], 25.5)
        self.assertAlmostEqual(d["late_share"], 50.0)
        self.assertAlmostEqual(d["same_day_share"], 50.0)

    def test_top_booking_hour(self):
        self.assertIn(self.s["times"]["top_hours"][0][0], ("9am", "10am"))

    def test_drivers_ranked_and_tested(self):
        dr = self.s["drivers"]
        self.assertTrue(dr and dr[0]["real"])
        self.assertAlmostEqual(dr[0]["gap"], 45.0)

    def test_small_groups_are_not_drivers(self):
        self.assertEqual(S.retention_drivers(S.timelines(office_week()[:6])),
                         [])

    def test_no_outcome_is_not_a_no_show(self):
        self.assertIsNone(S.shown({"status": ""}))
        self.assertFalse(S.shown({"status": "No Show"}))
        self.assertTrue(S.shown({"status": "Brought on Board"}))


class FixesTest(unittest.TestCase):
    def test_zoom_meeting_id_is_not_a_phone_number(self):
        from automations.sms_audit import templates as T
        body = ("Join https://us02web.zoom.us/j/2935077152 Meeting ID "
                "293 507 7152")
        self.assertEqual(T.lint([("S", "N", body)], {},
                                {"phone": "469-262-2775"})[0], [])
        wrong = T.lint([("S", "N", "Call (469) 555-0101")], {},
                       {"phone": "469-262-2775"})[0]
        self.assertEqual([k for k, _t in wrong], ["CHECK PHONE"])

    def test_setup_box_has_each_round_and_its_own_zoom(self):
        from automations.applicant_stream_card import run
        si = {"office_name": "Alphalete", "office_address1": "1 Main St Ste 2",
              "office_city": "Plano", "office_state": "TX",
              "office_zip": "75024", "office_phone": "469-262-2775"}
        bodies = [("First Interview Confirmation", "A",
                   "join https://zoom.us/j/111"),
                  ("Second Interview Invite", "B",
                   "join https://zoom.us/j/222"),
                  ("2nd Left Message - Call List", "C",
                   "join https://zoom.us/j/111")]
        states = {b[0]: "Activated" for b in bodies}
        zooms = run.zoom_in_use(bodies, states)
        self.assertEqual(zooms, {1: ["https://zoom.us/j/111"],
                                 2: ["https://zoom.us/j/222"]})
        facts = dict(run.grading_facts({"r1_mode": "zoom", "r2_mode": ""},
                                       si, zooms))
        self.assertEqual(facts["1st rounds"], "Zoom \u00b7 https://zoom.us/j/111")
        self.assertEqual(facts["2nd rounds"], "Zoom \u00b7 https://zoom.us/j/222")
        facts = dict(run.grading_facts({"r1_mode": "zoom",
                                        "r2_mode": "in person"}, si,
                                       {1: [], 2: []}))
        self.assertTrue(facts["2nd rounds"].startswith("In person"))
        office = {"r1_mode": "zoom", "r2_mode": "In person"}
        run.grading_facts(office, si, zooms)
        self.assertEqual(office["zoom2"], "")   # its Zoom link is not "right"
        self.assertEqual(len(run.grading_facts({}, si, {1: [], 2: []})[0]), 2)

    def test_placeholder_is_wording_not_wrong_info(self):
        self.assertNotIn("PLACEHOLDER", C.WRONG_INFO)

    def test_template_walkthrough_names_the_template_and_the_answer(self):
        f = F.template("WRONG ADDRESS",
                       "Directions / Directions: sends “3000 Premier”",
                       {"office": "11280",
                        "address": "3100 Premier Dr Suite 207, Irving TX"})
        joined = " ".join(f["steps"])
        self.assertIn("Directions / Directions", joined)
        self.assertIn("3100 Premier Dr Suite 207", joined)
        self.assertIn("Activate again", joined)

    def test_email_templates_go_to_the_email_page(self):
        f = F.template("SHOUTING", "Email / On Hold: “ALPHALETE”",
                       {})
        self.assertIn("Email Templates", f["steps"][0])

    def test_preferences_against_the_standard(self):
        # 60 / 60 / 60 since 2026-11-13: both buffers are "too soon" floors
        got = F.check_preferences({"offered_buffer": "60",
                                   "accepted_buffer": "5",
                                   "ghosting_threshold": "60"})
        self.assertEqual([g["kind"] for g in got], ["PREF accepted_buffer"])
        self.assertIn("too soon", got[0]["title"])
        # the old 180 / 300 is now what gets flagged: it closes same-day
        got = F.check_preferences({"offered_buffer": "180",
                                   "accepted_buffer": "300",
                                   "ghosting_threshold": "60"})
        self.assertEqual(len(got), 2)
        self.assertIn("same-day", got[1]["why"])
        # Aptel's 45 / 30 is inside the range: not flagged
        self.assertEqual(F.check_preferences({"offered_buffer": "45",
                                              "accepted_buffer": "30",
                                              "ghosting_threshold": "60"}),
                         [])

    def test_routing_summary(self):
        ok = F.approved_replies()
        self.assertEqual(len(ok), 31)
        self.assertEqual(ok[0][0], 1)
        self.assertNotIn("Tennyson", " ".join(m for _n, _x, m in ok))
        rows = [{"name": "Pay", "routing": "Clarify"}] * 40
        got = F.routing_summary(rows)
        self.assertEqual(got["kind"], "ROUTING")
        self.assertEqual(len(got["replies"]), 31)
        rows = [{"name": n, "routing": "Don't Escalate"} for _i, n, _m in ok]
        self.assertIsNone(F.routing_summary(rows))
        got = F.routing_summary(rows[1:])
        self.assertIn("#1 ", got["found"])
        self.assertEqual([r[0] for r in got["replies"]], [1])
        body = C._fix_body(got)
        self.assertIn("<li value='1'>", body)
        # #1 Request to talk via Phone links to the replies page
        self.assertIn("See the 5 replies", body)

    def test_matched_rows_link_to_the_five_replies(self):
        link = F.reply_link("compensation")
        self.assertTrue(link.endswith("#q16"))
        self.assertIsNone(F.reply_link("Travel"))
        from automations.applicant_stream_card import setup_page as P
        self.assertIn("See the 5 replies", P.options_html(["x"], link))
        self.assertNotIn("See the 5", P.options_html(["x"]))


class VitalsTest(unittest.TestCase):
    def test_sundays_are_finished_weeks_oldest_first(self):
        from automations.applicant_stream_card import vitals as V
        got = V.last_sundays(3, today=dt.date(2026, 11, 13))     # a Friday
        self.assertEqual(got, [dt.date(2026, 10, 18), dt.date(2026, 10, 25),
                               dt.date(2026, 11, 1)])
        self.assertTrue(all(d.weekday() == 6 for d in got))

    def test_round_trip_trend_and_trend_page(self):
        from automations.applicant_stream_card import vitals as V
        weeks = [(dt.date(2026, 10, 4) + dt.timedelta(weeks=i),
                  {"pct_first_retention": 40 + i, "first_showed": 50,
                   "pull": None}) for i in range(5)]
        back, stamp = V.parse(V.to_rows(weeks))
        self.assertEqual(back[-1][1]["pct_first_retention"], 44.0)
        self.assertIsNone(back[0][1]["pull"])
        self.assertTrue(stamp.startswith("pulled"))
        latest, delta = V.trend(back, "pct_first_retention")
        self.assertEqual((latest, delta), (44.0, 2.0))
        out = C.render(C.build("1", vitals=(back, stamp)))
        page0 = out[out.index("<div class='page0'>"):out.index(
            "<div class='page1'>")]
        self.assertIn("1st round retention", page0)
        self.assertIn("44%", page0)
        self.assertIn("\u25b2 +2 pts", page0)
        self.assertIn("RTCL", page0)
        # a line per vital, the weekly numbers behind a click
        self.assertIn("<svg class='spark'", page0)
        self.assertIn("<details class='vital'>", page0)
        self.assertIn("Week of 11/1", page0)
        # coloured by height: red low weeks -> orange -> green best weeks
        self.assertIn("linearGradient", page0)
        self.assertIn("stop-color='#c0392b'", page0)
        self.assertIn("fill='#1f8a4c'", page0)          # its best week
        self.assertIn("stroke='#e08a00'", page0)        # a flat row
        # Trend is the tab that opens first
        self.assertIn("id='pg0' checked", out)

    def test_vitals_from_a_week_of_retention_details_counts(self):
        from automations.applicant_stream_card import vitals as V
        days = {dt.date(2026, 11, 1): {"b1": 60, "s1": 30, "b2": 20, "s2": 10,
                                       "nss": 40, "nsh": 21, "sent": 90,
                                       "manual": 10, "scoop_s": 0,
                                       "file_s": 0, "retb": 50},
                dt.date(2026, 11, 2): {"b1": 40, "s1": 30, "b2": 0, "s2": 0,
                                       "nss": 1, "nsh": 1, "sent": 100,
                                       "manual": 0, "scoop_s": 0,
                                       "file_s": 0, "retb": 50}}
        got = V.from_days(days)
        self.assertEqual(got["pct_first_retention"], 60.0)      # 60 / 100
        self.assertEqual(got["pct_new_start_retention"], 53.7)  # 22 / 41
        self.assertEqual(got["pull"], 200)
        self.assertEqual(got["pct_apps_booked_first"], 50.0)    # 100 / 200
        self.assertIsNone(V.from_days({dt.date(2026, 11, 1): {"b1": 0}})[
            "pct_first_retention"])

    def test_no_vitals_says_not_pulled(self):
        out = C.render(C.build("1"))
        self.assertIn("Not pulled yet", out[out.index("<div class='page0'>"):
                                             out.index("<div class='page1'>")])


class SlotsTest(unittest.TestCase):
    def _hours(self, am, pm, seats=2):
        mk = lambda t: {"start": t, "end": t, "seats": seats}
        day = [mk("09:00 AM")] * am + [mk("01:00 PM")] * pm
        return {"Monday": day, "Tuesday": day}

    def test_morning_and_afternoon_a_day(self):
        recs = [{"date": "11-09-2026"}, {"date": "11-10-2026"}] * 2
        sl = S.slots(self._hours(2, 3), recs)
        self.assertEqual((sl["morning"], sl["afternoon"], sl["seats"]),
                         (2, 3, 10))
        self.assertAlmostEqual(sl["fill"], 0.2)
        self.assertIsNone(S.slots({}))

    def test_coaching_few_options_then_too_many_then_full(self):
        few = C.slot_line(S.slots(self._hours(1, 4)))
        self.assertEqual(few["dot"], C.YELLOW)
        self.assertIn("morning", few["action"])
        recs = [{"date": "11-09-2026"}]               # 1 of 10 seats
        many = C.slot_line(S.slots(self._hours(2, 3), recs))
        self.assertIn("Fewer", many["action"])
        recs = [{"date": "11-09-2026"}] * 9 + [{"date": "11-10-2026"}] * 9
        full = C.slot_line(S.slots(self._hours(2, 3), recs))
        self.assertIn("nearly full", full["action"])
        ok = C.slot_line(S.slots(self._hours(3, 3), [{"date": "11-09-2026"}]
                                 * 3 + [{"date": "11-10-2026"}] * 3))
        self.assertEqual(ok["dot"], C.GREEN)
        self.assertIsNone(ok["action"])
        self.assertEqual(C.slot_line(None)["short"], "Not pulled yet")

    def test_page_two_lists_the_times(self):
        from automations.applicant_stream_card import setup_page as P
        setup = P.gather()
        setup["hours"] = self._hours(1, 1)
        out = P.render(setup)
        self.assertIn("9:00 AM (2)", out)
        self.assertIn("1:00 PM (2)", out)


class SetupPageTest(unittest.TestCase):
    def test_page_two_shows_settings_buffers_replies_and_templates(self):
        from automations.applicant_stream_card import setup_page as P
        pull = ("##### PAGE p=325 ('Email Templates')\nAwait Call\n"
                "Await call email goes out\nFound : 2\nMultiples?: Yes\n"
                "Create New\nGENERAL\t(Not Activated)\t\n"
                "LM1 with SB\t(Activated)\t\n##### PAGE p=714\n")
        emails = P.parse_email_list(pull)
        self.assertEqual(emails[0][:2], ("Await Call", "Activated"))
        setup = P.gather(
            {"office_name": "Alphalete", "office_phone": "469-262-2775"},
            {"offered_buffer": "45", "accepted_buffer": "5",
             "ghosting_threshold": "60"},
            [{"name": "Compensation", "routing": "Don't Escalate",
              "message": "On average"}],
            [("Await Call", "T1", "Hey there"),
             ("Await Call", "T1", "Hey there")],
            {"Await Call": "Activated", "Rejection": "Not Activated"},
            emails=emails)
        self.assertEqual(len(setup["sms"][0][2]), 1)      # duplicate dropped
        # off-standard buffers, a recommended text that is off, and a
        # recommended text that does not exist all get flagged
        self.assertFalse(setup["prefs"][0][4])            # 45 is fine
        self.assertTrue(setup["prefs"][1][4])             # 5 is too soon
        self.assertFalse(setup["prefs"][2][4])            # ghosting = 60
        sms = {r[0]: r[3] for r in setup["sms"]}
        self.assertFalse(sms["Await Call"])               # not on Raf's list
        self.assertIn("Directions AI", sms)               # recommended, missing
        self.assertTrue(sms["Directions AI"])
        # Compensation is already Don't Escalate: no flag; the other 30
        # approved replies are listed as not set up
        self.assertFalse(setup["replies"][0][3])
        self.assertEqual(len(setup["replies_missing"]), 30)
        c = C.build("1", setup=setup)
        out = C.render(c)
        # the switch is radio tabs, not #links
        self.assertIn("<label for='pg2'>AppStream setup</label>", out)
        page2 = out[out.index("<div class='page2'>"):]
        self.assertIn("45 min", page2)            # buffer as set now
        self.assertIn("60 min (1 hr)", page2)     # next to our standard
        self.assertIn("class='diff'", page2)
        self.assertIn("469-262-2775", page2)
        self.assertIn("On average", page2)
        self.assertIn("Hey there", page2)
        self.assertIn("LM1 with SB", page2)
        self.assertIn("thing", page2)                     # the flag count
        self.assertIn("class='flag'", page2)
        # every flag says who fixes it
        self.assertEqual(page2.count("class='flag'"),
                         page2.count("Who fixes it:"))
        self.assertIn("You or your admin can change this", page2)

    def test_template_flag_sits_under_it_with_the_part_in_red(self):
        from automations.applicant_stream_card import setup_page as P
        bodies = [("2nd Interview Invite", "LM #1", "Hello there"),
                  ("2nd Interview Invite", "LM #1", "I\u2019ve emailed you"),
                  ("2nd Left Message - Call List", "Test", "test")]
        states = {"2nd Interview Invite": "Activated",
                  "2nd Left Message - Call List": "Activated"}
        items = [F.template("NOT PLAIN TEXT",
                            "2nd Interview Invite / LM #1 (the one starting "
                            "\u201cI\u2019ve emailed\u2026\u201d): contains \u2019",
                            {}),
                 F.template("PLACEHOLDER", "2nd Left Message - Call List / "
                            "Test: the whole body is \u201ctest\u201d.", {})]
        setup = P.gather(bodies=bodies, states=states, items=items)
        sms = {r[0]: r for r in setup["sms"]}
        inv = sms["2nd Interview Invite"][2]
        self.assertEqual([len(t[2]) for t in inv], [0, 1])  # the right one
        out = P.render(setup)
        self.assertIn("What it says now:", out)
        self.assertIn("I<mark>\u2019</mark>ve", out)
        self.assertIn("<mark>test</mark>", out)
        self.assertIn("We'd recommend:", out)
        # the section's flag count includes its templates' flags
        inv_head = out[out.index("2nd Interview Invite"):][:200]
        self.assertIn("\u2691 1", inv_head)
        self.assertEqual(sum(len(t[2]) for r in setup["sms"] for t in r[2]),
                         2)

    def test_our_words_on_the_wrong_type_only_ask_to_switch_type(self):
        from automations.applicant_stream_card import setup_page as P
        rows = [{"name": "Company Name Confusion", "routing": "Clarify",
                 "message": "Alphalete is hiring, AT&T is our client. "
                            "Message not sent as written: Clarify and "
                            "Escalate send their own reply."},
                {"name": "Compensation", "routing": "Escalate",
                 "message": ""}]
        setup = P.gather(esc_rows=rows)
        got = {r[0]: r for r in setup["replies"]}
        cnc = got["Company Name Confusion"]
        self.assertNotIn("Message not sent", cnc[2])
        self.assertIn("switch this to Don't Escalate", cnc[3][0]["title"])
        self.assertIsNone(cnc[3][0]["link"])            # no new wording
        comp = got["Compensation"][3][0]
        self.assertTrue(comp["link"].endswith("#q16"))  # blank -> our 5
        self.assertIn("What your current reply says:", P.render(setup))

    def test_page_two_says_not_pulled(self):
        out = C.render(C.build("1"))
        self.assertIn("Not pulled yet", out[out.index("<div class='page2'>"):])


class CardTest(unittest.TestCase):
    def _items(self, n, kind="NO OPT-OUT"):
        return [F.template(kind, "Await Call / T{}: x".format(i), {})
                for i in range(n)]

    def test_same_kind_folds_into_one_walkthrough(self):
        got = C.fold(self._items(5))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["count"], 5)
        self.assertIn("T4", got[0]["found"])

    def test_no_data_is_grey_never_green(self):
        c = C.build("1", info_skipped=["templates not pulled"])
        info = c["lines"][0]
        self.assertEqual(info["dot"], C.GREY)
        self.assertTrue(all(ln["dot"] != C.GREEN for ln in c["lines"]
                            if ln["key"] in ("who", "speed", "recruiters")))

    def test_wrong_info_goes_first(self):
        c = C.build("1", info_items=[F.template(
            "WRONG ROOM", "Confirm / A: zoom", {})],
            word_items=self._items(1, "SHOUTING"))
        self.assertEqual(c["todo"][0]["item"]["kind"], "WRONG ROOM")
        self.assertEqual(c["lines"][0]["dot"], C.RED)

    def test_old_pull_is_flagged(self):
        now = dt.datetime(2026, 11, 12)
        c = C.build("1", sources=[("AI Settings", dt.date(2026, 10, 1), "tab"),
                                  ("Texts", dt.date(2026, 11, 11), "file")],
                    now=now)
        self.assertEqual([f["what"] for f in c["stale"]], ["AI Settings"])
        self.assertIn("re-pull before sending", C.render(c))

    def test_top_three_are_one_line_actions(self):
        c = C.build("1", info_items=[F.template(
            "WRONG ADDRESS", "Directions / Directions: sends x",
            {"address": "3100 Premier"})],
            stats=S.summary(office_week()))
        self.assertLessEqual(len(c["todo"]), 3)
        self.assertEqual(c["todo"][0]["text"],
                         "Fix the address in “Directions”")
        # the speed habit makes the list when booking runs late
        self.assertTrue(any(t["line"] == "speed" for t in c["todo"]))

    def test_recruiter_name_opens_full_scorecard(self):
        c = C.build("1", recruiter_rows=[
            {"name": "Dulce Lamb", "grade": "D", "booked": 3,
             "retention": "20%", "focus": "x", "body": "<p>D CARD</p>"},
            {"name": "Jorge Pena", "grade": "C", "booked": 9,
             "retention": "40%", "focus": "1st Round Retention",
             "body": "<h1>Jorge Pena</h1><p>FULL CARD</p>"},
            {"name": "Gisela Soto", "grade": "A", "booked": 9,
             "retention": "60%", "focus": "x", "body": "<p>A CARD</p>"}])
        out = C.render(c, "h1{color:red}")
        self.assertIn("FULL CARD", out)
        self.assertIn(".sc h1{color:red}", out)
        # the name opens its card in place — no #links (dead in the app pane)
        self.assertIn("<details class='rc'><summary>", out)
        self.assertNotIn("href='#rc", out)
        # A first, D last
        names = out[out.index("<div class='names'>"):]
        self.assertLess(names.index("Gisela Soto"), names.index("Jorge Pena"))
        self.assertLess(names.index("Jorge Pena"), names.index("Dulce Lamb"))

    def test_delivery_splits_our_number_from_bad_applicant_numbers(self):
        log = ([{"type": "Out", "status": "Delivered",
                 "sender_phone": "+1469"}] * 90
               + [{"type": "Out", "status": "Failed",
                   "sender_phone": "+1469"}] * 8
               + [{"type": "Out", "status": "Dummy Phone",
                   "sender_phone": "+1469"}] * 2
               + [{"type": "In", "status": ""}] * 5)
        dv = S.delivery(log)
        self.assertEqual((dv["sent"], dv["failed"], dv["ours"]), (100, 10, 8))
        line = C.texts_arrived(dv)
        self.assertEqual(line["dot"], C.RED)
        self.assertIn("Aptel", line["action"])
        self.assertEqual(dv["numbers"][0][0], "+1469")

    def test_grading_box_is_at_the_top(self):
        c = C.build("1", grading=[("Address", "5217 Tennyson Pkwy", "AI "
                                   "Settings")])
        out = C.render(c)
        self.assertLess(out.index("what we're grading against"),
                        out.index("Your scorecard"))

    def test_renders(self):
        html = C.render(C.build("11280", stats=S.summary(office_week())))
        self.assertIn("Applicant Stream Grade Card", html)
        self.assertIn("AI vs recruiters", html)


if __name__ == "__main__":
    unittest.main()
