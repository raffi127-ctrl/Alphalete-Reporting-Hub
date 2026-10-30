import datetime as dt
import unittest
from types import SimpleNamespace
from unittest import mock

from automations.ad_photo_threads import unthreaded
from automations.ad_photo_threads.collect import Candidate


def cand(name, title, ad=None):
    return Candidate(name=name, title_raw=title, interviewer="", qualify="",
                     stars="", source="", ad=ad)


class LineTests(unittest.TestCase):
    """Eve 10/29: interviews with no ad go to one pinned thread, not @channel."""
    D = dt.date(2026, 10, 19)

    def test_blank_and_unlisted_say_why(self):
        self.assertIn("Jamar Gray (10/19): no Ad Title",
                      unthreaded.line(self.D, cand("Jamar Gray", ""), True))
        self.assertIn("new ad", unthreaded.line(self.D, cand("Ana", "AT&T Denton"), True))
        self.assertIn("misspelled", unthreaded.line(self.D, cand("Ana", "Sales ???"), False))

    def test_placeholders_count_as_blank(self):
        self.assertIn("no Ad Title", unthreaded.line(self.D, cand("Ana", "N/A"), True))

    def test_placeholder_name_is_not_a_person(self):
        build = lambda d, cl=None, cache=None: SimpleNamespace(  # noqa: E731
            candidates=[cand("N/A", "")])
        self.assertEqual(unthreaded.find(dt.date(2026, 10, 21), build=build), [])


class CheckTests(unittest.TestCase):
    DAY = dt.date(2026, 10, 21)
    MISS = dt.date(2026, 10, 19)

    def run_check(self, state, people, cl, **kw):
        reps = {d: SimpleNamespace(candidates=people if d == self.MISS
                                   else [cand("Ok", "x", ad="k")])
                for d in (self.DAY - dt.timedelta(days=n) for n in range(1, 8))}
        build = lambda d, cl=None, cache=None: reps[d]   # noqa: E731
        with mock.patch.object(unthreaded.post, "_load_state", lambda: state),                 mock.patch.object(unthreaded.post, "_save_state", lambda s: None),                 mock.patch.object(unthreaded.post, "_thread_alive", lambda *a: True):
            return unthreaded.check(self.DAY, "C1", title_only=True, cl=cl, build=build, **kw)

    def client(self):
        cl = mock.Mock()
        n = iter(range(100, 200))
        cl.chat_postMessage.side_effect = lambda **k: {"ts": f"{next(n)}.0"}
        return cl

    def test_one_pinned_thread_no_channel_tag(self):
        state, cl = {}, self.client()
        first = self.run_check(state, [cand("Jamar Gray", "")], cl)
        again = self.run_check(state, [cand("Jamar Gray", ""), cand("Bo", "")], cl)
        self.assertTrue(first["posted"] and again["posted"])
        calls = cl.chat_postMessage.call_args_list
        self.assertEqual(len(calls), 3)              # header + one reply per evening
        self.assertNotIn("thread_ts", calls[0].kwargs)
        self.assertEqual(calls[1].kwargs["thread_ts"], "100.0")
        self.assertEqual(calls[2].kwargs["thread_ts"], "100.0")
        self.assertNotIn("Jamar", calls[2].kwargs["text"])
        self.assertTrue(all("<!channel>" not in c.kwargs["text"] for c in calls))
        cl.pins_add.assert_called_once_with(channel="C1", timestamp="100.0")
        self.assertIn("<@U07FWSYP3NV>", calls[1].kwargs["text"])   # Camila
        self.assertIn("<@U07R68ZGHT6>", calls[1].kwargs["text"])   # Perla

    def test_waits_while_appstream_still_looking(self):
        k = "2026-10-19|jamar gray"
        state = {"C1": {"appstream_ads": {k: ""}, "appstream_ads_tries": {k: ["a", "b"]}}}
        cl = self.client()
        got = self.run_check(state, [cand("Jamar Gray", "")], cl, lookup_on=True)
        self.assertEqual((got["waiting"], got["posted"]), (1, False))
        cl.chat_postMessage.assert_not_called()
        state["C1"]["appstream_ads_tries"][k].append("c")
        got = self.run_check(state, [cand("Jamar Gray", "")], cl, lookup_on=True)
        self.assertTrue(got["posted"])

    def test_typed_title_goes_in_right_away(self):
        got = self.run_check({}, [cand("Ana", "Unknown ad")], self.client(), lookup_on=True)
        self.assertTrue(got["posted"])

    def test_placed_later_is_crossed_out(self):
        state, cl = {}, self.client()
        self.run_check(state, [cand("Jamar Gray", "")], cl)
        got = self.run_check(state, [], cl)
        self.assertEqual(got["placed"], 1)
        text = cl.chat_update.call_args.kwargs["text"]
        self.assertIn("~", text)
        self.assertIn("placed", text)

    def test_dry_run_posts_nothing(self):
        cl = self.client()
        got = self.run_check({}, [cand("Jamar Gray", "")], cl, apply=False)
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


class SweepOldNotesTests(unittest.TestCase):
    """Eve 10/30: the old @channel notes come down; their people get placed."""
    DAY = dt.date(2026, 10, 30)

    def test_landed_placed_rest_threaded_notes_deleted(self):
        d = dt.date(2026, 10, 27)
        people = [cand("Ana Ruiz", "AT&T Agent", ad="k"), cand("Bo Lee", "")]
        build = lambda day, cl=None, cache=None: SimpleNamespace(  # noqa: E731
            candidates=people if day == d else [])
        state = {"C1": {"unthreaded_said": ["2026-10-27|ana ruiz", "2026-10-27|bo lee",
                                            "2026-10-01|old one"]}}
        cl = mock.Mock()
        cl.auth_test.return_value = {"user_id": "ULUCY"}
        cl.conversations_history.return_value = {"messages": [
            {"ts": "1793100000.1", "user": "ULUCY", "text": "<!channel> 2 1st rounds didn't land on any ad thread:"},
            {"ts": "1793100000.2", "user": "UEVE", "text": "how can we fix this? didn't land on any ad thread"},
            {"ts": "1793100000.3", "user": "ULUCY", "text": "something else"}]}
        n = iter(range(100, 200))
        cl.chat_postMessage.side_effect = lambda **k: {"ts": f"{next(n)}.0"}
        added = {}
        with mock.patch.object(unthreaded.post, "_load_state", lambda: state), \
                mock.patch.object(unthreaded.post, "_save_state", lambda s: None), \
                mock.patch.object(unthreaded.post, "_pin", lambda *a: None), \
                mock.patch.object(unthreaded.post, "add_photos",
                                  lambda rep, ch, names, cl=None: added.update(
                                      {x: "added 1 photo(s)" for x in names}) or
                                  {x: "added 1 photo(s)" for x in names}), \
                mock.patch("automations.ad_photo_threads.weekly.is_weekly", lambda ch: False):
            dry = unthreaded.sweep_old(self.DAY, "C1", title_only=False,
                                       since=dt.date(2026, 10, 14), cl=cl, build=build)
            self.assertEqual(dry["landed"], ["2026-10-27|ana ruiz"])
            self.assertEqual(dry["no_ad"], ["2026-10-27 Bo Lee"])
            cl.chat_delete.assert_not_called()
            cl.chat_postMessage.assert_not_called()
            got = unthreaded.sweep_old(self.DAY, "C1", title_only=False, apply=True,
                                       since=dt.date(2026, 10, 14), cl=cl, build=build)
        self.assertEqual(added, {"Ana Ruiz": "added 1 photo(s)"})
        self.assertEqual(got["deleted"], 1)
        cl.chat_delete.assert_called_once_with(channel="C1", ts="1793100000.1")
        reply = cl.chat_postMessage.call_args_list[-1].kwargs["text"]
        self.assertIn("Bo Lee (10/27)", reply)
        for u in unthreaded.TAG_USERS:
            self.assertIn(f"<@{u}>", reply)
        self.assertNotIn("<!channel>", reply)
