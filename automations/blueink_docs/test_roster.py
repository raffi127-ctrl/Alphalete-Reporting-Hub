"""Parser tests -- the two things that would quietly send docs to the wrong
person: dropping a section, and mis-reading a status column.

    python -m pytest automations/blueink_docs/test_roster.py -q
"""
from automations.blueink_docs.roster import (NewStart,
                                             final_status_is_unrecognised,
                                             normalize_phone, parse_tab,
                                             _tab_date)

HEADER = ["#", "2ND Round Interviewer", "Trainer", "Name", "Last Name",
          "Contact Added", "Email", "Phone", "Location", "Final Status",
          "\nBG Status : Last Checked ", "Digi Docs", "Friday Confirmation"]


def _row(first, last, email, phone="8173955555", final="", bg="Passed",
         friday="Confirmed: OTP"):
    return ["1", "Interviewer", "1:00", first, last, "TRUE", email, phone,
            "", final, bg, "FALSE", friday]


def _tab(*sections):
    """sections = lists of person-rows; each gets its own date + header row."""
    values = []
    for rows in sections:
        # list(HEADER), not HEADER: a test that mutates its rows would
        # otherwise rewrite the module-level header for every later test.
        values += [["8/24/2026"] + [""] * 12, list(HEADER)] + list(rows) + [[""] * 13]
    return values


def test_reads_every_section_not_just_the_first():
    values = _tab([_row("Ana", "Lopez", "ana@x.com")],
                  [_row("Ben", "Ruiz", "ben@x.com")])
    people = parse_tab(values, "D2D OBCL 8.24")
    assert [p.name for p in people] == ["Ana Lopez", "Ben Ruiz"]
    assert [p.section for p in people] == [1, 2]


def test_three_or_more_sections_are_all_read():
    # The tab grew a second stacked block without warning; assume a third will
    # turn up too. Every header row starts a new section, however many there are.
    people = parse_tab(_tab([_row("A", "One", "a@x.com")],
                            [_row("B", "Two", "b@x.com")],
                            [_row("C", "Three", "c@x.com")],
                            [_row("D", "Four", "d@x.com")]), "t")
    assert [p.name for p in people] == ["A One", "B Two", "C Three", "D Four"]
    assert [p.section for p in people] == [1, 2, 3, 4]


def test_rows_hidden_by_a_sheet_filter_are_still_parsed():
    # Sheets filters hide rows in the VIEW only -- values API returns them all.
    # Proven against the live tab 2026-08-24 (53 rows hidden, all 72 people
    # parsed). This pins the parser side: nothing here may skip a row for
    # looking "hidden", because we never see that flag in the first place.
    values = _tab([_row("A", "One", "a@x.com")], [_row("B", "Two", "b@x.com")])
    assert len(parse_tab(values, "t")) == 2


def test_bad_final_status_blocks_the_send():
    for final in ("Failed BGC", "Quit before Classroom",
                  "Quit during Classroom", "Quit - CR", "Terminated",
                  "No Show", "no-show", "RESCHEDULING", "Declined"):
        p = parse_tab(_tab([_row("A", "B", "a@x.com", final=final)]), "t")[0]
        assert not p.eligible, final
        assert final in p.skip_reason


def test_good_final_status_still_sends():
    # The blank-only rule excluded this person on 2026-08-24. It shouldn't.
    p = parse_tab(_tab([_row("A", "B", "a@x.com", final="Showed Up To CR")]), "t")[0]
    assert p.eligible
    assert not final_status_is_unrecognised(p.final_status)


def test_unrecognised_final_status_sends_but_is_flagged():
    p = parse_tab(_tab([_row("A", "B", "a@x.com", final="Pending Paperwork")]),
                  "t")[0]
    assert p.eligible                       # block-list: unknown still sends
    assert final_status_is_unrecognised(p.final_status)   # ...and gets shouted about


def test_blank_final_status_is_not_flagged():
    p = parse_tab(_tab([_row("A", "B", "a@x.com", final="")]), "t")[0]
    assert p.eligible
    assert not final_status_is_unrecognised(p.final_status)


def test_failed_and_adverse_action_bg_block_the_send():
    for bg in ("Failed", "failed", "Adverse Action"):
        p = parse_tab(_tab([_row("A", "B", "a@x.com", bg=bg)]), "t")[0]
        assert not p.eligible, bg


def test_bg_statuses_that_still_get_docs():
    for bg in ("Passed", "Sent", "Taken - Pending", "Review",
               "Unperformable", "Expired", "Pending (Name Issue)"):
        p = parse_tab(_tab([_row("A", "B", "a@x.com", bg=bg)]), "t")[0]
        assert p.eligible, bg


def test_declined_friday_confirmation_blocks_the_send():
    p = parse_tab(_tab([_row("A", "B", "a@x.com", friday="Declined")]), "t")[0]
    assert not p.eligible
    assert "Declined" in p.skip_reason


def test_unanswered_friday_confirmation_still_sends():
    # "NA: Sent Text" = the text went out and nobody replied yet. Not a no.
    for friday in ("NA: Sent Text", "Confirmed: OTP", "Confirmed: Via Sms",
                   "BOB Friday", ""):
        p = parse_tab(_tab([_row("A", "B", "a@x.com", friday=friday)]), "t")[0]
        assert p.eligible, friday


def test_missing_or_junk_email_is_skipped_not_sent():
    for email in ("", "   ", "not-an-email"):
        p = parse_tab(_tab([_row("A", "B", email)]), "t")[0]
        assert not p.eligible
        assert "email" in p.skip_reason


def test_columns_are_found_by_label_not_position():
    values = _tab([_row("Ana", "Lopez", "ana@x.com")])
    for row in values:                       # bolt a new column on the front
        row.insert(0, "NEW")
    people = parse_tab(values, "t")
    assert people[0].name == "Ana Lopez"
    assert people[0].email == "ana@x.com"


def test_name_column_is_not_confused_with_last_name():
    p = parse_tab(_tab([_row("Ana", "Lopez", "a@x.com")]), "t")[0]
    assert (p.first, p.last) == ("Ana", "Lopez")


def test_phone_shapes_from_both_sections_normalize():
    assert normalize_phone("18176876676") == "+18176876676"
    assert normalize_phone("817-395-7537") == "+18173957537"
    assert normalize_phone("(817) 395 7537") == "+18173957537"
    assert normalize_phone("nope") == ""


def test_tab_date_parsing():
    assert _tab_date("D2D OBCL 8.24").month == 8
    assert _tab_date("D2D OBCL 8.24").day == 24
    assert _tab_date("D2D OBCL 12.8.25").year == 2025
    assert _tab_date("D2D OBCL") is None
