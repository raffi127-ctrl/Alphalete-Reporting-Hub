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
