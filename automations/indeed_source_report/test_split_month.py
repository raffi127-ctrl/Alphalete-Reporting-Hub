"""A month pulled in two halves adds up to the same ads as one pull.

Run:  python -m unittest automations.indeed_source_report.test_split_month

WHAT THIS GUARDS (2026-11-12). Rafael Hidalgo (11280) got AppStream's
"Server Error 500" for the month's Source Report; fetch.source_report now asks
for the two halves and joins the tables. Every field is a count, so the joined
read must give exactly what one table with the summed counts gives.
"""
import unittest

from automations.indeed_source_report import fetch, parse

COLS = ["Email Inbox", "Email Subject Line", "Process Emails",
        "Removed From Process Emails", "Sent to Call List",
        "First Interviews Booked", "First Interviews Marked Showed Up",
        "Second Interviews Booked", "Second Interviews Showed-up"]


def _table(rows):
    head = "".join("<th>%s</th>" % c for c in COLS)
    body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % v for v in r)
                   for r in rows)
    return "<table><tr>%s</tr>%s</table>" % (head, body)


AD = ("hr@x.com", "Sales Rep - Dallas, TX")


class SplitMonth(unittest.TestCase):
    def test_two_halves_add_up_to_one_pull(self):
        h1 = _table([AD + (5, 1, 4, 3, 2, 1, 1)])
        h2 = _table([AD + (7, 0, 6, 2, 1, 1, 0)])
        whole = _table([AD + (12, 1, 10, 5, 3, 2, 1)])
        split_ads, _ = parse.ads_for_month(h1 + h2)
        whole_ads, _ = parse.ads_for_month(whole)
        self.assertEqual(len(split_ads), 1)
        self.assertEqual(split_ads[0]["rec"], whole_ads[0]["rec"])

    def test_one_table_reads_as_before(self):
        ads, _ = parse.ads_for_month(_table([AD + (3, 0, 2, 1, 1, 0, 0)]))
        self.assertEqual(ads[0]["rec"]["apps"], 3)

    def test_split_range_is_disjoint_and_complete(self):
        self.assertEqual(fetch._split_range("11-01-2026", "11-30-2026"),
                         [("11-01-2026", "11-15-2026"),
                          ("11-16-2026", "11-30-2026")])
        self.assertIsNone(fetch._split_range("11-12-2026", "11-12-2026"))

    def test_500_page_is_named(self):
        class P:
            url = "https://applicantstream.com/index.cfm?p=702&"

            def evaluate(self, js):
                return ("Server Error 500 - Internal server error. There is a "
                        "problem with the resource you are looking for")
        self.assertIsInstance(fetch._no_table_error(P()),
                              fetch.AppStreamServerError)


if __name__ == "__main__":
    unittest.main()
