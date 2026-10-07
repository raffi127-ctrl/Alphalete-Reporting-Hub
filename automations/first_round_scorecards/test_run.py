"""python -m unittest automations.first_round_scorecards.test_run"""
import datetime as dt
import unittest

from automations.first_round_scorecards import appstream, doc, grade, run, zooms

# Camila's ZOOMS INFO tab, trimmed: tests never read the real Sheet
ZOOMS_TAB = [
    ["33", "ZOOM 1", "ZOOM 3", "ZOOM 8", "CARLOS' ZOOM"],
    ["", "504 877 4019", "711 240 6133", "660 341 8230", ""],
    ["MORNINGS", "Jamis Garay", "Joe Logan", "Jennifer Figueroa", "Carlos Hidalgo"],
    ["", "", "", "", ""],
    ["AFTERNOONS", "", "", "", ""],
    ["", "", "Cyrus Wade", "Mercy Ohiokhai", ""],
    ["", "ZOOM 1", "ZOOM 3 ", "ZOOM 8", "Carlos' Zoom"],
    ["", "arszooma@gmail.com", "arszoomc@gmail.com", "arszoomh@gmail.com", ""],
    ["", "pw", "pw", "pw", ""],
    ["", "KEY1", "KEY3", "whsec_abc", "CARLOSKEY0123456789"],
]
zooms._accounts = zooms.parse(ZOOMS_TAB)

MEETING = {"recording_id": 1, "recording_start_time": "2026-09-29T15:47:15Z",
           "recording_end_time": "2026-09-29T16:02:55Z",
           "share_url": "https://fathom.video/share/x",
           "recorded_by": {"name": "ARS ZOOM 12", "email": "arszoomp@gmail.com"}}


def result(said=None, verbiage=(), **happened):
    items = {k: {"happened": kind == "must", "note": ""} for k, _, kind in grade.ITEMS}
    for k, v in happened.items():
        items[k]["happened"] = v
    # the model names portions in any order; the post shows them in script order
    gaps = [{"portion": k, "kind": "skipped", "note": "Never came up. @3:37"}
            for k, v in reversed(list((said or {}).items())) if not v]
    gaps += [{"portion": k, "kind": "incorrect_verbiage", "note": '"six months" @09:08'}
             for k in verbiage]
    return {"is_interview": True, "skipped_portions": gaps, "not_interview_reason": "", "applicants": ["Nakechia"],
            "items": items, "coaching": ["Do the schedule section.", "Keep the pay on script."],
            "applicant_questions": [{"topic": "Door to door", "question": "Is this in the field? @4:10",
                                     "answer": "Yes, face to face with clients. @4:15"}]}


class ScoreTest(unittest.TestCase):
    def test_perfect_is_100(self):
        self.assertEqual(grade.score(result())["score"], 100)

    def test_red_flag_yes_loses_points(self):
        s = grade.score(result(retail=True))
        self.assertEqual((s["score"], s["red_hit"], s["missed"]), (91, 1, ["retail"]))

    def test_must_do_no_loses_points(self):
        # the pilot's usual shape: schedule, wrap-up, check-ins and commute missed = 64
        s = grade.score(result(schedule=False, wrap_up=False, check_ins=False, commute=False))
        self.assertEqual((s["score"], s["musts_done"]), (64, 2))


class ReplyTest(unittest.TestCase):
    def test_reply_has_time_score_misses_and_link(self):
        text = run.reply_text(MEETING, result(schedule=False, off_script_pay=True))
        self.assertIn("10:47 AM CT", text)
        self.assertIn("16 min", text)
        self.assertIn("Nakechia", text)
        self.assertIn("Score: 82/100", text)
        self.assertIn("🚩 pay different from the script", text)
        self.assertIn("❌ Missed: schedule section", text)
        self.assertIn("<https://fathom.video/share/x|Watch the recording>", text)

    def test_skipped_recording_says_why(self):
        text = run.reply_text(MEETING, None, skipped="the recording has almost no transcript")
        self.assertIn("Not scored — the recording has almost no transcript", text)

    def test_interviewer_from_account(self):
        self.assertEqual(run.interviewer(MEETING), "Valentina")
        other = dict(MEETING, recorded_by={"name": "ARS ZOOM 7", "email": "x@y.com"})
        self.assertEqual(run.interviewer(other), "ARS ZOOM 7")

    def test_shared_account_splits_by_the_name_she_said(self):
        shared = dict(MEETING, recorded_by={"name": "Camila hk",
                                            "email": "camilahk@arsinterviewsservice.com"})
        self.assertEqual(run.interviewer(shared, {"interviewer_name": "perla."}), "Perla")
        # not in the trimmed tab here: its Zoom name
        self.assertEqual(run.interviewer(shared, {"interviewer_name": ""}), "Camila hk")
        # ZOOM 12 isn't only Valentina's anymore (10/1): the intro wins there too
        self.assertEqual(run.interviewer(MEETING, {"interviewer_name": "Nakechia"}), "Nakechia")
        self.assertEqual(run.interviewer(MEETING), "Valentina")

    def test_sheet_zoom_splits_by_name_falls_back_to_the_zoom(self):
        z3 = dict(MEETING, recorded_by={"name": "ARS ZOOM 3", "email": "arszoomc@gmail.com"})
        self.assertEqual(run.interviewer(z3, {"interviewer_name": "Camila"}), "Camila")
        self.assertEqual(run.interviewer(z3), "ZOOM 3")

    def test_zoom_with_no_login_matched_by_its_key(self):
        # Carlos' Zoom (10/2): key in the tab, login cell empty
        m = dict(MEETING, recorded_by={"name": "Carlos", "email": "someone@carlos.com"},
                 fathom_key_tail="CARLOSKEY0123456789"[-12:])
        self.assertEqual(zooms.owner(m, dt.datetime(2026, 10, 2, 9, 0)), "Carlos Hidalgo")
        self.assertEqual(run.interviewer(m), "Carlos' Zoom")
        self.assertIn("CARLOSKEY0123456789", [z["key"] for z in zooms.accounts().values()])

    def test_thread_title(self):
        self.assertEqual(run.thread_title("Valentina"), "Valentina's 1st Round Scorecards")


# Nakechia's 9/29 interview as Rafael counted it by hand: 5 skipped portions
NAKECHIA = {"face_to_face": False, "schedule": False, "commute": False,
            "check_ins": False, "wrap_up": False}


class SkippedTest(unittest.TestCase):
    def test_reply_counts_skipped_portions_and_quotes_the_script(self):
        text = run.reply_text(MEETING, result(said=NAKECHIA))
        self.assertIn("⏭️ *Skipped portions: 5*", text)
        self.assertIn('• _"All interactions with them are face to face', text)
        self.assertIn("we went a different direction.\"_", text)
        # script order, not the order the model happened to answer in
        order = [text.index(line[:25]) for k, line in grade.PORTIONS if k in NAKECHIA]
        self.assertEqual(order, sorted(order))

    def test_nothing_skipped_no_line(self):
        self.assertNotIn("Skipped portions", run.reply_text(MEETING, result()))

    def test_old_result_without_portions_still_posts(self):
        r = result()
        del r["skipped_portions"]
        self.assertNotIn("Skipped portions", run.reply_text(MEETING, r))
        self.assertNotIn("Skipped portions", doc.build_html(MEETING, "Valentina", r))

    def test_doc_lists_each_with_the_note(self):
        page = doc.build_html(MEETING, "Valentina", result(said=NAKECHIA))
        self.assertIn("Skipped portions: 5", page)
        self.assertIn('?timestamp=217">@3:37</a>', page)


class KeyPiecesTest(unittest.TestCase):
    def test_every_portion_has_its_key_pieces_in_the_prompt(self):
        for k, _ in grade.PORTIONS:
            self.assertIn(f"- {k}: {grade.KEY_PIECES[k]}", grade.SYSTEM)


class OfficeScriptTest(unittest.TestCase):
    """Each office's own pay + schedule (Camila's scripts, 2026-10-06)."""

    def test_owner_as_zooms_info_writes_it(self):
        self.assertEqual(grade.office_for("Raf Hidalgo\n2nd funnel"), "Rafael Hidalgo")
        self.assertEqual(grade.office_for("Nii Tagoe"), "Nii Teiko")
        self.assertEqual(grade.office_for(" jacob  dover "), "Jacob Dover")
        self.assertEqual(grade.office_for("Salik Mallick"), "")  # no script of their own
        self.assertEqual(grade.office_for("Geoge Delgado"), "George Delgado")
        self.assertEqual(grade.office_for(""), "")

    def test_no_script_is_rafaels(self):
        self.assertEqual(grade.build("")["system"], grade.build("Salik Mallick")["system"])
        self.assertIn("$1000 - $1500", grade.SYSTEM)

    def test_office_numbers_and_schedule_in_its_prompt(self):
        system = grade.build("Jacob Dover")["system"]
        self.assertIn("Jacob Dover's office", system)
        self.assertIn("entry $900-1,200 average weekly paycheck, Assistant Manager $65-75k",
                      system)
        self.assertIn("Monday through Friday, from 9:00AM to 8:00PM", system)
        self.assertNotIn("$1000 - $1500", system)

    def test_monday_friday_not_a_flag_when_the_script_says_it(self):
        self.assertIn("mon_fri: NO", grade.build("Nii Teiko")["rules"])
        self.assertIn("mon_fri: YES", grade.build("Jacob Dover")["rules"])

    def test_skipped_line_quotes_the_offices_script(self):
        r = result(said={"pay_entry": False})
        r["script_office"] = "Rashad Reed"
        text = run.reply_text(MEETING, r)
        self.assertIn("$900 - $1200", text)
        self.assertNotIn("$1000 - $1500", text)
        self.assertIn("Script:</b> Rashad Reed's office", doc.build_html(MEETING, "V", r))


class ScriptFormatTest(unittest.TestCase):
    """Scripts not shaped like Rafael's (Camila's PDFs, 2026-10-07): the items
    they leave for the 2nd round aren't counted."""

    def r(self, office, **kw):
        r = result(**kw)
        r["script_office"] = office
        return r

    def test_profits_management_doesnt_count_the_pay(self):
        # Jairo's script has no pay in the 1st round: not explaining it is fine
        s = grade.score(self.r("Jairo Ruiz", pay=False))
        self.assertEqual((s["score"], s["n_must"], s["na"]), (100, 5, ["pay"]))
        self.assertEqual(grade.score(self.r("Jairo Ruiz", commute=False))["score"], 90)
        b = grade.build("Jairo Ruiz")
        self.assertNotIn("pay_entry", dict(b["portions"]))
        self.assertIn("send the address via zoom chat", b["system"])
        self.assertIn("quoted any pay number at all", b["rules"])

    def test_highline_leaves_pay_schedule_commute(self):
        s = grade.score(self.r("Ryan McSpadden", pay=False, schedule=False, commute=False))
        self.assertEqual((s["score"], s["n_red"] + s["n_must"]), (100, 8))
        self.assertEqual(grade.office_for("Roshan Ahmad"), "Roshan Ahmad")

    def test_carlos_own_pay_no_schedule(self):
        b = grade.build("Carlos Hidalgo")
        self.assertIn("$1200 to $2000 a week", b["system"])
        self.assertIn("Grand Prairie", b["system"])
        self.assertNotIn("schedule", dict(b["portions"]))
        self.assertEqual(grade.score(self.r("Carlos Hidalgo", schedule=False))["score"], 100)

    def test_na_item_in_the_doc_and_reply(self):
        r = self.r("Jairo Ruiz", pay=False)
        page = doc.build_html(MEETING, "Gonzalo", r)
        self.assertIn("Did she explain the pay? — N/A", page)
        self.assertIn("Must-dos: <b>5 of 5</b>", page)
        text = run.reply_text(MEETING, r)
        self.assertIn("Must-dos: 5 of 5", text)
        self.assertNotIn("explaining the pay", text)

    def test_standard_offices_unchanged(self):
        self.assertEqual(grade.build("Rashad Reed")["na"], set())
        self.assertIn("$900 - $1200", grade.build("Joe Logan")["system"])


class VerbiageTest(unittest.TestCase):
    def test_nakechia_as_rafael_counted_it(self):
        # 5 skipped + 2 in the wrong words: the 2 are NOT skips, and they cost
        # half an item each -> 7 of 11 items passed, minus 1 = 55
        r = result(said=NAKECHIA, verbiage=["management", "pay_executive"],
                   schedule=False, wrap_up=False, check_ins=False, commute=False)
        self.assertEqual(len(grade.skipped(r)), 5)
        self.assertEqual(grade.score(r)["score"], 55)
        text = run.reply_text(MEETING, r)
        self.assertIn("⏭️ *Skipped portions: 5*", text)
        self.assertIn("✏️ *Incorrect verbiage: 2* (-0.5 item each)", text)
        self.assertIn('• She said: "six months" @09:08', text)
        self.assertIn("Score: 55/100", text)
        page = doc.build_html(MEETING, "Valentina", r)
        self.assertIn("Incorrect verbiage: 2", page)
        self.assertIn('?timestamp=548">@09:08</a>', page)

    def test_no_verbiage_same_score_as_before(self):
        self.assertEqual(grade.score(result(schedule=False))["score"], 91)

    def test_old_skip_without_kind_is_a_skip(self):
        r = result()
        r["skipped_portions"] = [{"portion": "commute", "note": ""}]
        self.assertEqual(len(grade.skipped(r)), 1)
        self.assertEqual(grade.verbiage(r), [])

    def test_never_below_zero(self):
        everything = [k for k, _ in grade.PORTIONS]
        r = result(verbiage=everything, **{k: kind == "red" for k, _, kind in grade.ITEMS})
        self.assertEqual(grade.score(r)["score"], 0)


class ScheduledTest(unittest.TestCase):
    BOOKED = [{"office": "11280", "time": "10:45 AM", "name": "Nakechia Miller"},
              {"office": "11280", "time": "10:45 AM", "name": "Kevin Brown"},
              {"office": "11280", "time": "12:15 PM", "name": "Ana Julia Avina"}]
    STARTED = dt.datetime(2026, 9, 29, 10, 47, 15, tzinfo=run.fathom.CT)

    def test_matches_a_misheard_name(self):
        slot = appstream.scheduled_for(["Nakeshia Miller"], self.BOOKED, self.STARTED)
        self.assertEqual(slot.strftime("%H:%M"), "10:45")

    def test_other_person_same_first_name_no_match(self):
        self.assertIsNone(appstream.scheduled_for(["Nakechia Johnson"], self.BOOKED,
                                                  self.STARTED))

    def test_reply_shows_scheduled_and_started(self):
        m = dict(MEETING, scheduled_ct=self.STARTED.replace(minute=45, second=0))
        text = run.reply_text(m, result())
        self.assertIn("*Started 10:47 AM CT* · scheduled 10:45 AM · 16 min", text)
        self.assertNotIn("before the scheduled time", text)      # 2 min late is fine

    def test_started_early_is_flagged(self):
        m = dict(MEETING, scheduled_ct=self.STARTED.replace(hour=11, minute=0, second=0))
        text = run.reply_text(m, result())
        self.assertIn("⚠️ Started 12 min before the scheduled time", text)
        self.assertIn("Started 12 min before", doc.build_html(m, "Valentina", result()))

    def test_not_on_appstream_vs_not_read(self):
        self.assertIn("scheduled not on AppStream",
                      run.reply_text(dict(MEETING, scheduled_ct=""), result()))
        self.assertNotIn("scheduled", run.reply_text(MEETING, result()))


    def test_other_offices_only_for_the_unplaced(self):
        """Carlos' office books in 11580, not Raf's three funnels (Eve 10/7)."""
        from unittest import mock
        carlos = dict(MEETING, recording_id=1, recording_start_time="2026-09-29T15:47:15Z")
        raf = dict(MEETING, recording_id=2, recording_start_time="2026-09-29T15:47:15Z")
        graded = {"Isabella": [(carlos, dict(result(), applicants=["Keila Ruiz"]), "")],
                  "Valentina": [(raf, dict(result(), applicants=["Nakechia Miller"]), "")]}
        calls = []

        def booked(day, offices=appstream.OFFICES):
            calls.append(list(offices))
            if offices == appstream.OFFICES:
                return self.BOOKED
            return [{"office": "11580", "time": "10:45 AM", "name": "Keila Ruiz"}]
        with mock.patch.object(appstream, "booked", side_effect=booked),                 mock.patch.object(appstream, "other_offices", return_value=["11580"]):
            run._add_scheduled(dt.date(2026, 9, 29), graded)
        self.assertEqual(calls, [appstream.OFFICES, ["11580"]])
        self.assertEqual(carlos["scheduled_ct"].strftime("%H:%M"), "10:45")
        self.assertEqual(raf["scheduled_ct"].strftime("%H:%M"), "10:45")

    def test_all_placed_reads_no_other_office(self):
        from unittest import mock
        raf = dict(MEETING, recording_id=2, recording_start_time="2026-09-29T15:47:15Z")
        graded = {"Valentina": [(raf, dict(result(), applicants=["Nakechia Miller"]), "")]}
        with mock.patch.object(appstream, "booked", return_value=self.BOOKED) as b:
            run._add_scheduled(dt.date(2026, 9, 29), graded)
        self.assertEqual(b.call_count, 1)

    def test_other_offices_skip_the_funnels(self):
        others = appstream.other_offices()
        self.assertIn("11580", others)                        # Carlos Hidalgo
        self.assertFalse(set(others) & set(appstream.OFFICES))
        self.assertEqual(len(others), len(set(others)))

class RefreshTest(unittest.TestCase):
    """--refresh edits the reply already in the thread instead of adding one."""
    def setUp(self):
        import tempfile
        from pathlib import Path
        self._saved = (run.LEDGER, run.OUT_DIR, run.doc.upload)
        run.OUT_DIR = Path(tempfile.mkdtemp())
        run.LEDGER = run.OUT_DIR / "posted.json"
        run.doc.upload = lambda *a, **k: "https://docs.google.com/d/1"
        run._remember(1, dt.date(2026, 9, 29), "C0C42793AKS", "111.222")

    def tearDown(self):
        run.LEDGER, run.OUT_DIR, run.doc.upload = self._saved

    def test_refresh_edits_in_place(self):
        import sys
        import types
        calls = []

        class Client:
            def chat_update(self, **kw):
                calls.append(("update", kw))
                return {"ok": True}

            def chat_postMessage(self, **kw):
                calls.append(("post", kw))
                return {"ok": True, "ts": "999"}

        fake = types.SimpleNamespace(_client=Client, _ordinal=str,
                                     ensure_named_thread=lambda *a, **k: {"thread_ts": "100.1"})
        saved = sys.modules.get("automations.shared.slack_metrics_post")
        sys.modules["automations.shared.slack_metrics_post"] = fake
        import automations.shared as shared_pkg
        had = getattr(shared_pkg, "slack_metrics_post", None)
        shared_pkg.slack_metrics_post = fake
        try:
            rc = run.post(dt.date(2026, 9, 29), {"Valentina": [(MEETING, result(), "")]},
                          preview=False, refresh=True)
        finally:
            if saved is not None:
                sys.modules["automations.shared.slack_metrics_post"] = saved
            else:
                sys.modules.pop("automations.shared.slack_metrics_post", None)
            if had is not None:
                shared_pkg.slack_metrics_post = had
            else:
                delattr(shared_pkg, "slack_metrics_post")
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in calls], ["update"])
        self.assertEqual((calls[0][1]["channel"], calls[0][1]["ts"]), ("C0C42793AKS", "111.222"))


class FlagTest(unittest.TestCase):
    def test_low_score_tags_camila_and_perla(self):
        low = result(schedule=False, off_script_pay=True, retail=True, nine_to_five=True,
                     mon_fri=True, base_pay=True)
        self.assertLessEqual(grade.score(low)["score"], run.FLAG_AT)
        text = run.reply_text(MEETING, low, tag=True)
        self.assertIn("<@U07FWSYP3NV> <@U07R68ZGHT6>", text)
        # the preview DM never tags
        self.assertNotIn("<@", run.reply_text(MEETING, low, tag=False))

    def test_exactly_50_is_tagged_51_is_not(self):
        from unittest import mock
        base = grade.score(result())
        for pts, tagged in ((50, True), (51, False)):
            with mock.patch.object(run.grade, "score", return_value=dict(base, score=pts)):
                text = run.reply_text(MEETING, result(), tag=True)
            self.assertEqual("<@U07FWSYP3NV>" in text, tagged, pts)


class DocTest(unittest.TestCase):
    def test_reply_links_the_full_audit(self):
        text = run.reply_text(MEETING, result(), doc_link="https://docs.google.com/d/1")
        self.assertIn("📄 <https://docs.google.com/d/1|Full audit>", text)

    def test_doc_has_every_item_and_timestamps_link_to_the_moment(self):
        page = doc.build_html(MEETING, "Valentina", result(schedule=False))
        for _, question, _ in grade.ITEMS:
            self.assertIn(question.split("(")[0][:30], page)
        self.assertIn("Scorecard: <span", page)
        self.assertIn('href="https://fathom.video/share/x?timestamp=250">@4:10</a>', page)
        self.assertIn("Door to door", page)

    def test_doc_name(self):
        self.assertEqual(doc.doc_name(MEETING, "Valentina"),
                         "Valentina — Sep 29 10:47 AM — 1st rd audit")


class DueTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self._saved = (run.LEDGER, run.OUT_DIR)
        run.OUT_DIR = Path(tempfile.mkdtemp())
        run.LEDGER = run.OUT_DIR / "posted.json"

    def tearDown(self):
        run.LEDGER, run.OUT_DIR = self._saved

    def test_gate(self):
        import datetime as dt
        at = lambda d, h: dt.datetime(2026, 9, d, h, 0, tzinfo=run.fathom.CT)
        self.assertFalse(run.due(at(29, 17)))          # Tuesday before 6 PM
        self.assertTrue(run.due(at(29, 18)))           # Tuesday 6 PM
        self.assertFalse(run.due(at(26, 19)))          # Saturday
        run._mark_day_done(dt.date(2026, 9, 29))
        self.assertFalse(run.due(at(29, 19)))          # already posted today


class WatchTest(unittest.TestCase):
    """Eve's one-day DM about a watched Zoom (Carlos' new one, 10/6)."""
    EMAIL = "carlosoffice@arsinterviewsservice.com"
    DAY = dt.date(2026, 10, 6)

    def setUp(self):
        import tempfile
        from pathlib import Path
        self._saved = (run.LEDGER, run.OUT_DIR, run.WATCH)
        run.OUT_DIR = Path(tempfile.mkdtemp())
        run.LEDGER = run.OUT_DIR / "posted.json"
        run.WATCH = {self.EMAIL: ("la Zoom nueva de Carlos", "2026-10-06")}

    def tearDown(self):
        run.LEDGER, run.OUT_DIR, run.WATCH = self._saved

    def _carlos(self, rid):
        return dict(MEETING, recording_id=rid, recorded_by={"name": "Carlos", "email": self.EMAIL})

    def test_counts_only_that_zoom(self):
        graded = {"Miroslava": [(self._carlos(1), result(), ""), (self._carlos(2), result(), ""),
                                (self._carlos(3), None, "empty")],
                  "Valentina": [(MEETING, result(), "")]}
        text = run.watch_text(self.DAY, graded, self.EMAIL, "la Zoom nueva de Carlos")
        self.assertIn("2 entrevista(s) auditada(s)", text)
        self.assertIn("10/6", text)

    def test_nothing_recorded_is_news(self):
        self.assertIn("0 entrevistas", run.watch_text(self.DAY, {}, self.EMAIL, "x"))
        ungraded = {"Carlos": [(self._carlos(1), None, "empty")]}
        self.assertIn("ninguna auditada", run.watch_text(self.DAY, ungraded, self.EMAIL, "x"))

    def test_a_later_tick_counts_what_an_earlier_one_posted(self):
        """10/6 21:39: the retry tick had none of Carlos' left (6 PM posted
        them) and DMed "0 entrevistas"."""
        from unittest import mock
        run._remember(1, self.DAY, "C1", "1.1")
        run._remember(2, self.DAY, "C1", "1.2")
        run._remember(9, dt.date(2026, 10, 5), "C1", "1.3")      # other day
        lines = [{}] * run.MIN_TRANSCRIPT_LINES
        day = [dict(self._carlos(1), transcript=lines), dict(self._carlos(2), transcript=lines),
               dict(self._carlos(9), transcript=lines), dict(MEETING, recording_id=3)]
        with mock.patch.object(run.fathom, "meetings_on", return_value=day):
            n = run._posted_earlier(self.DAY, {}, self.EMAIL)
        self.assertEqual(n, 2)
        self.assertIn("2 entrevista(s) auditada(s)",
                      run.watch_text(self.DAY, {}, self.EMAIL, "x", earlier=n))

    def test_sent_once_and_only_that_day(self):
        from unittest import mock
        from automations.shared import slack_metrics_post as smp
        client = mock.Mock()
        client.conversations_open.return_value = {"channel": {"id": "D1"}}
        with mock.patch.object(smp, "_client", return_value=client):
            run._watch_dm(dt.date(2026, 10, 5), {})           # not its day
            self.assertEqual(client.chat_postMessage.call_count, 0)
            run._watch_dm(self.DAY, {})
            run._watch_dm(self.DAY, {})                        # a later tick
        self.assertEqual(client.chat_postMessage.call_count, 1)
        self.assertEqual(client.chat_postMessage.call_args.kwargs["channel"], "D1")


class BoardPostTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self._saved = (run.LEDGER, run.OUT_DIR)
        run.OUT_DIR = Path(tempfile.mkdtemp())
        run.LEDGER = run.OUT_DIR / "posted.json"

    def tearDown(self):
        run.LEDGER, run.OUT_DIR = self._saved

    DAY = dt.date(2026, 10, 5)
    ROWS = [{"interviewer": "Valentina", "date": "2026-10-05", "score": 45},
            {"interviewer": "Valentina", "date": "2026-10-05", "score": 50},   # avg 48
            {"interviewer": "Elfina", "date": "2026-10-05", "score": 50},      # 50 = not low
            {"interviewer": "Nakechia", "date": "2026-10-05", "score": 36},
            {"interviewer": "Gabby", "date": "2026-10-02", "score": 20}]       # other day

    def test_low_scorers_by_day_average(self):
        self.assertEqual(run.low_scorers(self.ROWS, self.DAY),
                         [("Nakechia", 36, 1), ("Valentina", 48, 2)])

    def test_day_reply_tags_and_lists(self):
        text = run.board_day_text(self.DAY, self.ROWS)
        self.assertIn("<@U07FWSYP3NV>", text)
        self.assertIn("<@U07R68ZGHT6>", text)
        self.assertIn("Mon 10/5", text)
        self.assertIn("49 pts or under", text)
        self.assertIn("• Nakechia — 36 pts (1 interview)", text)
        self.assertIn("• Valentina — 48 pts (2 interviews)", text)
        self.assertNotIn("Elfina", text)
        self.assertIn("Nobody", run.board_day_text(self.DAY, []))

    def test_one_pinned_thread_a_week_one_reply_a_day(self):
        from unittest import mock
        from automations.shared import slack_metrics_post as smp
        client = mock.Mock()
        n = iter(range(100))
        client.chat_postMessage.side_effect = lambda **kw: {"ok": True, "ts": f"1.{next(n)}"}
        with mock.patch.object(smp, "_client", return_value=client):
            run._board_post(self.DAY, "", self.ROWS)                  # board not written
            run._board_post(self.DAY, "https://sheet/x", self.ROWS)   # Mon: thread + reply
            run._board_post(self.DAY, "https://sheet/x", self.ROWS)   # a rerun: nothing
            run._board_post(dt.date(2026, 10, 6), "https://sheet/x", [])   # Tue: reply only
            run._board_post(dt.date(2026, 10, 12), "https://sheet/y", [])  # next week
        calls = [c.kwargs for c in client.chat_postMessage.call_args_list]
        self.assertEqual(len(calls), 5)
        self.assertNotIn("thread_ts", calls[0])
        self.assertIn("https://sheet/x", calls[0]["text"])
        self.assertEqual(calls[1]["thread_ts"], "1.0")
        self.assertEqual(calls[2]["thread_ts"], "1.0")                # Tue in Monday's thread
        self.assertNotIn("thread_ts", calls[3])                        # new week, new thread
        self.assertEqual(calls[4]["thread_ts"], "1.3")
        self.assertEqual([c.kwargs["timestamp"] for c in client.pins_add.call_args_list],
                         ["1.0", "1.3"])
        client.pins_remove.assert_called_with(channel=run.CHANNEL_ID, timestamp="1.0")

    def test_no_pin_permission_still_posts(self):
        from unittest import mock
        from automations.shared import slack_metrics_post as smp
        client = mock.Mock()
        client.chat_postMessage.return_value = {"ok": True, "ts": "1.0"}
        client.pins_add.side_effect = RuntimeError("missing_scope")
        with mock.patch.object(smp, "_client", return_value=client):
            run._board_post(self.DAY, "https://sheet/x", self.ROWS)
        self.assertEqual(client.chat_postMessage.call_count, 2)


class DocsOnlyTest(unittest.TestCase):
    def test_writes_docs_and_never_touches_slack(self):
        from unittest import mock
        graded = {"Valentina": [(MEETING, result(), ""), (MEETING, None, "empty")]}
        with mock.patch.object(run, "build", return_value=graded),                 mock.patch.object(doc, "upload", return_value="https://docs/x") as up,                 mock.patch.object(run, "post") as posted,                 mock.patch.object(run, "_mark_day_done") as marked:
            rc = run.main(["--date", "2026-09-22", "--post", "--docs-only"])
        self.assertEqual(rc, 0)
        self.assertEqual(up.call_count, 1)          # the ungraded one gets no doc
        posted.assert_not_called()
        marked.assert_not_called()                  # a past day stays un-posted


class ZoomsTest(unittest.TestCase):
    def test_tab_parsed_by_labels(self):
        z = zooms.parse(ZOOMS_TAB)
        self.assertEqual(z["arszooma@gmail.com"],
                         {"zoom": "ZOOM 1", "morning": "Jamis Garay",
                          "afternoon": "Jamis Garay", "key": "KEY1"})   # all day
        self.assertEqual(z["arszoomc@gmail.com"]["afternoon"], "Cyrus Wade")
        self.assertEqual(z["arszoomh@gmail.com"]["key"], "")            # a webhook secret

    def test_owner_by_time_of_day(self):
        z3 = dict(MEETING, recorded_by={"email": "ArsZoomC@gmail.com"})
        # 11:15 = last morning slot, 11:45 = first afternoon one (Camila)
        am = dt.datetime(2026, 10, 1, 11, 18, tzinfo=run.fathom.CT)
        self.assertEqual(zooms.owner(z3, am), "Joe Logan")
        self.assertEqual(zooms.owner(z3, am.replace(minute=41)), "Cyrus Wade")
        self.assertEqual(zooms.owner(dict(MEETING, recorded_by={"email": "x@y.com"}), am), "")

    def test_reply_and_doc_name_the_office(self):
        m = dict(MEETING, owner="Joe Logan")
        self.assertIn("*Joe Logan's office* · *Started", run.reply_text(m, None, skipped="x"))
        self.assertNotIn("office", run.reply_text(MEETING, None, skipped="x"))

    def test_sheet_keys_only_when_asked(self):
        from automations.first_round_scorecards import fathom
        real = fathom._file_keys
        fathom._file_keys = lambda: ["FILEKEY"]
        try:
            self.assertEqual(fathom.api_keys(with_sheet=False), ["FILEKEY"])
            self.assertEqual(fathom.api_keys(with_sheet=True), ["FILEKEY", "KEY1", "KEY3", "CARLOSKEY0123456789"])
        finally:
            fathom._file_keys = real
        self.assertTrue(fathom.SHEET_KEYS_LIVE)       # every Zoom in the channel (Eve 10/1)


if __name__ == "__main__":
    unittest.main()


class BoardTest(unittest.TestCase):
    def test_parse_doc(self):
        from automations.first_round_scorecards import board
        text = ("Interviewer: Amy (ARS ZOOM 4) · Office: Ellen Dent · Applicants: x\n"
                "Scorecard: 42 / 100 🔴")
        d = board.parse_doc(text)
        self.assertEqual((d["score"], d["office"]), (42, "Ellen Dent"))
        self.assertIsNone(board.parse_doc("nothing here")["score"])

    def test_table_averages_and_order(self):
        from automations.first_round_scorecards import board
        mon = dt.date(2026, 9, 28)
        rows = [{"interviewer": "Amy", "date": "2026-09-28", "score": 40, "office": "Ellen Dent"},
                {"interviewer": "Amy", "date": "2026-09-28", "score": 50, "office": "Ellen Dent"},
                {"interviewer": "Amy", "date": "2026-10-01", "score": 60, "office": "Ellen Dent"},
                {"interviewer": "ZOOM 4", "date": "2026-10-01", "score": 90, "office": ""},
                {"interviewer": "Eva", "date": "2026-10-02", "score": 70, "office": "Tre Mitchell"}]
        lines = board.table(mon, rows)
        # people by week average, an unnamed Zoom last even with a higher score
        self.assertEqual([p["name"] for p in lines], ["Eva", "Amy", "ZOOM 4"])
        amy = lines[1]
        self.assertEqual(amy["days"], [45, None, None, 60, None])
        self.assertEqual((amy["week"], amy["n"]), (50, 3))
        grid = board.values(mon, lines)
        self.assertEqual(grid[-1][1], "TEAM")
        self.assertEqual(grid[-1][8:10], [62, 5])     # (40+50+60+90+70)/5

    def test_monday(self):
        from automations.first_round_scorecards import board
        self.assertEqual(board.monday(dt.date(2026, 10, 2)), dt.date(2026, 9, 28))

    def test_tab_order_newest_first(self):
        from automations.first_round_scorecards import board
        tabs = ["WE 9.27", "WE 10.4", "Notes"]
        # an old week written last must not land in front of the newer one
        self.assertEqual(board.tab_index(dt.date(2026, 9, 21), tabs), 1)
        self.assertEqual(board.tab_index(dt.date(2026, 9, 28), tabs), 0)
        self.assertEqual(board.tab_name(dt.date(2026, 9, 28)), "WE 10.4")
        self.assertEqual(board.tab_week("WE 1.3", dt.date(2026, 12, 28)), dt.date(2026, 12, 28))

    def test_parse_flags_missed_coaching(self):
        from automations.first_round_scorecards import board
        text = ("Scorecard: 50 / 100 🔴\nCoaching points:\n"
                "* Do not skip the schedule. Say full time.\n* Use the exact wrap-up.\n"
                "⏭️ Skipped portions: 1\n1. \"All interactions...\"\n"
                "🚩 Red flags — should NOT happen\n"
                "5. Did she quote pay different from the script? — YES 🚩\n"
                "1. Did she say the job is inside a retail store? — NO\n"
                "✅ Must-dos — should happen\n"
                "8. Did she cover the schedule (full time, in person, day shifts, 40 hrs, Saturdays)? — NO\n"
                "9. Did she do the wrap-up script? — YES\n")
        d = board.parse_doc(text)
        self.assertEqual(d["flags"], ["pay different from the script"])
        self.assertEqual(d["missed"], ["schedule section"])
        self.assertEqual(d["coaching"], ["Do not skip the schedule. Say full time.",
                                         "Use the exact wrap-up."])
        line = board.table(dt.date(2026, 9, 21), [
            {"interviewer": "Amy", "date": "2026-09-21", "time": "09:00", "score": 50,
             "office": "", **d},
            {"interviewer": "Amy", "date": "2026-09-22", "time": "09:00", "score": 60,
             "office": "", "flags": ["pay different from the script"], "missed": [],
             "coaching": ["Keep it up!"]}])[0]
        self.assertEqual(line["flags"], "pay different from the script ×2")
        self.assertEqual(line["missed"], "schedule section ×1")
        self.assertEqual(line["coaching"], "• Keep it up!")     # the latest interview's

    def test_same_person_candidates_and_merge(self):
        from automations.first_round_scorecards import board
        r = lambda who, office: {"interviewer": who, "date": "2026-10-01", "time": "", "score": 50,
                                 "office": office, "flags": [], "missed": [], "coaching": []}
        rows = [r("Eva", "Tre Mitchell")] * 3 + [r("Iva", "Tre Mitchell"), r("Amy", "Ellen Dent"),
                r("Ana", "Tre Mitchell"), r("ZOOM 4", "Tre Mitchell"), r("Eve", "Other Office")]
        c = board.candidates(rows, [])
        # same office + similar name; a Zoom row or another office never pairs
        self.assertIn(["Eva", "Iva", "Tre Mitchell", 3, 1, ""], c)
        self.assertFalse(any("ZOOM 4" in x[:2] or "Eve" in x[:2] for x in c))
        # already asked (either order) = not asked again
        self.assertNotIn("Iva", [x[1] for x in board.candidates(rows, [["Iva", "Eva", "", "", "", "NO"]])])
        m = board.merges([["Eva", "Iva", "", "", "", "YES"], ["Eva", "Ana", "", "", "", "no"],
                          ["Eve", "Eva", "", "", "", "yes"]])
        self.assertEqual(m, {"Iva": "Eve", "Eva": "Eve"})        # chains resolve
        merged = board.apply_merges(rows, {"Iva": "Eva"})
        self.assertEqual(sum(x["interviewer"] == "Eva" for x in merged), 4)

    def test_same_person_one_row_per_name_and_accents(self):
        from automations.first_round_scorecards import board
        r = lambda who: {"interviewer": who, "date": "2026-10-01", "time": "", "score": 50,
                         "office": "Salik Mallick", "flags": [], "missed": [], "coaching": []}
        rows = [r("Elfina")] * 9 + [r("Alfina"), r("Lucina"), r("Ulfina")]
        self.assertEqual([x[:2] for x in board.candidates(rows, [])],
                         [["Elfina", "Alfina"], ["Elfina", "Lucina"], ["Elfina", "Ulfina"]])
        got = board.apply_merges([r("Angela"), r("Angela"), r("Ángela")], {})
        self.assertEqual({x["interviewer"] for x in got}, {"Angela"})
