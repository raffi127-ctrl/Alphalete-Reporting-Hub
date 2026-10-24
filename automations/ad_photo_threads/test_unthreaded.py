import datetime as dt
import unittest
from types import SimpleNamespace
from unittest import mock

from automations.ad_photo_threads import unthreaded
from automations.ad_photo_threads.collect import Candidate


def cand(name, title, ad=None):
    return Candidate(name=name, title_raw=title, interviewer="", qualify="",
                     stars="", source="", ad=ad)


class MessageTests(unittest.TestCase):
    """Eve 10/21: interviews with no thread, said in the office's channel."""
    D = dt.date(2026, 10, 19)

    def test_nothing_missing_says_nothing(self):
        self.assertEqual(unthreaded.message([], True), "")

    def test_blank_and_unlisted_tag_the_channel(self):
        text = unthreaded.message([(self.D, cand("Jamar Gray", "")),
                                   (self.D, cand("Ana", "AT&T Sales Representative, Denton, TX")),
                                   (self.D, cand("Bo", "AT&T Sales Representative, Denton, TX"))],
                                  title_only=True)
        self.assertTrue(text.startswith("<!channel> 3 1st rounds"))
        self.assertIn("Jamar Gray (10/19)", text)
        self.assertIn('"AT&T Sales Representative, Denton, TX" (2)', text)
        self.assertIn("new ad", text)

    def test_office_without_a_list_asks_for_spelling(self):
        text = unthreaded.message([(self.D, cand("Ana", "Sales ???"))], title_only=False)
        self.assertIn("spelling", text)
        self.assertNotIn("Reply here", text)

    def test_placeholders_count_as_blank(self):
        text = unthreaded.message([(self.D, cand("Ana", "-")), (self.D, cand("Bo", "N/A"))], True)
        self.assertIn("No Ad Title in the sheet:* Ana (10/19), Bo (10/19)", text)
        self.assertNotIn("not recognized", text)

    def test_placeholder_name_is_not_a_person(self):
        build = lambda d, cl=None, cache=None: SimpleNamespace(  # noqa: E731
            candidates=[cand("N/A", "")])
        self.assertEqual(unthreaded.find(dt.date(2026, 10, 21), build=build), [])


class CheckTests(unittest.TestCase):
    def test_each_interview_is_said_once(self):
        state = {}
        day = dt.date(2026, 10, 21)
        reps = {d: SimpleNamespace(candidates=[cand("Jamar Gray", "")] if d == dt.date(2026, 10, 19)
                                   else [cand("Ok", "x", ad="k")])
                for d in (day - dt.timedelta(days=n) for n in range(1, 8))}
        build = lambda d, cl=None, cache=None: reps[d]   # noqa: E731
        cl = mock.Mock()
        with mock.patch.object(unthreaded.post, "_load_state", lambda: state), \
                mock.patch.object(unthreaded.post, "_save_state", lambda s: None):
            first = unthreaded.check(day, "C1", title_only=True, cl=cl, build=build)
            again = unthreaded.check(day, "C1", title_only=True, cl=cl, build=build)
        self.assertTrue(first["posted"])
        self.assertFalse(again["posted"])
        self.assertEqual(cl.chat_postMessage.call_count, 1)

    def test_dry_run_posts_nothing(self):
        day = dt.date(2026, 10, 21)
        build = lambda d, cl=None, cache=None: SimpleNamespace(  # noqa: E731
            candidates=[cand("Jamar Gray", "")])
        cl = mock.Mock()
        with mock.patch.object(unthreaded.post, "_load_state", lambda: {}):
            got = unthreaded.check(day, "C1", title_only=True, cl=cl, build=build, apply=False)
        self.assertIn("Jamar Gray", got["text"])
        cl.chat_postMessage.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class CallListTests(unittest.TestCase):
    """Eve 10/24: a blank Ad Title is looked up on the Call List before the
    channel is asked -- only when it's one ad the office already runs."""
    D = dt.date(2026, 10, 22)

    def setUp(self):
        from automations.ad_photo_threads.titles import TitleBook
        self.book = TitleBook(["AT&T Sales Agent, McKinney, TX"] * 3
                              + ["AT&T Team Member, Frisco, TX"] * 3)

    def ad(self, seen, name="Carlo Palacio", oids=("22583",)):
        from automations.ad_photo_threads import collect
        return collect.call_list_ad(cand(name, ""), self.D, set(oids), self.book, seen=seen)

    def test_one_running_ad_fills_it(self):
        seen = {("22583", "carlo palacio"): [(dt.date(2026, 10, 20), "AT&T Sales Agent, McKinney, TX")]}
        self.assertEqual(self.ad(seen), self.book.resolve("AT&T Sales Agent, McKinney, TX"))

    def test_two_ads_stay_asked(self):
        seen = {("22583", "carlo palacio"): [(dt.date(2026, 10, 20), "AT&T Sales Agent, McKinney, TX"),
                                             (dt.date(2026, 10, 21), "AT&T Team Member, Frisco, TX")]}
        self.assertIsNone(self.ad(seen))

    def test_an_ad_with_no_thread_is_not_started(self):
        seen = {("22583", "carlo palacio"): [(dt.date(2026, 10, 20), "Verizon Retail Associate, Plano, TX")]}
        self.assertIsNone(self.ad(seen))

    def test_other_office_or_too_old_or_later_does_not_count(self):
        ad = "AT&T Sales Agent, McKinney, TX"
        self.assertIsNone(self.ad({("11280", "carlo palacio"): [(dt.date(2026, 10, 20), ad)]}))
        self.assertIsNone(self.ad({("22583", "carlo palacio"): [(dt.date(2026, 7, 1), ad)]}))
        self.assertIsNone(self.ad({("22583", "carlo palacio"): [(dt.date(2026, 10, 23), ad)]}))

    def test_placeholders_are_blank(self):
        from automations.ad_photo_threads import collect
        self.assertTrue(all(collect.blank_title(s) for s in ["", " ", "-", "N/A", "none"]))
        self.assertFalse(collect.blank_title("AT&T Sales Agent"))
