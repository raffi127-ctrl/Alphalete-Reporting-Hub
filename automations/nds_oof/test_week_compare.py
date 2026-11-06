from automations.nds_oof import week_compare as W


def test_parse_kinds():
    assert W.parse("12") == ("num", 12.0)
    assert W.parse("35%") == ("pct", 35.0)
    assert W.parse("1h 20m") == ("dur", 80.0)
    assert W.parse("45m") == ("dur", 45.0)
    assert W.parse("9:45 AM") == ("clock", 585.0)
    assert W.parse("12:10 PM") == ("clock", 730.0)
    assert W.parse("—") == (None, None)
    assert W.parse("n/a") == (None, None)


def test_delta_and_direction():
    assert W.fmt_delta("num", 5) == "+5"
    assert W.fmt_delta("pct", -2.5) == "-2.5 pts"
    assert W.fmt_delta("dur", 75) == "+1h 15m"
    assert W.better("Mon–Sat Avg Gap / Day", -10) is True
    assert W.better("Mon–Fri Avg First Knock", 15) is False
    assert W.better("Mon–Fri Total Knocks", 15) is True
    assert W.better("Mon–Fri Total Knocks", 0) is None


def _week(rows):
    return {"headers": ["#", "Rep", "Mon–Fri Total Knocks", "Mon–Sat Avg Gap / Day", "Mon–Fri Avg First Knock"],
            "rows": rows}


def test_build_rows_totals_first_new_and_gone():
    prev = _week([["1", "Ana Lopez", "100", "1h 00m", "10:00 AM"],
                  ["2", "Bob Ruiz", "80", "45m", "9:30 AM"],
                  ["", "OFFICE TOTALS", "180", "52m", "9:45 AM"]])
    last = _week([["1", "Ana Lopez", "120", "40m", "9:50 AM"],
                  ["2", "Cara Diaz", "60", "30m", "11:00 AM"],
                  ["", "OFFICE TOTALS", "180", "35m", "10:25 AM"]])
    header, rows, bgs, n_tot = W.build(prev, last)
    assert header == ["Rep", "Mon–Fri Total Knocks", "Mon–Sat Avg Gap / Day", "Mon–Fri Avg First Knock"]
    assert n_tot == 1 and rows[0][0] == "OFFICE TOTALS"
    ana = next(r for r in rows if r[0] == "Ana Lopez")
    assert ana[1] == "100 → 120  (+20)"
    assert ana[2] == "1h 00m → 40m  (-20m)"
    assert ana[3] == "10:00 AM → 9:50 AM  (-10m)"
    cara = next(r for r in rows if r[0] == "Cara Diaz")
    assert cara[1] == "new → 60"
    bob = next(r for r in rows if r[0] == "Bob Ruiz")
    assert bob[1] == "80 → off board"
    ri = rows.index(ana)
    assert bgs[(ri, 1)] == W.GREEN and bgs[(ri, 2)] == W.GREEN and bgs[(ri, 3)] == W.GREEN
    tot = rows.index(rows[0])
    assert (tot, 1) not in bgs                      # unchanged → no colour
    assert bgs[(tot, 3)] == W.RED                   # first knock later = worse


def test_all_blank_column_is_dropped():
    prev = {"headers": ["#", "Rep", "Knocks", "Apps"], "rows": [["1", "Ana Lopez", "10", "—"]]}
    last = {"headers": ["#", "Rep", "Knocks", "Apps"], "rows": [["1", "Ana Lopez", "12", ""]]}
    header, rows, bgs, n_tot = W.build(prev, last)
    assert header == ["Rep", "Knocks"] and rows[0] == ["Ana Lopez", "10 → 12  (+2)"]


def test_recap_days_monday_to_saturday():
    import datetime as _dt
    from automations.nds_oof.run import recap_days
    days = recap_days(_dt.date(2026, 10, 31))
    assert days[0] == _dt.date(2026, 10, 26)
    assert days[-1] == _dt.date(2026, 10, 31)
    assert [d.weekday() for d in days] == [0, 1, 2, 3, 4, 5]
