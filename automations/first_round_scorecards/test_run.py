"""python -m unittest automations.first_round_scorecards.test_run"""
import datetime as dt
import unittest

from automations.first_round_scorecards import appstream, doc, grade, run, zooms

# Camila's ZOOMS INFO tab, trimmed: tests never read the real Sheet
ZOOMS_TAB = [
    ["33", "ZOOM 1", "ZOOM 3", "ZOOM 8"],
    ["", "504 877 4019", "711 240 6133", "660 341 8230"],
    ["MORNINGS", "Jamis Garay", "Joe Logan", "Jennifer Figueroa"],
    ["", "", "", ""],
    ["AFTERNOONS", "", "", ""],
    ["", "", "Cyrus Wade", "Mercy Ohiokhai"],
    ["", "ZOOM 1", "ZOOM 3 ", "ZOOM 8"],
    ["", "arszooma@gmail.com", "arszoomc@gmail.com", "arszoomh@gmail.com"],
    ["", "pw", "pw", "pw"],
    ["", "KEY1", "KEY3", "whsec_abc"],
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
            self.assertEqual(fathom.api_keys(with_sheet=True), ["FILEKEY", "KEY1", "KEY3"])
        finally:
            fathom._file_keys = real
        self.assertTrue(fathom.SHEET_KEYS_LIVE)       # every Zoom in the channel (Eve 10/1)


if __name__ == "__main__":
    unittest.main()
