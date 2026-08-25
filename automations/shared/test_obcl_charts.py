"""The three rules, each of which is a bug somebody actually hit."""
from automations.shared import obcl_charts as oc

H = ["#", "Interviewer", "Name", "Last Name", "Email", "Blue Ink"]
BLANK = ["", "", "", "", "", ""]


def _p(first, last, email="a@x.com"):
    return ["1", "Iv", first, last, email, "FALSE"]


def _rows(*blocks, header=True):
    out = []
    for b in blocks:
        out += [["8/24/2026", "", "", "", "", ""]]
        if header:
            out += [list(H)]
        out += list(b) + [list(BLANK)]
    return out


def test_finds_every_chart():
    charts = oc.find_charts(_rows([_p("Ana", "Lopez")], [_p("Ben", "Ruiz")]))
    assert len(charts) == 2


def test_a_chart_ends_at_the_blank_row():
    # 2026-08-24: 25 stray name rows below the chart read as real people.
    vals = _rows([_p("Ana", "Lopez")])
    vals.append(["", "", "Stray", "Person", "", ""])
    charts = oc.find_charts(vals)
    stray = len(vals)
    assert not any(c["start_row"] <= stray <= c["end_row"] for c in charts)


def test_date_row_chart_without_a_header_inherits_columns():
    # Monday's second chart is often pasted in without a header row.
    vals = _rows([_p("Ana", "Lopez")])
    vals += [["8/31/2026", "", "", "", "", ""], _p("Ben", "Ruiz")]
    charts = oc.find_charts(vals)
    assert len(charts) == 2
    assert charts[1]["header_row"] is None
    assert charts[1]["cols"] == charts[0]["cols"]


def test_rows_with_no_chart_open_belong_to_nobody():
    # No date row, no header -- not a chart, whatever is typed there.
    charts = oc.find_charts([_p("Ana", "Lopez"), _p("Ben", "Ruiz")])
    assert charts == []


def test_columns_are_found_by_label_not_index():
    vals = _rows([_p("Ana", "Lopez")])
    for row in vals:                       # bolt a column on the front
        row.insert(0, "NEW")
    c = oc.find_charts(vals)[0]
    assert oc.column(c, "Blue Ink") == len(H) + 1
    assert oc.column(c, "Email") == 5 + 1


def test_column_matches_on_substring():
    # The real BG header is "\\nBG Status : Last Checked ".
    vals = _rows([_p("Ana", "Lopez")])
    vals[1].append("\\nBG Status : Last Checked ")
    c = oc.find_charts(vals)[0]
    assert oc.column(c, "BG Status") == len(H) + 1


def test_any_number_of_charts_not_just_two():
    """Monday has two today; Megan says there could be more. Nothing here
    counts charts, so this pins that: seven, of MIXED shape -- some with a
    header row, some opened by a date row alone -- plus a stray row at the
    bottom belonging to nobody."""
    names = ["Ana", "Ben", "Cara", "Dan", "Eve", "Finn", "Gus"]
    vals = []
    for i, n in enumerate(names):
        vals.append(["8/%d/2026" % (3 + i), "", "", "", "", ""])
        if i % 2 == 0:
            vals.append(list(H))
        vals.append(_p(n, "Surname%d" % i))
        vals.append(list(BLANK))
    vals.append(["", "", "Stray", "Person", "", ""])

    charts = oc.find_charts(vals)
    assert len(charts) == len(names)
    assert sum(1 for c in charts if c["header_row"] is None) == 3
    # every chart holds exactly its one person, and the stray is in none
    for c in charts:
        assert c["start_row"] == c["end_row"]
    assert not any(c["start_row"] <= len(vals) <= c["end_row"] for c in charts)
