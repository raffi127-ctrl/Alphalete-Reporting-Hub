"""Offline tests — no OwnerVille, no Sheets.

    python -m unittest automations.obcl_ov_sweep.test_sweep
"""
import unittest

from automations.obcl_ov_sweep import config, ov_table, sweep

HEAD = ["#", "2ND Round Interviewer", "Start Time", "Name", "Last Name",
        "Email", "Final Status", "Digi Docs", "Onboarding Quizzes",
        "Blue Ink", "Headshot Photo", "UID Request", "Owner Submit"]


def _row(first, last, fs="", dd="FALSE", oq="FALSE", uid="FALSE",
         own="FALSE"):
    return ["1", "Leader", "1:00", first, last, f"{first}@x.com", fs,
            dd, oq, "TRUE", "TRUE", uid, own]


def _tab():
    return [
        ["9/14/2026"], HEAD,
        _row("Ann", "Old", dd="TRUE", oq="TRUE", uid="TRUE", own="TRUE"),
        _row("Ben", "Carried", dd="TRUE"),
        [],
        ["9/21/2026"], HEAD,
        _row("Cara", "New"),
        _row("Dan", "Quit", fs="Quit before classroom"),
        _row("Eve", "Owner", fs="Owner submitted"),
    ]


ALL_DONE = {c: True for c in config.COLUMNS}


class Roster(unittest.TestCase):
    def test_reads_every_chart_including_last_weeks(self):
        names = [p.name for p in sweep.people(_tab())]
        self.assertEqual(names, ["Ann Old", "Ben Carried", "Cara New",
                                 "Dan Quit", "Eve Owner"])

    def test_columns_found_by_label_and_blue_ink_not_mapped(self):
        p = sweep.people(_tab())[0]
        self.assertEqual(p.cols["Digi Docs"], 8)
        self.assertEqual(p.cols["Owner Submit"], 13)
        self.assertNotIn("Blue Ink", p.cols)
        self.assertEqual(p.cols["Headshot Photo"], 11)

    def test_to_check_skips_finished_gone_and_owner_submitted(self):
        names = [p.name for p in sweep.to_check(sweep.people(_tab()))]
        self.assertEqual(names, ["Ben Carried", "Cara New"])

    def test_owner_submit_ticked_is_skipped_too(self):
        tab = _tab()
        tab[7] = _row("Cara", "New", own="TRUE")
        names = [p.name for p in sweep.to_check(sweep.people(tab))]
        self.assertNotIn("Cara New", names)


class Earned(unittest.TestCase):
    def _cara(self):
        return [p for p in sweep.people(_tab()) if p.first == "Cara"][0]

    def test_everything_done_ticks_every_open_column(self):
        # Cara's Headshot is already ticked on the sheet, so it isn't re-ticked.
        self.assertEqual(sorted(sweep.earned(self._cara(), ALL_DONE)),
                         sorted(set(config.COLUMNS) - {"Headshot Photo"}))

    def test_only_true_ticks_false_and_unread_do_not(self):
        st = dict(ALL_DONE, **{"Digi Docs": False, "UID Request": None})
        self.assertEqual(sorted(sweep.earned(self._cara(), st)),
                         ["Onboarding Quizzes", "Owner Submit"])

    def test_already_ticked_is_not_rewritten(self):
        ben = [p for p in sweep.people(_tab()) if p.first == "Ben"][0]
        self.assertNotIn("Digi Docs", sweep.earned(ben, ALL_DONE))


class Paint(unittest.TestCase):
    def test_every_box_green_or_red_hand_ticks_green_gone_untouched(self):
        plan = sweep.paint_plan(sweep.people(_tab()),
                                ticked_now=[(8, "Digi Docs")],
                                ready_rows=[8])
        got = {(p.name, c): col for p, c, col in plan}
        self.assertEqual(got[("Ann Old", "Owner Submit")], config.DONE_GREEN)
        self.assertEqual(got[("Ben Carried", "Digi Docs")], config.DONE_GREEN)
        self.assertEqual(got[("Ben Carried", "UID Request")],
                         config.NOT_FOUND_RED)
        self.assertEqual(got[("Cara New", "Digi Docs")], config.DONE_GREEN)
        self.assertEqual(got[("Cara New", "Owner Submit")], config.READY_BLUE)
        self.assertEqual(got[("Cara New", "UID Request")], config.NOT_FOUND_RED)
        self.assertFalse(any(n == "Dan Quit" for n, _ in got))

    def test_bg_pending_owner_submit_is_yellow(self):
        plan = sweep.paint_plan(sweep.people(_tab()), bg_pending_rows=[8])
        got = {(p.name, c): col for p, c, col in plan}
        self.assertEqual(got[("Cara New", "Owner Submit")],
                         config.BG_PENDING_YELLOW)


class SheetBgPending(unittest.TestCase):
    def _person(self, fs="", bg="Taken - Pending", own="FALSE", dd="TRUE"):
        head = HEAD + ["BG Status : Last Checked"]
        row = _row("Quincy", "Williams", fs=fs, dd=dd, oq="TRUE", uid="TRUE",
                   own=own) + [bg]
        return sweep.people([["9/21/2026"], head, row])

    def _owner_colour(self, **kw):
        plan = sweep.paint_plan(self._person(**kw))
        return [col for _, c, col in plan if c == "Owner Submit"][0]

    def test_taken_pending_all_else_done_is_yellow(self):
        self.assertEqual(self._owner_colour(), config.BG_PENDING_YELLOW)

    def test_pending_on_ov_final_status_is_yellow(self):
        self.assertEqual(self._owner_colour(fs="Pending on OV", bg="Passed"),
                         config.BG_PENDING_YELLOW)

    def test_unperformable_all_else_done_is_yellow(self):
        self.assertEqual(self._owner_colour(bg="Unperformable"),
                         config.BG_PENDING_YELLOW)

    def test_blue_ink_open_does_not_block_yellow(self):
        head = HEAD + ["BG Status : Last Checked"]
        row = _row("David", "Dean", dd="TRUE", oq="TRUE", uid="TRUE") + [
            "Taken - Pending"]
        row[HEAD.index("Blue Ink")] = "FALSE"
        plan = sweep.paint_plan(sweep.people([["9/21/2026"], head, row]))
        self.assertEqual([col for _, c, col in plan if c == "Owner Submit"],
                         [config.BG_PENDING_YELLOW])

    def test_failed_bg_stays_red(self):
        self.assertEqual(self._owner_colour(bg="Failed"), config.NOT_FOUND_RED)

    def test_another_box_open_stays_red(self):
        self.assertEqual(self._owner_colour(dd="FALSE"), config.NOT_FOUND_RED)

    def test_sheet_only_never_reds_owner_submit(self):
        plan = sweep.paint_plan(self._person(dd="FALSE"), sheet_only=True)
        self.assertEqual([c for _, c, _ in plan if c == "Owner Submit"], [])

    def test_ticked_is_green(self):
        self.assertEqual(self._owner_colour(own="TRUE"), config.DONE_GREEN)


class NoShowAndStatus(unittest.TestCase):
    HEAD2 = HEAD[:6] + ["Location"] + HEAD[6:]

    def _p(self, fs="", loc="", own="FALSE", blue="TRUE", date="9/14/2026",
           dd="FALSE"):
        row = _row("Sung", "Par", fs=fs, own=own, dd=dd)
        row = row[:6] + [loc] + row[6:]
        row[self.HEAD2.index("Blue Ink")] = blue
        return sweep.people([[date], self.HEAD2, row])[0]

    def test_blank_status_and_location_after_start_is_a_no_show(self):
        import datetime as d
        p = self._p(blue="FALSE")
        for c in p.ticked:
            p.ticked[c] = False
        self.assertTrue(sweep.no_show(p, d.date(2026, 9, 21)))
        self.assertEqual(sweep.to_check([p]), [])
        self.assertEqual(sweep.paint_plan([p]), [])

    def test_something_ticked_is_not_a_no_show(self):
        import datetime as d
        head = self.HEAD2
        row = _row("Govany", "Torres", dd="TRUE", oq="TRUE", uid="TRUE")
        row = row[:6] + [""] + row[6:]
        p = sweep.people([["9/14/2026"], head, row])[0]
        self.assertFalse(sweep.no_show(p, d.date(2026, 9, 21)))

    def test_start_day_itself_is_not_a_no_show(self):
        import datetime as d
        self.assertFalse(sweep.no_show(self._p(date="9/21/2026"),
                                       d.date(2026, 9, 21)))

    def test_owner_submit_and_blue_ink_sets_owner_submitted(self):
        p = self._p(fs="Showed Up To CR", loc="Dallas", own="TRUE")
        self.assertEqual(sweep.status_updates([p]), [p])

    def test_missing_blue_ink_keeps_status(self):
        p = self._p(fs="Needs BlueInk", loc="Dallas", own="TRUE", blue="FALSE")
        self.assertEqual(sweep.status_updates([p]), [])

    def test_later_statuses_never_overwritten(self):
        for fs in ("Activations Email sent", "MISSING ID", "Owner submitted",
                   "Sara+ Received"):
            p = self._p(fs=fs, loc="Dallas", own="TRUE")
            self.assertEqual(sweep.status_updates([p]), [], fs)

    def test_ticked_this_pass_counts(self):
        p = self._p(fs="Pending on OV", loc="Dallas")
        self.assertEqual(sweep.status_updates([p], [(p.row, "Owner Submit")]),
                         [p])


VP_HEADS = ["Name", "Contact", "Login Created", "Onboarding Documents",
            "Background Check", "Drug Test", "FTC DIRECTV Compliance Training",
            "AT&T Protective Advantage Course", "AT&T Broadband Facts",
            "AT&T Protecting CPNI", "AT&T Compliance \u2013 2023",
            "2024 Consent Decree Manual CPNI/SPI", "Upload Documents",
            "AT&T UID Request", "Service", "Supplement", "Owner Submit",
            "Badge", "SARA Plus", "Progress"]
DONE = {"text": "09/21/26\n11:00 AM", "html": '<span class="badge bg-success">'}


def _marqoun():
    """Megan's screenshot row, 2026-09-21: docs + all six courses green, UID
    Requested, Owner Submit blank."""
    c = [{"text": "", "html": ""} for _ in VP_HEADS]
    for i in range(6, 12):
        c[i] = dict(DONE)
    c[3] = dict(DONE)
    c[4] = {"text": "Pending", "html": '<span class="badge bg-warning">'}
    c[13] = {"text": "Requested\n09/21/26\n11:12 AM", "html": ""}
    return c


class TableRead(unittest.TestCase):
    def test_megans_screenshot_row(self):
        self.assertEqual(ov_table.done_columns(VP_HEADS, _marqoun()),
                         {"Digi Docs": True, "Onboarding Quizzes": True,
                          "UID Request": True, "Owner Submit": False,
                          "Headshot Photo": False})

    def test_one_open_course_blocks_quizzes(self):
        c = _marqoun()
        c[9] = {"text": "", "html": '<i class="fa fa-times text-danger">'}
        self.assertFalse(ov_table.done_columns(VP_HEADS, c)["Onboarding Quizzes"])

    def test_pending_and_red_are_not_done(self):
        self.assertFalse(ov_table.cell_done("Pending 09/21/26"))
        self.assertFalse(ov_table.cell_done("09/21/26", '<span class="badge-danger">'))
        self.assertFalse(ov_table.cell_done(""))

    def test_missing_header_is_unread_not_false(self):
        heads = [h for h in VP_HEADS if h != "Owner Submit"]
        c = _marqoun()[:len(heads)]
        self.assertIsNone(ov_table.done_columns(heads, c)["Owner Submit"])


def _all_but_submit():
    c = _marqoun()
    c[2] = dict(DONE)                                   # Login Created
    c[4] = dict(DONE)                                   # Background Check
    c[5] = dict(DONE)                                   # Drug Test
    c[12] = {"text": "Photo", "html": '<span class="badge bg-success">'}
    c[14] = {"text": "RES-ATT\n09/21/26\n2:32 PM", "html": ""}
    return c


class OwnerSubmitGate(unittest.TestCase):

    def test_section_states_and_blockers(self):
        from automations.obcl_ov_sweep import owner_submit as os_

        class M:
            def inner_text(self):
                return (" BACKGROUND CHECK\nCOMPLETED\n DRUG TEST\nPENDING\n"
                        " OWNER SUBMIT\nREQUIRED ACTION\n BADGE\n"
                        "REQUIRED ACTION\n SARA PLUS\nOPTIONAL\nSave Changes")
        st = os_.section_states(M())
        self.assertEqual(st["OWNER SUBMIT"], "REQUIRED ACTION")
        self.assertEqual(os_.blockers(st), ["DRUG TEST=PENDING"])

    def test_closed_gate_walks_dry_even_on_a_live_pass(self):
        from unittest import mock
        from automations.obcl_ov_sweep import run as r
        calls = []

        def fake_submit(page, name, *, dry_run):
            calls.append(dry_run)
            return "would submit", name

        class Ctx:
            def __enter__(self):
                return object()

            def __exit__(self, *a):
                return False
        p = sweep.people(_tab())[2]
        ready, writes = [p], []
        with mock.patch("automations.obcl_ov_sweep.owner_submit.submit_one",
                        fake_submit), \
             mock.patch("automations.shared.tableau_patchright."
                        "ownerville_session", lambda **k: Ctx()):
            with mock.patch.object(config, "OWNER_SUBMIT_LIVE", False):
                r._submit(ready, writes, live=True)
        self.assertEqual(calls, [True])        # dry, despite live=True
        self.assertEqual(writes, [])           # nothing ticked
        self.assertEqual(ready, [p])           # still blue


class FailureCaption(unittest.TestCase):
    def test_failed_submit_is_named_in_the_text(self):
        from automations.obcl_ov_sweep import snapshot as sn
        made = [(sn.GROUPS[0], 21, None), (sn.GROUPS[1], 1, None)]
        cap = sn.caption(made, [("Jane Doe", "confirm box would not tick")])
        self.assertIn("❌ Couldn't owner submit in OV: Jane Doe — ready to go "
                      "but needs done manually", cap)
        self.assertNotIn("confirm box", cap)
        self.assertTrue(cap.startswith("OBCL update\n✅ 21 owner submitted"))

    def test_no_failures_no_extra_line(self):
        from automations.obcl_ov_sweep import snapshot as sn
        self.assertNotIn("❌", sn.caption([(sn.GROUPS[0], 3, None)]))


class OwnerSubmitReview(unittest.TestCase):
    def test_review_in_progress_counts_as_submitted(self):
        c = _all_but_submit()
        c[16] = {"text": " Review in Progress",
                 "html": '<div class="label label-default"><i class="fa fa-check">'}
        self.assertTrue(ov_table.done_columns(VP_HEADS, c)["Owner Submit"])


class Photo(unittest.TestCase):
    def test_green_pill_uploaded_red_or_orange_missing(self):
        self.assertTrue(ov_table.photo_uploaded(
            "Photo", '<span class="badge bg-success"><i class="fa fa-check">'))
        self.assertFalse(ov_table.photo_uploaded(
            "Photo", '<span class="badge bg-danger">'))
        self.assertFalse(ov_table.photo_uploaded(
            "Photo", '<span class="badge bg-warning">'))
        self.assertFalse(ov_table.photo_uploaded("", ""))

    def test_uploaded_photo_ticks_headshot(self):
        c = _marqoun()
        c[12] = {"text": "Photo", "html": '<span class="badge bg-success">'}
        self.assertTrue(ov_table.done_columns(VP_HEADS, c)["Headshot Photo"])


class ReadyForOwnerSubmit(unittest.TestCase):
    def test_megans_row_is_not_ready_background_check_pending(self):
        self.assertFalse(ov_table.ready_for_owner_submit(VP_HEADS, _marqoun()))

    def test_everything_green_is_ready_photo_needs_no_date(self):
        self.assertTrue(ov_table.ready_for_owner_submit(VP_HEADS,
                                                        _all_but_submit()))

    def test_supplement_blank_does_not_block(self):
        c = _all_but_submit()
        c[15] = {"text": "", "html": ""}
        self.assertTrue(ov_table.ready_for_owner_submit(VP_HEADS, c))

    def test_background_check_must_be_passed(self):
        for bad in ({"text": "Pending", "html": ""},
                    {"text": "Failed", "html": ""},                 # no date
                    {"text": "09/21/26", "html": '<i class="text-danger">'},
                    {"text": "", "html": ""}):
            c = _all_but_submit()
            c[4] = bad
            self.assertFalse(ov_table.ready_for_owner_submit(VP_HEADS, c), bad)

    def test_bg_pending_everything_else_done_is_yellow_state(self):
        c = _all_but_submit()
        c[4] = {"text": "Pending", "html": '<span class="badge bg-warning">'}
        self.assertEqual(ov_table.owner_submit_state(VP_HEADS, c), "bg_pending")
        c[5] = {"text": "", "html": ""}          # drug test open too
        self.assertEqual(ov_table.owner_submit_state(VP_HEADS, c), "")

    def test_ready_state(self):
        self.assertEqual(ov_table.owner_submit_state(VP_HEADS,
                                                     _all_but_submit()), "ready")

    def test_missing_header_is_unread(self):
        heads = [h for h in VP_HEADS if h != "Drug Test"]
        self.assertIsNone(ov_table.ready_for_owner_submit(heads,
                                                          _all_but_submit()))


class FullyOnboarded(unittest.TestCase):
    """Da'ryan Stringer, Megan's screenshot 2026-09-21 — the finished shape."""

    def _row(self):
        c = _all_but_submit()
        c[16] = {"text": "\u2713 Approved\n09/21/26\n12:00 AM",
                 "html": '<span class="badge bg-success">'}
        return c

    def test_all_four_columns_done(self):
        self.assertEqual(ov_table.done_columns(VP_HEADS, self._row()),
                         {c: True for c in config.COLUMNS})

    def test_ready_too_but_run_ticks_green_instead_of_blue(self):
        # ready is True; run.py only paints blue when Owner Submit is NOT
        # being ticked in the same pass.
        self.assertTrue(ov_table.ready_for_owner_submit(VP_HEADS, self._row()))


if __name__ == "__main__":
    unittest.main()
