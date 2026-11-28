"""nds_metrics.sale_revenue -- each new NDS order priced and posted, no IO."""
import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.nds_metrics import line_revenue as LR
from automations.nds_metrics import sale_revenue as SR

RATES = {
    "wireless": {"port_nonbyod": {"OOF": 213, "INFP": 193},
                 "port_byod": {"OOF": 188, "INFP": 168},
                 "new_line": 25, "upgrade_voice": 30,
                 "tablet_wearable_nonbyod": 25},
    "addons": {"unlimited_premium": 15, "unlimited_extra": 10},
}
FRI = dt.date(2026, 11, 27)


def ln(oid, idx, rep="ANAIRT TRIANA", lt="Port", dtype="Smartphone",
       plan="AT&T Premium 2.0", st="Pending Shipment", date="11/27/2026"):
    """One line as line_revenue.parse_feed hands it over."""
    return {"order_id": oid, "customer": "MIKE MCGINN", "order_date": date,
            "salesperson": rep, "order_status": "", "line_idx": str(idx),
            "line_type": lt, "device_type": dtype, "tn": "81793966%02d" % idx,
            "device": "", "plan": plan, "line_status": st, "ship_date": "",
            "delivered": "", "port_status": ""}


ANAIRT = [ln("DSI164", i) for i in range(1, 7)]


class Pricing(unittest.TestCase):
    def test_six_new_phone_ports_on_premium_is_1368(self):
        # Anairt's 11/27 order: 6 x ($213 port + $15 Premium)
        p = SR.price(ANAIRT, RATES)
        self.assertEqual(p["total"], 1368)
        self.assertEqual(SR.describe(p), "6 new phones · Premium")
        rows = SR.lines_for({"DSI164": ANAIRT}, ["DSI164"], FRI, RATES)
        self.assertEqual(rows[0][1], "AT&amp;T — :dollar: Anairt's sale = $1,368 · 6 new phones · Premium")

    def test_mixed_order_prices_like_the_board(self):
        order = [ln("D1", 1), ln("D1", 2),
                 ln("D1", 3, dtype="BYOD", plan="AT&T Extra 2.0"),
                 ln("D1", 4, lt="New", plan="AT&T Value 2.0"),
                 ln("D1", 5, st="Cancelled")]
        p = SR.price(order, RATES)
        # 2 x (213 + 15) + (188 + 10) + 25; the cancelled line is $0
        self.assertEqual(p["total"], 2 * 228 + 198 + 25)
        self.assertEqual(p["cancelled"], 1)
        self.assertEqual(SR.describe(p), "2 new phones · 1 BYOD · 1 new number · 2 Premium · 1 Extra")

    def test_upgrade_and_tablet_words(self):
        p = SR.price([ln("D2", 1, lt="Upgrade", plan=""), ln("D2", 2, lt="Tablet", dtype="Tablet", plan="")], RATES)
        self.assertEqual(p["total"], 30 + 25)
        self.assertEqual(SR.describe(p), "1 upgrade · 1 tablet/watch")

    def test_an_all_cancelled_order_is_not_posted(self):
        rows = SR.lines_for({"D3": [ln("D3", 1, st="Cancelled")]}, ["D3"], FRI, RATES)
        self.assertEqual(rows, [])

    def test_only_that_days_orders(self):
        lines = ANAIRT + [ln("OLD", 1, date="11/26/2026")]
        self.assertEqual(list(SR.order_groups(lines, FRI)), ["DSI164"])


class Names(unittest.TestCase):
    def test_first_name_unless_two_sellers_share_it(self):
        got = SR.display_names({"DANIEL TORRES MARTINEZ", "DANIEL GONZALEZ", "ANAIRT TRIANA"})
        self.assertEqual(got["ANAIRT TRIANA"], "Anairt")
        self.assertEqual(got["DANIEL TORRES MARTINEZ"], "Daniel M.")
        self.assertEqual(got["DANIEL GONZALEZ"], "Daniel G.")

    def test_esmeraldas_login_is_jacob(self):
        # the shout-outs' standing swap (rep_names.SOLD_UNDER_FROM, 11/25)
        self.assertEqual(SR.seller("ESMERALDA RAMIREZ", FRI), "Jacob Ortega")
        self.assertEqual(SR.seller("ANAIRT TRIANA", FRI), "ANAIRT TRIANA")


class Clock(unittest.TestCase):
    def test_hours(self):
        at = lambda h, m: dt.datetime(2026, 11, 28, h, m)  # noqa: E731
        self.assertIsNone(SR.sale_day(at(9, 59)))
        self.assertEqual(SR.sale_day(at(10, 0)), dt.date(2026, 11, 28))
        self.assertEqual(SR.sale_day(at(23, 59)), dt.date(2026, 11, 28))
        self.assertEqual(SR.sale_day(at(0, 10)), dt.date(2026, 11, 27))   # an 11:58pm sale still gets its line
        self.assertIsNone(SR.sale_day(at(0, 21)))


class FakeClient:
    def __init__(self):
        self.sent = []

    def chat_postMessage(self, channel, text):
        self.sent.append((channel, text))


class Check(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state.json"
        self.client = FakeClient()
        self.feed = []
        rates = mock.patch.object(LR, "sow_rates", lambda: RATES)
        parse = mock.patch.object(LR, "parse_feed", lambda data: list(self.feed))
        rates.start(), parse.start()
        self.addCleanup(rates.stop)
        self.addCleanup(parse.stop)
        self.addCleanup(self.tmp.cleanup)

    def run_at(self, h, m, **kw):
        logs = []
        SR.check(dt.datetime(2026, 11, 27, h, m), pull=lambda day: b"", client=self.client,
                 log=logs.append, state_path=self.state, **kw)
        return logs

    def test_posts_each_order_once(self):
        self.run_at(10, 5, post=True)                      # first check of the day, nothing sold yet
        self.assertEqual(self.client.sent, [])
        self.feed = list(ANAIRT)
        self.run_at(21, 55, post=True)
        self.assertEqual(len(self.client.sent), 1)
        self.assertEqual(self.client.sent[0][0], "C07J46MQNUX")
        self.assertIn("Anairt's sale = $1,368", self.client.sent[0][1])
        self.feed = list(ANAIRT) + [ln("DSI165", 1, rep="STEFANY MICHELLE ZALDIVAR JUSTINIANO",
                                       plan="AT&T Extra 2.0")]
        self.run_at(22, 0, post=True)
        self.assertEqual(len(self.client.sent), 2)
        self.assertEqual(self.client.sent[1][1], "AT&amp;T — :dollar: Stefany's sale = $223 · 1 new phone · Extra")
        self.run_at(22, 5, post=True)                      # nothing new
        self.assertEqual(len(self.client.sent), 2)

    def test_a_late_first_check_records_the_backlog(self):
        # Lucy 2 off until 2pm (or just switched on): the day's orders are not news
        self.feed = list(ANAIRT)
        logs = self.run_at(14, 0, post=True)
        self.assertEqual(self.client.sent, [])
        self.assertIn("RECORDING ONLY", logs[0])
        self.feed = list(ANAIRT) + [ln("DSI170", 1, rep="FERNANDO SALAZAR")]
        self.run_at(14, 5, post=True)
        self.assertEqual(len(self.client.sent), 1)
        self.assertIn("Fernando's sale = $228", self.client.sent[0][1])

    def test_dry_run_posts_and_remembers_nothing(self):
        self.feed = list(ANAIRT)
        logs = self.run_at(10, 5)
        self.assertEqual(self.client.sent, [])
        self.assertFalse(self.state.exists())
        self.assertTrue(any("DRY RUN" in l for l in logs))
        self.assertTrue(any("Anairt's sale = $1,368" in l for l in logs))

    def test_baseline_remembers_without_posting(self):
        self.feed = list(ANAIRT)
        self.run_at(10, 5, baseline=True)
        self.assertEqual(self.client.sent, [])
        self.run_at(10, 10, post=True)
        self.assertEqual(self.client.sent, [])

    def test_outside_hours_pulls_nothing(self):
        pulled = []
        SR.check(dt.datetime(2026, 11, 27, 8, 0), post=True, pull=lambda d: pulled.append(d) or b"",
                 client=self.client, log=lambda *_: None, state_path=self.state)
        self.assertEqual(pulled, [])


class Profile(unittest.TestCase):
    def test_busy_only_while_the_lock_owner_lives(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(SR.profile_busy(Path(d)))
            os.symlink("lucy2-%d" % os.getpid(), os.path.join(d, "SingletonLock"))
            self.assertTrue(SR.profile_busy(Path(d)))
        with tempfile.TemporaryDirectory() as d:
            os.symlink("lucy2-999999", os.path.join(d, "SingletonLock"))
            self.assertFalse(SR.profile_busy(Path(d)))

    def test_own_feed_copy_is_not_a_morning_feed(self):
        # the revenue board replays every nds_wireless_<date>.html as a morning pull
        self.assertIsNone(LR.FEED_RE.match(SR.FEED.name))


if __name__ == "__main__":
    unittest.main()
