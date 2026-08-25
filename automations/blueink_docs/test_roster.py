"""Parser tests -- the two things that would quietly send docs to the wrong
person: dropping a section, and mis-reading a status column.

    python -m pytest automations/blueink_docs/test_roster.py -q
"""
from automations.blueink_docs.roster import (NewStart, collapse_duplicates,
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
    # turn up too. Megan 2026-08-24: "it shouldn't just be limited to 2 charts
    # ... could have more so we need to read all". Nothing counts charts.
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


def test_duplicate_rows_collapse_to_the_complete_one():
    # The tab repeated 25 names as bare stubs on 2026-08-24. Without this the
    # stub reports as "no usable email" and fills the Slack summary with false
    # alarms.
    full = _row("Cale", "Mckenna", "cale@x.com", final="Showed Up To CR")
    stub = ["", "", "", "Cale", "Mckenna", "", "", "", "", "", "", "", "", ""]
    people = parse_tab(_tab([full, stub]), "t")
    assert len(people) == 2                      # both parsed...
    kept = collapse_duplicates(people)
    assert len(kept) == 1                        # ...one survives
    assert kept[0].email == "cale@x.com"
    assert kept[0].eligible


def test_collapse_keeps_everyone_distinct():
    people = parse_tab(_tab([_row("A", "One", "a@x.com"),
                             _row("B", "Two", "b@x.com")]), "t")
    assert len(collapse_duplicates(people)) == 2


def test_rows_below_a_chart_are_not_people():
    # Megan 2026-08-24: only people IN a chart count. A chart ends at the blank
    # row; anything typed underneath belongs to nobody.
    values = _tab([_row("Ana", "Lopez", "ana@x.com")])
    values.append(["", "", "", "Stray", "Person", "", "", "", "", "", "", "", "", ""])
    people = parse_tab(values, "t")
    assert [p.name for p in people] == ["Ana Lopez"]


def test_a_second_chart_after_a_gap_still_counts():
    # ...but a real second chart -- blank row, date, header, people -- does.
    people = parse_tab(_tab([_row("Ana", "Lopez", "ana@x.com")],
                            [_row("Ben", "Ruiz", "ben@x.com")]), "t")
    assert [p.name for p in people] == ["Ana Lopez", "Ben Ruiz"]


def test_second_monday_chart_without_a_header_still_reads():
    # Monday's tab carries two charts. If the second one is pasted in without
    # a header row, its people must still be read -- the DATE row is the
    # marker that a chart started.
    values = _tab([_row("Ana", "Lopez", "ana@x.com")])
    values.append(["8/31/2026"] + [""] * 13)
    values.append(_row("Ben", "Ruiz", "ben@x.com"))
    people = parse_tab(values, "t")
    assert [p.name for p in people] == ["Ana Lopez", "Ben Ruiz"]
    assert [p.section for p in people] == [1, 2]


def test_a_date_row_is_still_required_for_headerless_rows():
    # No date row = not a chart. The 2026-08-24 stray rows must stay excluded.
    values = _tab([_row("Ana", "Lopez", "ana@x.com")])
    values.append(_row("Stray", "Person", "stray@x.com"))
    assert [p.name for p in parse_tab(values, "t")] == ["Ana Lopez"]


def test_many_charts_of_mixed_shape_all_read():
    # Seven charts, every other one opened by a date row with NO header of its
    # own, plus a stray row at the bottom that belongs to no chart.
    names = ["Ana", "Ben", "Cara", "Dan", "Eve", "Finn", "Gus"]
    values = []
    for i, n in enumerate(names):
        values.append(["8/%d/2026" % (3 + i)] + [""] * 13)
        if i % 2 == 0:
            values.append(list(HEADER))
        values.append(_row(n, "Surname%d" % i, "%s@x.com" % n.lower()))
        values.append([""] * 14)
    values.append(["", "", "", "Stray", "Person"] + [""] * 9)

    people = parse_tab(values, "t")
    assert [p.first for p in people] == names
    assert [p.section for p in people] == list(range(1, len(names) + 1))
    assert "Stray" not in [p.first for p in people]
