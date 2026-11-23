import datetime as dt
import unittest

from automations.fiber_zip_penetration import core as C

CSV = "\t".join(["Office Lead Penetration (Fixed)", "Account_Owner_Name__c", "Zip State",
                 "Customer Zip", "Days Since Last Sale", "Lead Count",
                 "Expected Fiber Sales (copy)", "Total Sales", "Sales Needed",
                 "Assigned Fiber Lead Penetration"]) + "\n" + "\n".join("\t".join(r) for r in [
    ["Grand Total", "Total", "Total", "Total", "Total", "5,641,548", "112,831", "67,533", "45,298", "1.20%"],
    ["1.0%", "Rafael Hidalgo", "TN", "75024", "62 Days", "1", "0", "4", "0", "400.00%"],
    ["1.0%", "Rafael Hidalgo", "TX", "75024", "2 Days", "2,440", "49", "4", "45", "0.16%"],
    ["1.0%", "Rafael Hidalgo", "TX", "75001", "23 Days", "1,084", "22", "8", "14", "0.74%"],
    ["2.3%", "Joseph Logan", "MI", "48823", "38 Days", "3,750", "75", "41", "34", "1.09%"],
])

HDR = [""] * 23 + ["Zip Code", "City", "Spanish %", "Used on line up", "Total Leads",
                   "Fiber doors", "CFWO", "Avg Household Income", "Current Penetration Rate ",
                   "Sales needed to be 1%+ Over 17 weeks", "Total Current Sales",
                   "Sales Needed to be at 2% Over 17 wks",
                   "Expected Fiber Sales over 17 wks for 2%", "Days since last Sale", "Notes"]
HDR[8] = "Zip Code"


def row(z, doors="1,031", f=""):
    r = [""] * 38
    r[23], r[28], r[32] = z, doors, f
    return r


class T(unittest.TestCase):
    def test_parse_keeps_bigger_dup_and_skips_total(self):
        d = C.parse_zips(CSV)
        self.assertEqual(set(d), {"Rafael Hidalgo", "Joseph Logan"})
        self.assertEqual(d["Rafael Hidalgo"]["75024"]["pct"], 0.0016)
        self.assertEqual(d["Rafael Hidalgo"]["75001"]["days"], 23)

    def test_layout_picks_zip_left_of_pct(self):
        lay = C.layout([[""], HDR])
        self.assertEqual(lay["zip"], 23)
        self.assertEqual(lay["cols"]["pct"], 31)
        self.assertEqual(lay["need1"], 32)

    def test_plan(self):
        vals = [[""], HDR, row("75001", f="=AC3*1%/17"), row("75999"), row("")]
        lay = C.layout(vals)
        w, s = C.plan(vals, vals, lay, C.parse_zips(CSV)["Rafael Hidalgo"])
        got = {x["range"]: x["values"][0][0] for x in w}
        self.assertEqual(got["AF3"], "0.74%")
        self.assertEqual(got["AH3"], 8)
        self.assertEqual(got["AK3"], 23)
        self.assertNotIn("AG3", got)                     # Raf's formula kept
        self.assertEqual(got["AG4"], "=AC4*1%/17")       # blank -> formula
        self.assertEqual(got["AF4"], "")                 # zip not in Tableau
        self.assertEqual(s["not_on_sheet"], ["75024"])
        self.assertEqual(s["last_row"], 3)

    def test_total_row(self):
        tot = [""] * 38
        tot[23], tot[28], tot[31], tot[32], tot[33] = "Total", "=SUM(AC3:AC4)", "?", "=AC5*1%/17", "?"
        vals = [[""], HDR, row("75001", f="=AC3*1%/17"), row("75024", f="=AC4*1%/17"), tot]
        lay = C.layout(vals)
        w, s = C.plan(vals, vals, lay, C.parse_zips(CSV)["Rafael Hidalgo"])
        got = {x["range"]: x["values"][0][0] for x in w}
        self.assertEqual(s["total_row"], 4)
        self.assertEqual(got["AH5"], "=SUM(AH3:AH4)")
        self.assertEqual(got["AK5"], "=MIN(AK3:AK4)")
        self.assertEqual(got["AF5"], "%.2f%%" % (100 * 12 / (1084 + 2440)))  # sales / leads
        self.assertNotIn("AG5", got)                     # Raf's total formula kept

    def test_tabs(self):
        t = ["Line up WE 11.29", "Line up WE 11.22", "Line Up WE 11.1", "Sales Board WE 11.29"]
        self.assertEqual(C.target_tabs(t, dt.date(2026, 11, 23)), ["Line up WE 11.29"])
        self.assertEqual(C.target_tabs(t, dt.date(2026, 11, 29)), ["Line up WE 11.29"])
        self.assertEqual(C.target_tabs(t + ["Line Up WE 12.6"], dt.date(2026, 11, 27)),
                         ["Line up WE 11.29", "Line Up WE 12.6"])
        self.assertEqual(C.target_tabs(t, dt.date(2026, 12, 2)), ["Line up WE 11.29"])

    def test_cf_replaces_old_rules(self):
        lay = C.layout([[""], HDR])
        old = [{"ranges": [{"startColumnIndex": 31, "endColumnIndex": 32}]},
               {"ranges": [{"startColumnIndex": 2, "endColumnIndex": 3}]}]
        r = C.cf_requests(7, lay, 74, old)
        self.assertEqual(r[0], {"deleteConditionalFormatRule": {"sheetId": 7, "index": 0}})
        self.assertEqual(len(r), 4)


if __name__ == "__main__":
    unittest.main()
