"""guest.py: envelope rows shape exactly like sara.scrape()'s, the date
window holds, header variants resolve, and the daily wrapper fails OPEN while
the backfill fails LOUD. All offline — no Sheets, no SaraPlus, no RingCentral."""
from __future__ import annotations

import base64
import datetime as dt
import io
import unittest
from unittest import mock

from automations.rc_contact_sync import guest as G


def _csv(rows, fields):
    out = io.StringIO()
    out.write(",".join(fields) + "\n")
    for r in rows:
        out.write(",".join(str(r.get(f, "")) for f in fields) + "\n")
    return out.getvalue().encode("utf-8-sig")


def _env(csv_bytes, *, hours_old=0.0):
    pulled = dt.datetime.now() - dt.timedelta(hours=hours_old)
    return {"pulled": pulled.isoformat(timespec="seconds"),
            "rows": 1, "csv": base64.b64encode(csv_bytes).decode()}


FIELDS = ("Order ID", "Order Date", "User Name", "Business Name",
          "Customer Name", "spe.Phone")
ROW = {"Order ID": "RAF-1", "Order Date": "10/6/2026",
       "User Name": "JORGE GRAMAJO", "Business Name": "ACME LLC",
       "Customer Name": "JANE DOE", "spe.Phone": "(210) 555-0101"}


class TestGuestCustomers(unittest.TestCase):
    def _run(self, env, since=dt.date(2026, 9, 29), until=dt.date(2026, 10, 7)):
        with mock.patch("automations.sp_order_log.raf_guest.fetch",
                        return_value=env):
            return G.guest_customers(since, until, log=lambda *a, **k: None)

    def test_shapes_like_scrape(self):
        out = self._run(_env(_csv([ROW], FIELDS)))
        self.assertEqual(out, [{
            "order_id": "RAF-1", "day": "2026-10-06",
            "order_date": "10/6/2026", "rep": "JORGE GRAMAJO",
            "business": "ACME LLC", "customer_name": "JANE DOE",
            "phone": "(210) 555-0101",
        }])

    def test_window_bounds(self):
        rows = [dict(ROW, **{"Order ID": "A", "Order Date": "9/28/2026"}),
                dict(ROW, **{"Order ID": "B", "Order Date": "9/29/2026"}),
                dict(ROW, **{"Order ID": "C", "Order Date": "10/7/2026"}),
                dict(ROW, **{"Order ID": "D", "Order Date": "10/8/2026"})]
        out = self._run(_env(_csv(rows, FIELDS)))
        self.assertEqual([c["order_id"] for c in out], ["B", "C"])

    def test_plain_phone_header(self):
        fields = tuple(f if f != "spe.Phone" else "Phone" for f in FIELDS)
        row = {**{k: v for k, v in ROW.items() if k != "spe.Phone"},
               "Phone": "2105550101"}
        out = self._run(_env(_csv([row], fields)))
        self.assertEqual(out[0]["phone"], "2105550101")

    def test_no_phone_column_row_survives(self):
        fields = tuple(f for f in FIELDS if f != "spe.Phone")
        row = {k: v for k, v in ROW.items() if k != "spe.Phone"}
        out = self._run(_env(_csv([row], fields)))
        self.assertEqual(out[0]["phone"], "")

    def test_missing_required_column_raises(self):
        fields = tuple(f for f in FIELDS if f != "Customer Name")
        row = {k: v for k, v in ROW.items() if k != "Customer Name"}
        with self.assertRaises(RuntimeError):
            self._run(_env(_csv([row], fields)))

    def test_stale_envelope_raises(self):
        with self.assertRaises(RuntimeError):
            self._run(_env(_csv([ROW], FIELDS), hours_old=48))

    def test_missing_envelope_raises(self):
        with self.assertRaises(RuntimeError):
            self._run(None)


class TestForDay(unittest.TestCase):
    def test_fails_open_with_reason(self):
        with mock.patch("automations.sp_order_log.raf_guest.fetch",
                        return_value=None):
            out, err = G.for_day(dt.date(2026, 10, 7),
                                 log=lambda *a, **k: None)
        self.assertEqual(out, [])
        self.assertIn("RuntimeError", err)

    def test_single_day(self):
        env = _env(_csv([ROW], FIELDS))
        with mock.patch("automations.sp_order_log.raf_guest.fetch",
                        return_value=env):
            out, err = G.for_day(dt.date(2026, 10, 6),
                                 log=lambda *a, **k: None)
        self.assertIsNone(err)
        self.assertEqual(len(out), 1)
        with mock.patch("automations.sp_order_log.raf_guest.fetch",
                        return_value=env):
            out, err = G.for_day(dt.date(2026, 10, 5),
                                 log=lambda *a, **k: None)
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()


class TestResidentialHeader(unittest.TestCase):
    def test_no_business_column_is_fine(self):
        fields = tuple(f for f in FIELDS if f != "Business Name")
        row = {k: v for k, v in ROW.items() if k != "Business Name"}
        env = _env(_csv([row], fields))
        with mock.patch("automations.sp_order_log.raf_guest.fetch",
                        return_value=env):
            out = G.guest_customers(dt.date(2026, 9, 29),
                                    dt.date(2026, 10, 7),
                                    log=lambda *a, **k: None)
        self.assertEqual(out[0]["business"], "")
        self.assertEqual(out[0]["customer_name"], "JANE DOE")
