"""customers.all_customers shapes every rep's rows like sara.scrape()'s, the
date window holds, the stale/missing envelope fails loud, and the config wiring
points at Dylan's account + #alphalete-sales. All offline — no Sheets, no
SaraPlus, no RingCentral."""
from __future__ import annotations

import base64
import datetime as dt
import io
import unittest
from unittest import mock

from automations.rc_contact_sync_raf import config as C
from automations.rc_contact_sync_raf import customers as CU


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
ROW = {"Order ID": "RAF-1", "Order Date": "10/19/2026",
       "User Name": "WILLIE HENDERSON", "Business Name": "",
       "Customer Name": "JANE DOE", "spe.Phone": "(214) 555-0101"}


class TestAllCustomers(unittest.TestCase):
    def _run(self, env, since=dt.date(2026, 10, 13),
             until=dt.date(2026, 10, 19)):
        with mock.patch(
                "automations.rc_contact_sync_raf.customers._fetch",
                return_value=env):
            return CU.all_customers(since, until, log=lambda *a, **k: None)

    def test_shapes_like_scrape(self):
        out = self._run(_env(_csv([ROW], FIELDS)))
        self.assertEqual(out, [{
            "order_id": "RAF-1", "day": "2026-10-19",
            "order_date": "10/19/2026", "rep": "WILLIE HENDERSON",
            "business": "", "customer_name": "JANE DOE",
            "phone": "(214) 555-0101",
            "alt_phones": [], "wireless_order": "", "ban": "",
        }])

    def test_keeps_every_rep(self):
        # No roster filter: two different reps both survive.
        rows = [dict(ROW, **{"Order ID": "A", "User Name": "WILLIE HENDERSON"}),
                dict(ROW, **{"Order ID": "B", "User Name": "ZORIA JOHNSON"})]
        out = self._run(_env(_csv(rows, FIELDS)))
        self.assertEqual(sorted(c["rep"] for c in out),
                         ["WILLIE HENDERSON", "ZORIA JOHNSON"])

    def test_window_bounds(self):
        rows = [dict(ROW, **{"Order ID": "A", "Order Date": "10/12/2026"}),
                dict(ROW, **{"Order ID": "B", "Order Date": "10/13/2026"}),
                dict(ROW, **{"Order ID": "C", "Order Date": "10/19/2026"}),
                dict(ROW, **{"Order ID": "D", "Order Date": "10/20/2026"})]
        out = self._run(_env(_csv(rows, FIELDS)))
        self.assertEqual([c["order_id"] for c in out], ["B", "C"])

    def test_plain_phone_header(self):
        fields = tuple(f if f != "spe.Phone" else "Phone" for f in FIELDS)
        row = {**{k: v for k, v in ROW.items() if k != "spe.Phone"},
               "Phone": "2145550101"}
        out = self._run(_env(_csv([row], fields)))
        self.assertEqual(out[0]["phone"], "2145550101")

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


class TestUpgradeExclusion(unittest.TestCase):
    FIELDS_OT = FIELDS + ("Order Type",)

    def _run(self, rows, since=dt.date(2026, 10, 13),
             until=dt.date(2026, 10, 19)):
        with mock.patch(
                "automations.rc_contact_sync_raf.customers._fetch",
                return_value=_env(_csv(rows, self.FIELDS_OT))):
            return CU.all_customers(since, until, log=lambda *a, **k: None)

    def test_drops_upgrades_keeps_new(self):
        rows = [dict(ROW, **{"Order ID": "N", "Order Type": "New"}),
                dict(ROW, **{"Order ID": "U", "Order Type": "Upgrade"})]
        out = self._run(rows)
        self.assertEqual([c["order_id"] for c in out], ["N"])

    def test_upgrade_match_is_case_insensitive(self):
        rows = [dict(ROW, **{"Order ID": "U", "Order Type": "  upgrade "})]
        self.assertEqual(self._run(rows), [])

    def test_no_order_type_column_keeps_everything(self):
        # The plain FIELDS set (no Order Type) → nothing dropped as an upgrade.
        with mock.patch(
                "automations.rc_contact_sync_raf.customers._fetch",
                return_value=_env(_csv([ROW], FIELDS))):
            out = CU.all_customers(dt.date(2026, 10, 13),
                                   dt.date(2026, 10, 19),
                                   log=lambda *a, **k: None)
        self.assertEqual(len(out), 1)


class TestConfigWiring(unittest.TestCase):
    def test_points_at_dylans_account(self):
        # The identity the run guards on is Dylan's rc_autoread extension,
        # and the watched line is the SMS line rc_autoread reads.
        from automations.rc_autoread import run as rc
        creds = C.rc_creds()
        self.assertEqual(creds["expected_owner_id"], C.EXPECTED_OWNER_ID)
        self.assertEqual(creds["watch_extension_id"], rc.EXTENSION_ID)
        self.assertEqual(creds["jwt"], rc.JWT_TOKEN)

    def test_posts_to_alphalete_sales_only(self):
        self.assertEqual(C.CHANNELS, ["C068PH3RFSM"])
        self.assertEqual(C.CHANNEL_LABEL["C068PH3RFSM"], "#alphalete-sales")

    def test_header_has_no_markdown_stars(self):
        # ensure_named_thread bolds + dates the title; stars here would double.
        self.assertNotIn("*", C.SLACK_HEADER)


if __name__ == "__main__":
    unittest.main()
