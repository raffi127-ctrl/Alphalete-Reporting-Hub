"""Las capitanias NDS (Khalil, Colten, Jairo) llevan los knocks desde el
2026-09-15 (Eve: "megan dice que creo el knocks report (daily y weekly) para las
capitanias de NDS ... podemos agregarlas a sus daily captainship emails?").

Lo que esto fija: que las dos secciones estan en el flavor, que el board diario
de cada owner sale con las columnas de SU forma (wireless / gaps-only / house),
que el resumen no inventa ceros para lo que una oficina wireless no tiene, que
las apps de NDS salen del workbook NDS (Eve 2026-09-15) sumadas a las D2D, y
que el mail nocturno NO se suma solo.

    python -m unittest automations.captainship_drafts.test_knocks_nds
"""
import datetime as dt
import unittest
from pathlib import Path

from automations.captainship_drafts import config
from automations.captainship_drafts import knock_dispo_images as KD
from automations.total_knocks import pull as K

DAY = dt.date(2026, 9, 14)


def _wireless(rep, knocks, not_int=10):
    return {K.COL_ID: rep[:3], K.COL_REP: rep, K.COL_TOTAL_LEADS_KNOCKED: 50,
            K.COL_TOTAL_KNOCKS: knocks, K.COL_FIRST_KNOCK: "10:00 AM",
            K.COL_LAST_KNOCK: "6:00 PM", K.COL_NO_ANSWER: 40,
            K.COL_NOT_INTERESTED: not_int, K.COL_COME_BACK: 5,
            K.COL_INACCESSIBLE: 4, K.COL_DO_NOT_KNOCK: 1,
            K.COL_GAPS: 1, K.COL_TOTAL_GAPS: 30}


def _house(rep, knocks, talk):
    rec = {c: "" for c in K.SHEET_COLUMNS}
    rec.update({K.COL_REP: rep, K.COL_TOTAL_KNOCKS: knocks,
                K.COL_TOTAL_TALK_TO: talk, K.COL_TOTAL_LEADS_KNOCKED: knocks,
                K.COL_FIRST_KNOCK: "10:00 AM", K.COL_LAST_KNOCK: "6:00 PM",
                K.COL_NO_ANSWER: 30, K.COL_TALK_TO_NI: 6, K.COL_PRES_NI: 2,
                K.COL_COME_BACK: 3, K.COL_SALE: 1, K.COL_INACCESSIBLE: 4,
                K.COL_DO_NOT_KNOCK: 0, K.COL_GAPS: 0, K.COL_TOTAL_GAPS: 0})
    return rec


def _gaps_only(rep):
    return {K.COL_ID: rep[:3], K.COL_REP: rep, K.COL_FIRST_KNOCK: "11:00 AM",
            K.COL_LAST_KNOCK: "5:00 PM", K.COL_GAPS: 2, K.COL_TOTAL_GAPS: 45}


class NdsCarriesBothSections(unittest.TestCase):
    def test_kinds_and_intro_stay_index_aligned(self):
        _greeting, items = config._INTRO["nds"]
        self.assertEqual(len(items), len(config.SECTION_KINDS["nds"]))
        self.assertEqual(config.SECTION_KINDS["nds"][-2:],
                         ["daily_knocks", "knock_dispo"])
        self.assertEqual(items[-2:], config._INTRO["fiber"][1][-2:])

    def test_the_three_nds_captains_get_them(self):
        tuesday = dt.date(2026, 9, 15)
        for key in ("khalil", "colten", "jairo"):
            kinds = [k for _h, k in config.BY_KEY[key].sections_on(tuesday)]
            self.assertIn("daily_knocks", kinds, key)
            self.assertNotIn("knock_dispo", kinds, key)   # solo dom + lun

    def test_b2b_still_has_no_knock_sections(self):
        self.assertNotIn("daily_knocks", config.SECTION_KINDS["b2b"])

    def test_the_night_mail_carries_nds_too(self):
        """Eve 2026-09-15 evening: the 9 PM local mail goes to the NDS
        captainships' offices as well."""
        from automations.captainship_night_knocks import run as NK
        keys = NK.default_captains()
        for key in ("khalil", "colten", "jairo"):
            self.assertIn(key, keys)
        self.assertEqual(keys[0], "rafael")


class OwnerCfgs(unittest.TestCase):
    def test_nds_owners_read_the_nds_workbook_too(self):
        (_d, cfg), = KD.owner_cfgs(["Khalil Mansour"], {}, nds=True)
        self.assertEqual(cfg["apps_source"], "nds")
        self.assertEqual(cfg["pss_owner"], "Khalil Mansour")
        (_d, cfg), = KD.owner_cfgs(["Khalil Mansour"], {})
        self.assertEqual(cfg["apps_source"], "d2d")

    def test_the_weekly_pin_is_the_same_one_the_daily_pull_uses(self):
        from automations.rashad_metrics import knocks_pull as KP
        for name in ("Calvin Ribera", "Khalil Mansour"):
            (_d, cfg), = KD.owner_cfgs([name], {}, nds=True)
            self.assertEqual(cfg["campaign_id"], KP.campaign_for_office(name))


class NdsApps(unittest.TestCase):
    """La vista 'Thisweekandlast' del workbook NDS, con la forma medida el
    2026-09-15: fila 0 = semana por columna, fila 1 = encabezados, la celda
    del owner solo en la primera fila de su bloque y con salto de linea."""

    def setUp(self):
        import csv, tempfile
        rows = [
            ["", "", "", "9/13/2026", "9/13/2026", "9/13/2026", "9/20/2026",
             "9/20/2026", "Grand Total"],
            ["Owner & Office ", "Rep Name", "Product Type (Broken Out)",
             "Monday", "Saturday", "Total", "Monday", "Total", "Total"],
            ["Grand Total", "Total", "Total", "1,174", "5", "1,179", "3", "3",
             "1,182"],
            ["KHALIL MANSOUR\r[alphalete management group]", "Total", "Total",
             "9", "2", "11", "4", "4", "15"],
            ["", "Amet Shemo", "WIRELESS", "5", "2", "7", "4", "4", "11"],
            ["", "Amet Shemo", "AIR", "1", "", "1", "", "", "1"],
            ["", "Orlando Keenan", "WIRELESS", "3", "", "3", "", "", "3"],
            ["ZAID ARABYAT\r[aces acquisitions]", "Total", "Total", "2", "",
             "2", "", "", "2"],
            ["", "Rep Z", "WIRELESS", "2", "", "2", "", "", "2"],
        ]
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "nds.csv"
        with open(self.path, "w", encoding="utf-16", newline="") as fh:
            csv.writer(fh, delimiter="\t", quotechar='"').writerows(rows)

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_week_sums_every_product_type_monday_to_saturday(self):
        from automations.weekly_knock_dispositions import apps as A
        got = A.nds_rep_apps_for_owner(self.path, "Khalil Mansour", {},
                                       dt.date(2026, 9, 13))
        self.assertEqual(got, {"Amet Shemo": 8, "Orlando Keenan": 3})

    def test_one_day_reads_its_own_weeks_column(self):
        from automations.weekly_knock_dispositions import apps as A
        got = A.nds_rep_apps_for_owner(self.path, "Khalil Mansour", {},
                                       dt.date(2026, 9, 20), days=["Monday"])
        self.assertEqual(got["Amet Shemo"], 4)

    def test_the_owner_is_matched_through_the_alias_list(self):
        from automations.weekly_knock_dispositions import apps as A
        got = A.nds_rep_apps_for_owner(
            self.path, "Zaid Arabiyat", {"Zaid Arabyat": ["Zaid Arabiyat"]},
            dt.date(2026, 9, 13))
        self.assertEqual(got, {"Rep Z": 2})

    def test_a_week_or_day_the_file_lacks_raises_instead_of_a_zero(self):
        from automations.weekly_knock_dispositions import apps as A
        with self.assertRaises(RuntimeError):
            A.nds_rep_apps_for_owner(self.path, "Khalil Mansour", {},
                                     dt.date(2026, 9, 6))
        with self.assertRaises(RuntimeError):
            A.nds_rep_apps_for_owner(self.path, "Khalil Mansour", {},
                                     dt.date(2026, 9, 20), days=["Friday"])

    def test_the_two_sources_add_up_per_rep(self):
        self.assertEqual(KD.merge_apps({"Amet Shemo": 1},
                                       {"amet shemo": 2, "Rep Z": 3}),
                         {"Amet Shemo": 3, "Rep Z": 3})
        self.assertEqual(KD.merge_apps(None, {"Rep Z": 1}), {"Rep Z": 1})
        self.assertIsNone(KD.merge_apps(None, None))


class DailySummaryForWireless(unittest.TestCase):
    def test_house_captainships_keep_the_seven_columns(self):
        captured = [("A", {"name": "A"}, [_house("ana", 60, 12)], 3)]
        self.assertEqual(KD.summary_dispo(captured), KD.DAILY_SUMMARY_DISPO)
        self.assertEqual(KD.summary_headers(KD.summary_dispo(captured)),
                         KD.DAILY_SUMMARY_HEADERS)

    def test_the_wireless_bucket_is_the_pulls_own_name(self):
        self.assertEqual(KD._WIRELESS_DISPO, K.COL_NOT_INTERESTED)

    def test_an_all_wireless_captainship_drops_the_split_it_cant_read(self):
        captured = [("A", {"name": "A"}, [_wireless("ana", 60)], None)]
        dispo = KD.summary_dispo(captured)
        self.assertIn(K.COL_NOT_INTERESTED, dispo)
        for gone in (K.COL_TALK_TO_NI, K.COL_PRES_NI, K.COL_SALE):
            self.assertNotIn(gone, dispo)

    def test_a_wireless_icd_shows_blank_talk_tos_not_zeros(self):
        captured = [("A", {"name": "A"}, [_wireless("ana", 60),
                                          _wireless("bo", 40, 7)], None)]
        dispo = KD.summary_dispo(captured)
        row = KD.daily_summary_row("A", captured[0][2], None, dispo)
        at = KD.summary_headers(dispo).index
        self.assertEqual(row[at("Total Knocks")], "100")
        self.assertEqual(row[at("Total # of Reps Knocking")], "2")
        for col in ("Total Talk To", "% Talk To's per Knocks",
                    "Talk To's per Rep", "Total Apps"):
            self.assertEqual(row[at(col)], "", col)
        self.assertEqual(row[at(K.COL_NOT_INTERESTED)], "17")

    def test_a_mixed_totals_row_does_not_print_a_partial_talk_to_rate(self):
        """Khalil tiene a Isaiah (RES AT&T, house) junto a oficinas wireless:
        los talk-to's de una sola sobre los knocks de todas no es una tasa."""
        captured = [("Isaiah", {"name": "Isaiah"}, [_house("ana", 60, 12)], None),
                    ("Zaid", {"name": "Zaid"}, [_wireless("bo", 40)], None)]
        table, bgs = KD.daily_summary_table(captured, chan_rows=None)
        dispo = KD.summary_dispo(captured)
        at = KD.summary_headers(dispo).index
        totals, isaiah, zaid = table[len(bgs) - 1], table[len(bgs)], table[-1]
        self.assertEqual(isaiah[at("Total Talk To")], "12")
        self.assertEqual(zaid[at("Total Talk To")], "")
        self.assertEqual(totals[at("Total Talk To")], "")
        self.assertEqual(totals[at("Total Knocks")], "100")
        # cada ICD muestra solo los buckets que su tabla tiene
        self.assertEqual(isaiah[at(K.COL_NOT_INTERESTED)], "")
        self.assertEqual(zaid[at(K.COL_SALE)], "")
        for r in table:
            self.assertEqual(len(r), len(KD.summary_headers(dispo)))

    def test_a_gaps_only_icd_has_no_knock_counts_to_show(self):
        row = KD.daily_summary_row("G", [_gaps_only("ana")])
        at = KD.DAILY_SUMMARY_HEADERS.index
        self.assertEqual(row[at("Total Knocks")], "")
        self.assertEqual(row[at("Total # of Reps Knocking")], "")
        self.assertEqual(row[at("Avg First Knock")], "11:00 AM")


class PerOwnerDailyBoard(unittest.TestCase):
    def _drawn(self, rows, board_rows=None, apps=None):
        from automations.total_knocks import render as R
        seen = {}

        def fake_draw(cols, table, title, theme, out, **k):
            seen.update(cols=list(cols), title=title, out=out,
                        table=[list(r) for r in table])
            return out
        old = R._draw
        R._draw = fake_draw
        try:
            KD.render_owner_daily_board(
                DAY, rows, board_rows or rows, Path("."), "Zaid Arabiyat",
                extra_totals=[("Chan Park", [_house("chan", 90, 20)])],
                apps=apps)
        finally:
            R._draw = old
        return seen

    def test_a_wireless_office_shows_its_apps(self):
        rows = [_wireless("ana", 60), _wireless("bo", 40)]
        board_rows, apps, _n = KD.daily_apps_for_board(rows,
                                                       {"ana": 3, "bo": 1})
        seen = self._drawn(rows, board_rows, apps)
        self.assertIn("Total Apps", seen["cols"])

    def test_a_wireless_office_gets_the_wireless_columns_and_daily_title(self):
        seen = self._drawn([_wireless("ana", 60)])
        self.assertIn(K.COL_NOT_INTERESTED, seen["cols"])
        self.assertNotIn(K.COL_TALK_TO_NI, seen["cols"])
        self.assertTrue(seen["title"].startswith("DAILY TOTAL KNOCKS"),
                        seen["title"])

    def test_a_gaps_only_office_gets_the_telemapper_board(self):
        seen = self._drawn([_gaps_only("ana")])
        self.assertTrue(seen["title"].startswith("TELEMAPPER KNOCKS"),
                        seen["title"])

    def test_a_house_office_keeps_the_board_it_always_had(self):
        from automations.total_knocks import render as R
        seen = self._drawn([_house("ana", 60, 12)])
        self.assertIn(R.COMBINED_KNOCKS_DISPLAY.get(K.COL_TALK_TO_NI,
                                                    K.COL_TALK_TO_NI),
                      seen["cols"])
        self.assertTrue(seen["title"].startswith("DAILY TOTAL KNOCKS"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
