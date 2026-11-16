import unittest

from automations.owner_pnl.probe_apex_requests import shape, summarize


class ShapeTest(unittest.TestCase):
    def test_query_values_never_kept(self):
        k = shape("post", "https://Apex.herbjoyent.com/api/payroll?period=2026-11-08&ssn=123")
        self.assertEqual(k[:4], ("POST", "apex.herbjoyent.com", "/api/payroll", "period,ssn"))
        self.assertNotIn("123", repr(k))
        self.assertNotIn("2026-11-08", repr(k))

    def test_writes_listed_before_reads(self):
        seen = {
            shape("GET", "https://apex.herbjoyent.com/payrolls", "document"): [3, {"200"}],
            shape("POST", "https://apex.herbjoyent.com/api/export", "xhr"): [1, {"200"}],
        }
        lines = summarize(seen)
        self.assertIn("NON-READ requests (the guard must allow exactly these): 1", lines[0])
        self.assertIn("POST", lines[1])
        self.assertIn("/api/export", lines[1])
        self.assertIn("apex.herbjoyent.com x3", lines[-1])


if __name__ == "__main__":
    unittest.main()
