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
        self.assertNotIn("Headshot Photo", p.cols)

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

    def test_everything_done_ticks_all_four(self):
        self.assertEqual(sorted(sweep.earned(self._cara(), ALL_DONE)),
                         sorted(config.COLUMNS))

    def test_only_true_ticks_false_and_unread_do_not(self):
        st = dict(ALL_DONE, **{"Digi Docs": False, "UID Request": None})
        self.assertEqual(sorted(sweep.earned(self._cara(), st)),
                         ["Onboarding Quizzes", "Owner Submit"])

    def test_already_ticked_is_not_rewritten(self):
        ben = [p for p in sweep.people(_tab()) if p.first == "Ben"][0]
        self.assertNotIn("Digi Docs", sweep.earned(ben, ALL_DONE))


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
                          "UID Request": True, "Owner Submit": False})

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
    c[12] = {"text": "\u2713 Photo", "html": '<span class="badge bg-success">'}
    c[14] = {"text": "RES-ATT\n09/21/26\n2:32 PM", "html": ""}
    return c


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
