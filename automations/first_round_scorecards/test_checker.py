import datetime as dt
import unittest

from automations.first_round_scorecards import checker as ck

ACC = {
    "khalil@x.com": {"zoom": "Khalil's Zoom", "morning": "Khalil Mansour", "afternoon": "Khalil Mansour", "key": ""},
    "zoom8@x.com": {"zoom": "ZOOM 8", "morning": "Jennifer Figueroa", "afternoon": "Mercy Ohiokhai", "key": "k" * 20},
    "zoom6@x.com": {"zoom": "ZOOM 6", "morning": "Ryan McSpadden", "afternoon": "Ryan McSpadden", "key": "r" * 20},
    "zoom2@x.com": {"zoom": "ZOOM 2", "morning": "LOST", "afternoon": "LOST", "key": ""},
    "zoom12@x.com": {"zoom": "ZOOM 12", "morning": "Raf Hidalgo 2nd funnel", "afternoon": "Miguel Zaragoza", "key": ""},
}


class Problems(unittest.TestCase):
    def test_a_zoom_with_an_office_and_no_key(self):
        got = ck.problems(ACC, seen={"zoom12@x.com"}, rejected=set(), missed={}, owners_before=None)
        self.assertIn("nokey:khalil@x.com", got)
        self.assertIn("Khalil Mansour", got["nokey:khalil@x.com"])

    def test_no_office_or_covered_by_another_key_is_not_flagged(self):
        got = ck.problems(ACC, seen={"zoom12@x.com"}, rejected=set(), missed={}, owners_before=None)
        self.assertNotIn("nokey:zoom2@x.com", got)        # LOST
        self.assertNotIn("nokey:zoom12@x.com", got)       # the creds file sees it

    def test_a_rejected_key_unless_its_login_is_seen(self):
        got = ck.problems(ACC, seen=set(), rejected={"zoom6@x.com"}, missed={}, owners_before=None)
        self.assertIn("badkey:zoom6@x.com", got)
        got = ck.problems(ACC, seen={"zoom6@x.com"}, rejected={"zoom6@x.com"}, missed={}, owners_before=None)
        self.assertNotIn("badkey:zoom6@x.com", got)       # Ryan: audited anyway

    def test_an_office_that_lost_its_zoom(self):
        got = ck.problems(ACC, seen=set(), rejected=set(), missed={},
                          owners_before=["Steve McElwee", "Khalil Mansour"])
        self.assertIn("gone:Steve McElwee", got)
        self.assertNotIn("gone:Khalil Mansour", got)

    def test_an_office_not_audited_on_purpose(self):
        acc = {"josh@x.com": {"zoom": "ZOOM JOSH", "morning": "Joshua Ghorbani",
                              "afternoon": "Joshua Ghorbani", "key": ""}}
        self.assertEqual(ck.problems(acc, set(), set(), {}, None), {})

    def test_recordings_left_out_of_the_post(self):
        got = ck.problems({}, set(), set(), {"Jennifer Figueroa": 3, "Mercy Ohiokhai": 0}, None)
        self.assertEqual(list(got), ["missed:Jennifer Figueroa"])


class Quiet(unittest.TestCase):
    """Megan 2026-10-27: Khalil's Zoom, key fine, recorded nothing for weeks."""
    ACC = {"k@x.com": {"zoom": "Khalil's Zoom", "morning": "Khalil Mansour",
                       "afternoon": "Khalil Mansour", "key": "k" * 20}}
    TUE = dt.date(2026, 10, 27)

    def quiet(self, last, day=TUE, seen=frozenset(), rejected=frozenset()):
        return ck.problems(self.ACC, set(seen), set(rejected), {}, None, last=last, day=day)

    def test_a_working_key_that_recorded_nothing(self):
        got = self.quiet({})
        self.assertIn("quiet:k@x.com", got)
        self.assertIn("in the last 7 days", got["quiet:k@x.com"])

    def test_recorded_on_one_of_the_last_two_weekdays_is_fine(self):
        self.assertEqual(self.quiet({"k@x.com": dt.date(2026, 10, 26)}, seen={"k@x.com"}), {})
        # Monday looks back to Friday, not over the weekend
        self.assertEqual(self.quiet({"k@x.com": dt.date(2026, 10, 23)}, day=dt.date(2026, 10, 26),
                                    seen={"k@x.com"}), {})

    def test_older_than_two_weekdays_says_since_when(self):
        got = self.quiet({"k@x.com": dt.date(2026, 10, 22)}, seen={"k@x.com"})
        self.assertIn("since Thu 10/22", got["quiet:k@x.com"])

    def test_an_ancient_date_reads_as_none(self):
        got = self.quiet({"k@x.com": dt.date(2021, 9, 16)}, seen={"k@x.com"})
        self.assertIn("in the last 7 days", got["quiet:k@x.com"])

    def test_bad_key_is_flagged_as_bad_key_not_quiet(self):
        got = self.quiet({}, rejected={"k@x.com"})
        self.assertEqual(list(got), ["badkey:k@x.com"])

    def test_not_checked_without_dates(self):
        self.assertEqual(ck.problems(self.ACC, set(), set(), {}, None), {})

    def test_fixed_once_it_records_again(self):
        d = ck.diff(self.quiet({"k@x.com": self.TUE}, seen={"k@x.com"}), {"quiet:k@x.com": "Q"})
        self.assertEqual(list(d["fixed"]), ["quiet:k@x.com"])


class Launch(unittest.TestCase):
    """Camila 2026-10-29: Hasan launches 11/3, ZOOM 11 records nothing until then."""
    ACC = {"z11@x.com": {"zoom": "ZOOM 11", "morning": "Hasan", "afternoon": "Hasan Salame",
                         "key": "h" * 20}}

    def quiet(self, day, last=None):
        return ck.problems(self.ACC, {"z11@x.com"}, set(), {}, None, last=last or {}, day=day)

    def test_not_quiet_before_launch_or_its_first_two_weekdays(self):
        old = {"z11@x.com": dt.date(2026, 10, 26)}
        for d in (29, 30):
            self.assertEqual(self.quiet(dt.date(2026, 10, d), old), {})
        for d in (2, 3, 4):
            self.assertEqual(self.quiet(dt.date(2026, 11, d), old), {})
        self.assertIn("quiet:z11@x.com", self.quiet(dt.date(2026, 11, 5), old))

    def test_a_zoom_shared_with_a_live_office_is_still_checked(self):
        acc = {"z11@x.com": dict(self.ACC["z11@x.com"], morning="Khalil Mansour")}
        self.assertIsNone(ck.launch(acc["z11@x.com"]))

    def test_the_open_alert_is_dropped_not_reported_fixed(self):
        self.assertIn("z11@x.com", ck.waiting(self.ACC, dt.date(2026, 10, 29)))
        self.assertNotIn("z11@x.com", ck.waiting(self.ACC, dt.date(2026, 11, 11)))


class OfficeAlerts(unittest.TestCase):
    """Megan 2026-10-27: a quiet Zoom also goes to that office's recruiting channel."""
    DAY = dt.date(2026, 10, 27)
    ACC = {"hr@precision.com": {"zoom": "Drew's Zoom", "morning": "Drew Tepper",
                                "afternoon": "Drew Tepper", "key": "d" * 20},
           "zoom9@x.com": {"zoom": "ZOOM 9", "morning": "Nobody Channel",
                           "afternoon": "Nobody Channel", "key": "n" * 20}}

    class Client:
        def __init__(self):
            self.sent = []

        def chat_postMessage(self, **kw):
            self.sent.append(kw)
            return {"ok": True, "ts": f"1.{len(self.sent)}"}

    def test_new_quiet_zoom_goes_to_its_office_channel(self):
        d = ck.diff({"quiet:hr@precision.com": "q", "quiet:zoom9@x.com": "q"}, {})
        got = ck.office_alerts(self.DAY, d, self.ACC, {"hr@precision.com": dt.date(2026, 10, 22)})
        self.assertEqual([(k, ch) for k, ch, _, _ in got], [("quiet:hr@precision.com", "C0C532LA6JY")])
        _, _, parent, reply = got[0]
        self.assertIn("Drew's Zoom", parent)
        self.assertIn("since Thu 10/22", reply)
        self.assertIn("hr@precision.com", reply)
        self.assertTrue(reply.startswith(f"<@{ck.CAMILA}>"))       # Megan 10/28: tag Camila

    def test_an_open_problem_is_not_reposted(self):
        d = ck.diff({"quiet:hr@precision.com": "q"}, {"quiet:hr@precision.com": "q"})
        self.assertEqual(ck.office_alerts(self.DAY, d, self.ACC, {}), [])

    def test_posted_then_fixed_in_the_same_thread(self):
        c = self.Client()
        d = ck.diff({"quiet:hr@precision.com": "q"}, {})
        threads = ck.post_office_alerts(c, self.DAY, d, self.ACC, {}, {})
        self.assertEqual(threads, {"quiet:hr@precision.com|C0C532LA6JY": ["C0C532LA6JY", "1.1"]})
        self.assertEqual(c.sent[1]["thread_ts"], "1.1")
        d = ck.diff({}, {"quiet:hr@precision.com": "q"})
        threads = ck.post_office_alerts(c, self.DAY, d, self.ACC, {}, threads)
        self.assertEqual(threads, {})
        self.assertEqual((c.sent[-1]["channel"], c.sent[-1]["thread_ts"]), ("C0C532LA6JY", "1.1"))
        self.assertIn("✅", c.sent[-1]["text"])

    def test_preview_goes_to_the_dm_and_keeps_no_thread(self):
        c = self.Client()
        d = ck.diff({"quiet:hr@precision.com": "q"}, {})
        self.assertEqual(ck.post_office_alerts(c, self.DAY, d, self.ACC, {}, {}, preview_channel="D1"), {})
        self.assertEqual({m["channel"] for m in c.sent}, {"D1"})


class News(unittest.TestCase):
    DAY = dt.date(2026, 10, 22)

    def test_only_new_and_fixed_make_a_post(self):
        before = {"nokey:a": "A", "nokey:b": "B"}
        self.assertIsNone(ck.texts(self.DAY, ck.diff({"nokey:a": "A", "nokey:b": "B"}, before)))
        d = ck.diff({"nokey:a": "A", "nokey:c": "C"}, before)
        self.assertEqual((list(d["new"]), list(d["open"]), list(d["fixed"])),
                         (["nokey:c"], ["nokey:a"], ["nokey:b"]))
        parent, reply = ck.texts(self.DAY, d)
        self.assertIn("Thursday, Oct 22", parent)
        self.assertIn("1 new problem, 1 fixed", parent)
        self.assertIn(f"<@{ck.CAMILA}>", parent)
        self.assertIn("⚠️ C", reply)
        self.assertIn("✅ B", reply)

    def test_one_day_problems_are_never_reported_fixed(self):
        d = ck.diff({}, {"missed:X": "x", "gone:Y": "y"})
        self.assertEqual(d["fixed"], {})

    def test_only_fixed_doesnt_tag_camila(self):
        parent, _ = ck.texts(self.DAY, ck.diff({}, {"nokey:a": "A"}))
        self.assertNotIn("<@", parent)

    def test_preview_never_tags(self):
        parent, _ = ck.texts(self.DAY, ck.diff({"nokey:a": "A"}, {}), tag=False)
        self.assertNotIn("<@", parent)


if __name__ == "__main__":
    unittest.main()
