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
            "phone": "(214) 555-0101", "products": [],
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


class TestProductTags(unittest.TestCase):
    FIELDS_P = FIELDS + ("Internet Package", "Video Package",
                         "Wireless Line Count")

    def _run(self, row):
        with mock.patch(
                "automations.rc_contact_sync_raf.customers._fetch",
                return_value=_env(_csv([row], self.FIELDS_P))):
            return CU.all_customers(dt.date(2026, 10, 13),
                                    dt.date(2026, 10, 19),
                                    log=lambda *a, **k: None)[0]["products"]

    def test_all_three(self):
        row = dict(ROW, **{"Internet Package": "Internet 1000 (Fiber 1 GIG)",
                           "Video Package": "DIRECTV CHOICE",
                           "Wireless Line Count": "2"})
        self.assertEqual(self._run(row), ["Internet", "TV", "Wireless"])

    def test_internet_only(self):
        row = dict(ROW, **{"Internet Package": "Internet 500",
                           "Video Package": "", "Wireless Line Count": "0"})
        self.assertEqual(self._run(row), ["Internet"])

    def test_wireless_zero_is_not_tagged(self):
        row = dict(ROW, **{"Internet Package": "", "Video Package": "",
                           "Wireless Line Count": "0"})
        self.assertEqual(self._run(row), [])

    def test_no_product_columns_empty(self):
        with mock.patch(
                "automations.rc_contact_sync_raf.customers._fetch",
                return_value=_env(_csv([ROW], FIELDS))):
            out = CU.all_customers(dt.date(2026, 10, 13),
                                   dt.date(2026, 10, 19),
                                   log=lambda *a, **k: None)
        self.assertEqual(out[0]["products"], [])


class TestReplyTagging(unittest.TestCase):
    def _reply(self, missing, total, idmap):
        from automations.rc_contact_sync_raf import run as R
        with mock.patch("automations.shared.slack_tag_learning.lookup",
                        side_effect=lambda n: idmap.get(n)):
            return R.missing_names_reply(missing, total)

    def _cust(self, rep, name, phone="214-000-0000", products=("Internet",)):
        return {"rep": rep, "business": "", "customer_name": name,
                "phone": phone, "products": list(products), "alt_phones": [],
                "wireless_order": "", "ban": ""}

    def test_resolved_rep_bold_header_and_tagged_at_bottom(self):
        out = self._reply([self._cust("Jordan Ruiz", "Yani Young")], 5,
                          {"Jordan Ruiz": "U0B36GDTT6F"})
        # original look: a bold name header in the list…
        self.assertIn("*Jordan Ruiz*", out)
        # …and the @mention down at the bottom, after the customer lines.
        self.assertIn("<@U0B36GDTT6F>", out)
        self.assertLess(out.index("Yani Young"), out.index("<@U0B36GDTT6F>"))

    def test_unresolved_rep_stays_bold_no_warning(self):
        # Dylan 2026-11-02: an unresolved rep is just a bold name — NO public
        # "couldn't tag" warning anymore.
        out = self._reply([self._cust("Alexis Renteria", "Jazmin Garcia")], 5,
                          {})   # nobody resolves
        self.assertIn("*Alexis Renteria*", out)
        self.assertNotIn("<@", out)
        self.assertNotIn("No Slack match", out)
        self.assertNotIn(":warning:", out)

    def test_rep_stats_streak_and_week(self):
        from automations.rc_contact_sync_raf import run as R
        with mock.patch("automations.shared.slack_tag_learning.lookup",
                        side_effect=lambda n: None):
            out = R.missing_names_reply(
                [self._cust("Jordan Ruiz", "Yani")], 5,
                rep_stats={"Jordan Ruiz": (3, 4)})
        self.assertIn("3 days in a row", out)
        self.assertIn("4x this week", out)

    def test_rep_stats_streak_hidden_when_one(self):
        from automations.rc_contact_sync_raf import run as R
        with mock.patch("automations.shared.slack_tag_learning.lookup",
                        side_effect=lambda n: None):
            out = R.missing_names_reply(
                [self._cust("Jordan Ruiz", "Yani")], 5,
                rep_stats={"Jordan Ruiz": (1, 1)})
        self.assertNotIn("in a row", out)      # streak of 1 isn't shown
        self.assertIn("1x this week", out)

    def test_line_has_phone_and_products(self):
        out = self._reply(
            [self._cust("Hank Tran", "Rebecca Alcantara", "469-343-5714",
                        ("Internet", "TV", "Wireless"))], 5,
            {"Hank Tran": "U0BRVG0U0QP"})
        self.assertIn("469-343-5714 — Internet, TV, Wireless", out)


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


class TestHistory(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from automations.rc_contact_sync_raf import history as H
        self.H = H
        self._orig = H.STORE
        H.STORE = Path(tempfile.mkdtemp()) / "hist.json"

    def tearDown(self):
        self.H.STORE = self._orig

    def _go(self, day, reps):
        return self.H.update_and_stats("C1", reps, day, persist=True)

    def test_streak_counts_consecutive_run_days(self):
        d = dt.date
        self._go(d(2026, 11, 2), ["Rep X"])
        self._go(d(2026, 11, 3), ["Rep X"])
        s = self._go(d(2026, 11, 4), ["Rep X"])
        self.assertEqual(s["Rep X"], (3, 3))   # 3 in a row, 3x this week

    def test_clean_run_day_breaks_streak(self):
        d = dt.date
        self._go(d(2026, 11, 2), ["Rep Y"])
        self._go(d(2026, 11, 3), ["Someone Else"])   # Rep Y clean this run
        s = self._go(d(2026, 11, 4), ["Rep Y"])
        self.assertEqual(s["Rep Y"], (1, 2))   # streak reset, but 2x this week

    def test_non_run_day_does_not_break_streak(self):
        d = dt.date
        # Sat then Mon (no run on Sun) — still 2 in a row.
        self._go(d(2026, 11, 7), ["Rep Z"])
        s = self._go(d(2026, 11, 9), ["Rep Z"])
        self.assertEqual(s["Rep Z"][0], 2)

    def test_week_count_is_mon_to_sun(self):
        d = dt.date
        # 11/1 is a Sunday (prev week); 11/2 Mon starts the new week.
        self._go(d(2026, 11, 1), ["Rep W"])
        s = self._go(d(2026, 11, 2), ["Rep W"])
        self.assertEqual(s["Rep W"][1], 1)   # only Monday counts this week

    def test_rerun_same_day_is_idempotent(self):
        d = dt.date
        self._go(d(2026, 11, 2), ["Rep Q"])
        s = self._go(d(2026, 11, 2), ["Rep Q"])   # same day again
        self.assertEqual(s["Rep Q"], (1, 1))


if __name__ == "__main__":
    unittest.main()
