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

    def test_recordings_left_out_of_the_post(self):
        got = ck.problems({}, set(), set(), {"Jennifer Figueroa": 3, "Mercy Ohiokhai": 0}, None)
        self.assertEqual(list(got), ["missed:Jennifer Figueroa"])


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
