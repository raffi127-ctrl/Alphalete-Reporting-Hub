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


if __name__ == "__main__":
    unittest.main()
