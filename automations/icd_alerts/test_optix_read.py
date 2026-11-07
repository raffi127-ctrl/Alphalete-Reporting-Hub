"""optix_read.tally — the counting half (no browser, no account)."""
import unittest

from automations.icd_alerts import optix_read as O


def row(agent, disp, n, date="11/05/2026"):
    return {"agent": agent, "latestDisposition": disp,
            "latestDispositionDate": date, "totalDisposition": str(n)}


class Tally(unittest.TestCase):
    def test_untouched_leads_are_not_doors(self):
        # 11/5: 1,229 leads, 616 never dispositioned (Giovanni had 661 assigned)
        t = O.tally([row("Giovanni   Monreal", "", 0)] * 5 + [row("Giovanni Monreal", "No Answer", 2)])
        self.assertEqual(t["reps"]["Giovanni Monreal"]["Doors"], 1)
        self.assertEqual(t["reps"]["Giovanni Monreal"]["Knocks"], 2)

    def test_spacing_in_names_collapses(self):
        t = O.tally([row("Thais   Alvarezaragon", "No Answer", 5),
                     row("Thais Alvarezaragon", "Appointment", 1)])
        self.assertEqual(list(t["reps"]), ["Thais Alvarezaragon"])
        self.assertEqual(t["reps"]["Thais Alvarezaragon"]["Knocks"], 6)

    def test_every_disposition_seen_on_11_5_has_a_bucket(self):
        seen = ["No Answer", "Stop Back - No Appt", "Declined - Price/Competition",
                "Do Not Solicit Sign", "No Access", "DM Not Home", "No Interest No Preso",
                "Appointment", "Sale Made - Wireless", "VZW Sale Started",
                "Existing Customer - 401591801", "Sale Canceled- No system issue",
                "Gated Community", "Declined - Not Interested", "House for Sale",
                "Existing Customer", "Sale Canceled- system issue",
                "Sale Made - Wireless - 281630024"]
        for d in seen:
            self.assertNotEqual(O.bucket(d), "Other", d)

    def test_sales_and_talk_to(self):
        t = O.tally([row("Richard Bautista", "Sale Made - Wireless - 281630024", 1),
                     row("Richard Bautista", "VZW Sale Started", 2),
                     row("Richard Bautista", "No Answer", 2)])
        r = t["reps"]["Richard Bautista"]
        self.assertEqual((r["Sale"], r["Sale Started"], r["Talk To"], r["No Answer"]), (1, 1, 2, 1))

    def test_new_disposition_is_named_not_dropped(self):
        t = O.tally([row("Jose Ramos", "Dog In Yard", 1)])
        self.assertEqual(t["reps"]["Jose Ramos"]["Other"], 1)
        self.assertEqual(t["unknown"], ["Dog In Yard"])

    def test_nothing_address_shaped_survives(self):
        t = O.tally([dict(row("Diego Chacon", "No Answer", 1), address="3214 CASTLE ROCK LN")])
        self.assertNotIn("CASTLE", repr(t))


class BoardRow(unittest.TestCase):
    def test_column_names_match_the_board(self):
        from automations.total_knocks import pull as TP
        known = {v for k, v in vars(TP).items() if k.startswith("COL_")}
        for col in [c for c in O.BOARD_COLUMNS.values() if c] + ["Rep", "Do Not Knock"]:
            self.assertIn(col, known, col)

    def test_dnk_comes_out_of_inaccessible(self):
        t = O.tally([row("Isaac Nambo", "Do Not Solicit Sign", 1),
                     row("Isaac Nambo", "Gated Community", 1),
                     row("Isaac Nambo", "No Interest No Preso", 2),
                     row("Isaac Nambo", "Declined - Price/Competition", 1)])
        r = O.board_row("Isaac Nambo", t["reps"]["Isaac Nambo"])
        self.assertEqual(tuple(int(r[k]) for k in ("Do Not Knock", "Inaccessible", "Not Interested",
                                                    "Total Leads Knocked", "Total Knocks")),
                         (1, 1, 2, 4, 5))

    def test_the_board_recognises_and_totals_it(self):
        from automations.icd_alerts import knocks_map
        from automations.total_knocks import render as R
        t = O.tally([row("Richard Bautista", "Sale Made - Wireless", 1),
                     row("Richard Bautista", "Appointment", 1),
                     row("Richard Bautista", "No Answer", 3)])
        rows = knocks_map.to_rows([O.board_row("Richard Bautista", t["reps"]["Richard Bautista"])])
        self.assertEqual(R.knocks_shape(rows), R.SHAPE_VERIZON)
        self.assertEqual(rows[0]["Total Talk to"], 2)
        self.assertEqual(rows[0]["Total Knocks"], 5)


class VerizonSales(unittest.TestCase):
    def test_the_sale_shape(self):
        from automations.shared import sale_hype as H
        s = H.shape("verizon")
        self.assertEqual(s.metrics, ("Lines", "Sales"))
        self.assertEqual(s.total({"Lines": 3, "Sales": 1}), 3)   # lines are the count
        self.assertFalse(s.presale_ping)          # Sale Started is not trusted yet
        self.assertEqual(s.breakdown({"Lines": 1}), "1 app")

    def test_the_hub_counts_a_verizon_sale_as_an_app(self):
        from automations.icd_alerts import post as P
        self.assertEqual(P._apps({"Lines": 2}, campaign="verizon"), 2)

    def test_the_countdown_text(self):
        from automations.icd_alerts import post as P
        txt = P.scoreboard_text({"Richard Bautista": {"Lines": 3}, "Diego Chacon": {"Lines": 1},
                                 "Isaac Nambo": {"Lines": 0}}, ["Diego Chacon"], campaign="verizon")
        lines = txt.splitlines()
        self.assertTrue(lines[0].endswith(" 3"), lines)
        self.assertIn("Diego", lines[1])
        self.assertTrue(lines[-1].endswith("TOTALS: 4"))
        self.assertNotIn("Isaac", txt)
        self.assertEqual(P.scoreboard_text({"A B": {"Lines": 0}}, [], campaign="verizon"), "")

    def test_sale_started_is_not_a_sale(self):
        t = O.tally([row("Diego Chacon", "VZW Sale Started", 1),
                     row("Diego Chacon", "Sale Made - Wireless", 1)])
        self.assertEqual(t["reps"]["Diego Chacon"]["Sale"], 1)


class SharedRules(unittest.TestCase):
    def test_the_extension_and_python_count_the_same(self):
        """extension/optix/rules.json must say exactly what optix_read does."""
        import json
        from pathlib import Path
        r = json.loads((Path(__file__).resolve().parents[2] / "extension/optix/rules.json").read_text())
        self.assertEqual([tuple(x) for x in r["rules"]], [tuple(x) for x in O._RULES])
        self.assertEqual({k: v for k, v in O.BOARD_COLUMNS.items() if v}, r["board_columns"])


if __name__ == "__main__":
    unittest.main()
