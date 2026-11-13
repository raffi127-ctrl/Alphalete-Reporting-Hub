"""Ad Scorecard 2nd picture (Raf 11/12): sheet + AppStream funnel per ad."""
import datetime as dt
import unittest

from automations.ad_photo_threads import config, funnel


class _Book:
    """resolve() = lower-cased title, minus a ' - city' tail."""
    def resolve(self, t):
        return (t or "").split(" - ")[0].strip().lower() or None

    def display(self, k):
        return k.title()


D = dt.date(2026, 11, 6)


class Funnel(unittest.TestCase):
    def setUp(self):
        self._src = config.SOURCES
        config.SOURCES = [{"tab": "T"}]

    def tearDown(self):
        config.SOURCES = self._src

    def test_sheet_counts(self):
        rows = [
            {"Date 1st Rd": "11/03/2026", "Full Name": "A B", "Ad Title": "Sales Agent",
             "Offered Positon": "YES", "BOB": "BOB"},
            {"Date 1st Rd": "11/04/2026", "Full Name": "C D", "Ad Title": "sales agent",
             "Offered Positon": "NO", "BOB": ""},
            {"Date 1st Rd": "10/20/2026", "Full Name": "E F", "Ad Title": "Sales Agent",
             "Offered Positon": "YES", "BOB": "BOB"},          # outside the week
            {"Date 1st Rd": "11/04/2026", "Full Name": "", "Ad Title": "Sales Agent"},
        ]
        got = funnel.sheet_counts({"T": rows}, _Book(), dt.date(2026, 11, 2), D)
        self.assertEqual(got, {"sales agent": {"s1": 2, "offered": 1, "bob": 1}})

    def test_match_and_rows(self):
        ads = [{"title": "Sales Agent", "city": "Miami, FL",
                "rec": {"apps": 40, "b1": 9, "nb": 2, "ns": 1}},
               {"title": "Sales Agent", "city": "",
                "rec": {"apps": 10, "b1": 1, "nb": 0, "ns": 0}},
               {"title": "Brand New Ad", "city": "Doral, FL",
                "rec": {"apps": 5, "b1": 0, "nb": 0, "ns": 0}},
               {"title": "Dead Ad", "city": "", "rec": {"apps": 0, "b1": 0, "nb": 0, "ns": 0}}]
        sheet = {"sales agent": {"s1": 2, "offered": 1, "bob": 1}}
        app = funnel.match(ads, _Book(), sheet.keys())
        self.assertEqual(app["sales agent"], {"apps": 50, "b1": 10, "nb": 2, "ns": 1, "bob": None})
        rows = funnel.rows_for(sheet, app, {"sales agent": "Sales Agent"})
        self.assertEqual([r["title"] for r in rows], ["Sales Agent", "Brand New Ad"])
        self.assertEqual(funnel.cells(rows[0], 1),
                         ["1", "Sales Agent", "", "50", "10", "2", "1", "1", "2", "1"])
        self.assertEqual(funnel.cells(rows[1], 2)[5:8], ["-", "-", "-"])
        tot = funnel.total(rows, True)
        self.assertEqual(funnel.cells(tot, None)[3:],
                         ["55", "10", "2", "1", "1", "2", "1"])

    def test_no_appstream_dashes(self):
        rows = funnel.rows_for({"x": {"s1": 3, "offered": 0, "bob": 0}}, None, {"x": "X"})
        self.assertEqual(funnel.cells(rows[0], 1)[3:],
                         ["-", "-", "3", "0", "0", "-", "-"])
        self.assertEqual(funnel.cells(funnel.total(rows, False), None)[3], "-")

    def test_offers_off_dashes(self):
        old = config.SCORECARD_FUNNEL_OFFERS
        config.SCORECARD_FUNNEL_OFFERS = False
        try:
            rows = funnel.rows_for({"x": {"s1": 3, "offered": 0, "bob": 0}}, None, {"x": "X"})
            self.assertEqual(funnel.cells(rows[0], 1)[5:8], ["3", "-", "-"])
            # Raf: BOB from AppStream's Brought on Board, summed in the total.
            ads = [{"title": "X", "city": "", "rec": {"apps": 9, "b1": 4, "nb": 1, "ns": 1, "bob": 2}},
                   {"title": "Y", "city": "", "rec": {"apps": 3, "b1": 1, "nb": 0, "ns": 0, "bob": 1}}]
            app = funnel.match(ads, _Book(), ["x"])
            rows = funnel.rows_for({"x": {"s1": 3, "offered": 0, "bob": 0}}, app, {"x": "X"})
            self.assertEqual(funnel.cells(rows[0], 1)[5:8], ["3", "-", "2"])
            self.assertEqual(funnel.cells(funnel.total(rows, True), None)[7], "3")
            self.assertTrue(funnel.post_note())
            # A report without the column: "-", never a fake 0.
            ads[0]["rec"]["bob"] = ads[1]["rec"]["bob"] = None
            app = funnel.match(ads, _Book(), ["x"])
            rows = funnel.rows_for({"x": {"s1": 3, "offered": 0, "bob": 0}}, app, {"x": "X"})
            self.assertEqual(funnel.cells(funnel.total(rows, True), None)[7], "-")
        finally:
            config.SCORECARD_FUNNEL_OFFERS = old

    def test_every_scorecard_office_reads_its_own_appstream(self):
        got = {}
        for o in config.OFFICES:
            if o.get("scorecard"):
                config.use(o)
                got[o["key"]] = config.SCORECARD_FUNNEL_OFFICE
        self.assertEqual(got["colten"], "14733")
        self.assertEqual(got["eveliz"], "18404")
        self.assertEqual(got["jairo"], "21270")
        self.assertEqual(got["rafael"], "11280")


if __name__ == "__main__":
    unittest.main()
