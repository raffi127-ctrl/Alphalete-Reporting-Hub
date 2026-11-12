"""python -m unittest automations.interviewers_retention.test_build"""
import datetime as dt
import unittest
from types import SimpleNamespace

from automations.interviewers_retention import build

HDR = ["INTERVIEWER", "", "QUALIFIED", "2nd R BOOKED", "2nd R SHOWED", "2nd SHOWED %"]
TODAY = dt.date(2026, 11, 11)


def box(label, rows):
    out = [[label, "", " INTERVIEWERS RETENTION (Interviewers breakdown)"],
           ["", "OFFICE", "WEEKLY TOTAL"], HDR]
    out += rows
    out.append(["AVERAGES", "", "99", "999", "999"])
    return out


TAB = (box("11/8", [["Atef", "Gabriela", "13", "10", "5", "50%"],
                    ["", "Nicole", "40", "4", "1", "25%"],
                    ["Omar", "Gabriela", "9", "10", "8", "80%"],
                    ["Kash", "Valeria", "", "", "", "#DIV/0!"]])
       + box("11/1", [["Atef", "Gabriela", "1", "4", "1", ""], ["Omar", "Gabriela", "1", "2", "2", ""]])
       + box("10/25", [["Atef", "Nicole", "1", "2", "1", ""]]))


class Weeks(unittest.TestCase):
    def test_parse_reads_by_header_and_fills_owner_down(self):
        w = build.parse_weeks(TAB, TODAY)
        self.assertEqual([x.label for x in w], ["11/8", "11/1", "10/25"])
        self.assertEqual(w[0].start, dt.date(2026, 11, 8))
        self.assertEqual([(r.owner, r.interviewer, r.booked, r.showed) for r in w[0].rows],
                         [("Atef", "Gabriela", 10, 5), ("Atef", "Nicole", 4, 1),
                          ("Omar", "Gabriela", 10, 8), ("Kash", "Valeria", 0, 0)])

    def test_interviewer_sums_across_offices_and_ranks(self):
        pi, po = build.podiums(build.parse_weeks(TAB, TODAY))
        self.assertEqual([(l.name, l.booked, l.showed) for l in pi.lines],
                         [("Gabriela", 20, 13), ("Nicole", 4, 1)])   # Valeria: 0 booked, left out
        self.assertEqual(pi.lines[0].detail, ["Atef", "Omar"])
        self.assertEqual([(l.name, l.booked, l.showed) for l in po.lines],
                         [("Omar", 10, 8), ("Atef", 14, 6)])

    def test_history_is_prior_weeks_oldest_first(self):
        pi, po = build.podiums(build.parse_weeks(TAB, TODAY))
        self.assertEqual(pi.history_labels, ["10/25", "11/1", "11/8"])
        g = pi.lines[0]
        self.assertEqual(g.history, [None, 0.5, 0.65])    # 10/25 none, 11/1 = 3/6, 11/8 = 13/20
        self.assertEqual(pi.lines[1].history, [0.5, None, 0.25])

    def test_header_spellings_and_skipped_boxes(self):
        tab = [["11/15", "", " INTERVIEWERS RETENTION"], ["", "OFFICE"],
               ["INTERVIEWER", "", "2ND RD BOOKED", "2nd Rd Showed"], ["Atef", "G", "4", "2"],
               ["11/8", "", " INTERVIEWERS RETENTION"], ["", "OFFICE"],
               ["INTERVIEWER", "", "Booked", "Showed"], ["Atef", "G", "4", "2"]]
        w = build.parse_weeks(tab, TODAY)
        self.assertEqual([(x.label, x.rows[0].booked) for x in w], [("11/15", 4)])
        self.assertEqual([lbl for lbl, _ in build.SKIPPED], ["11/8"])

    def test_colour_fifty_is_green(self):
        self.assertEqual(build.colour(0.5), "good")
        self.assertEqual(build.colour(0.496), "good")      # shows as 50%
        self.assertEqual(build.colour(0.494), "bad")
        self.assertEqual(build.colour(None), "")

    def test_yesterday_never_invented(self):
        day = dt.date(2026, 11, 10)
        bi, bo, has = build.yesterday_boards({"Atef": {dt.date(2026, 11, 9): SimpleNamespace(by={"G": [3, 2]})}}, day)
        self.assertFalse(has)
        bi, bo, has = build.yesterday_boards(
            {"Atef": {day: SimpleNamespace(by={"G": [3, 2], "N": [2, 0]})},
             "Omar": {day: SimpleNamespace(by={"G": [1, 1]})}}, day)
        self.assertTrue(has)
        self.assertEqual([(l.name, l.booked, l.showed) for l in bi.lines], [("G", 4, 3), ("N", 2, 0)])
        self.assertEqual([(l.name, l.booked, l.showed) for l in bo.lines], [("Omar", 1, 1), ("Atef", 5, 2)])


class Datos(unittest.TestCase):
    H = ["Semana (domingo)", "Fecha", "Día", "Office ID", "Owner", "Empresa",
         "2nd agendadas", "2nd vinieron", "% vinieron"]

    def test_office_podium_last_full_week_and_four_weeks(self):
        rows = build.parse_datos([self.H,
            ["2026-11-01", "2026-11-02", "Lun", "1", "Atef", "", "4", "2", ""],
            ["2026-11-01", "2026-11-03", "Mar", "1", "Atef", "", "6", "4", ""],
            ["2026-11-01", "2026-11-02", "Lun", "2", "Omar", "", "2", "2", ""],
            ["2026-10-18", "2026-10-19", "Lun", "1", "Atef", "", "4", "1", ""],
            ["2026-11-08", "2026-11-10", "Mar", "1", "Atef", "", "5", "1", ""]])
        wk = build.last_full_week(TODAY)                  # Wed 11/11 -> Sun 11/1
        self.assertEqual(wk, dt.date(2026, 11, 1))
        b = build.office_podium_datos(rows, wk)
        self.assertEqual(b.history_labels, ["10/11", "10/18", "10/25", "11/1"])
        self.assertEqual([(l.name, l.booked, l.showed) for l in b.lines],
                         [("Omar", 2, 2), ("Atef", 10, 6)])
        self.assertEqual(b.lines[1].history, [None, 0.25, None, 0.6])
        y = build.yesterday_office_datos(rows, dt.date(2026, 11, 10))
        self.assertEqual([(l.name, l.booked, l.showed) for l in y.lines], [("Atef", 5, 1)])


class Roster(unittest.TestCase):
    def test_only_roster_offices_with_roster_spelling(self):
        D = lambda oid, owner: build.DayRow(dt.date(2026, 11, 1), dt.date(2026, 11, 2), oid, owner, 2, 1)
        rows = [D("1", "Juan Botero-Berrio"), D("2", "Andre Burton Jr"), D("3", "Someone Else"),
                D("4", "Jamis Garay New")]
        kept, missing = build.match_offices(rows, ["Juan Botero Berrio", "Andre Burton",
                                                   "Jamis Garay", "Steve McElwee"])
        self.assertEqual(sorted((r.office_id, r.owner) for r in kept),
                         [("1", "Juan Botero Berrio"), ("2", "Andre Burton"), ("4", "Jamis Garay")])
        self.assertEqual(missing, ["Steve McElwee"])


class ByDay(unittest.TestCase):
    def test_days_this_week_or_last_week_on_sunday_monday(self):
        days, last = build.report_days(dt.date(2026, 11, 12))            # Thursday
        self.assertEqual((days[0], days[-1], last), (dt.date(2026, 11, 9), dt.date(2026, 11, 11), False))
        for today in (dt.date(2026, 11, 16), dt.date(2026, 11, 15)):    # Monday, Sunday
            days, last = build.report_days(today)
            self.assertTrue(last)
            self.assertEqual((days[0], days[-1]), (dt.date(2026, 11, 9), dt.date(2026, 11, 14)))
        days, last = build.report_days(dt.date(2026, 11, 17))            # Tuesday: Monday only
        self.assertEqual((days, last), ([dt.date(2026, 11, 16)], False))

    def test_short_names_resolve_within_the_owner(self):
        people = {"eveliz wright": ["Romina Viadana", "Diana Duarte"],
                  "joseph logan": ["Gabriela Salazar"], "frank matos": ["Sofia Schilder", "Sofia Soto"]}
        self.assertEqual(build.resolve_interviewer("Eveliz Wright", "Romina", people), "Romina Viadana")
        self.assertEqual(build.resolve_interviewer("Joseph Logan", "Gabriela Sa", people), "Gabriela Salazar")
        self.assertEqual(build.resolve_interviewer("Frank Matos", "Sofia", people), "Sofia")   # two fit: keep
        self.assertEqual(build.resolve_interviewer("Nobody", "Owner", people), "Owner")

    def test_week_board_sums_days_and_sorts_by_week(self):
        d1, d2 = dt.date(2026, 11, 9), dt.date(2026, 11, 10)
        second = {"Atef": {d1: SimpleNamespace(by={"Gaby": [4, 1]}), d2: SimpleNamespace(by={"Gaby": [0, 0]})},
                  "Omar": {d1: SimpleNamespace(by={"Nic": [2, 2]})}}
        lines = build.interviewer_days(second, [d1, d2], {})
        b = build.week_board(lines, [d1, d2], False, "T", "Interviewer", {"nic": [0.5, None, 1.0, 1.0]},
                             ["10/18", "10/25", "11/1", "11/8"])
        self.assertEqual([(l.name, l.booked, l.showed) for l in b.lines], [("Nic", 2, 2), ("Gaby", 4, 1)])
        self.assertIsNone(b.lines[1].day_pct(d2))          # 0 booked -> no %, drawn as —
        self.assertEqual(b.lines[0].history, [0.5, None, 1.0, 1.0])
        self.assertEqual(b.lines[1].history, [None] * 4)


class ArsWeeks(unittest.TestCase):
    def test_podium_and_history_from_ars_and_unmatched_listed(self):
        people = {"atef": ["Gabriela Salazar", "Nicole Renee"], "omar": ["Gabriela Salazar"]}
        res = build.Resolver(people)
        d = lambda m, dd: dt.date(2026, m, dd)
        second = {"Atef": {d(11, 2): SimpleNamespace(by={"Gabriela": [4, 3], "Sofia R.": [2, 0]}),
                           d(11, 7): SimpleNamespace(by={"Nicole": [2, 1]}),
                           d(10, 27): SimpleNamespace(by={"Gabriela S": [2, 2]}),
                           d(11, 9): SimpleNamespace(by={"Gabriela": [9, 9]})},      # current week: out
                  "Omar": {d(11, 3): SimpleNamespace(by={"Gaby": [2, 1]})}}
        wk = dt.date(2026, 11, 1)
        per = build.ars_interviewer_weeks(second, [wk - dt.timedelta(days=7 * k) for k in range(4)], res)
        b = build.interviewer_podium_ars(per, wk)
        self.assertEqual([(l.name, l.booked, l.showed) for l in b.lines],
                         [("Gabriela Salazar", 4, 3), ("Gaby", 2, 1), ("Nicole Renee", 2, 1), ("Sofia R.", 2, 0)])
        self.assertEqual(b.history_labels, ["10/11", "10/18", "10/25", "11/1"])
        self.assertEqual(b.lines[0].history, [None, None, 1.0, 0.75])
        self.assertEqual(res.report(), ["Atef: 'Sofia R.'", "Omar: 'Gaby'"])


if __name__ == "__main__":
    unittest.main()
