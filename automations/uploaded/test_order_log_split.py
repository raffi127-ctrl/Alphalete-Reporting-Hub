"""Letter posts: index first, post links to it, and the too-big switch.

    python -m unittest automations.uploaded.test_order_log_split
"""
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from openpyxl import Workbook

from automations.uploaded import order_log, order_log_split as ols


def _book(path: Path, reps: int, rows: int) -> Path:
    wb = Workbook()
    wb.active.title = ols.LOG_TAB
    wb.active.append(["Rep", "Order Date"])
    for i in range(rows):
        wb.active.append([f"Rep {i % max(reps, 1)}", "10/1"])
    for i in range(reps):
        wb.create_sheet(f"Rep {i}").append(["Order Date"])
    wb.save(path)
    return path


class FakeClient:
    def __init__(self):
        self.calls, self.n = [], 0

    def chat_postMessage(self, **kw):
        self.n += 1
        ts = f"{self.n}.0"
        self.calls.append(("post", ts, kw))
        return {"ts": ts}

    def chat_update(self, **kw):
        self.calls.append(("update", kw["ts"], kw))
        return {"ok": True}

    def chat_getPermalink(self, channel, message_ts):
        return {"permalink": f"https://x/{message_ts}"}

    def files_upload_v2(self, **kw):
        return {"file": {"id": "F1", "permalink": "https://x/file"}}


class TestLimit(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = Path(d.name)

    def test_small_file_is_not_over(self):
        over, rows, tabs = ols.over_phone_limit(_book(self.dir / "a.xlsx", 5, 100))
        self.assertEqual((over, rows, tabs), (False, 100, 5))

    def test_too_many_rows_is_over(self):
        self.assertTrue(ols.over_phone_limit(
            _book(self.dir / "a.xlsx", 5, ols.ROW_WARN + 1))[0])

    def test_too_many_tabs_is_over(self):
        self.assertTrue(ols.over_phone_limit(
            _book(self.dir / "a.xlsx", ols.TAB_WARN + 1, 100))[0])

    def test_broken_file_stays_on_single_file(self):
        self.assertFalse(order_log.too_big_for_phone(self.dir / "missing.xlsx"))


class TestThread(unittest.TestCase):
    def test_index_is_first_reply_and_post_links_to_it(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            book = _book(d / "Order Log.xlsx", 2, 4)
            c = FakeClient()
            with mock.patch.object(ols, "rep_files", return_value=[("Ana", book), ("Bo", book)]), \
                    mock.patch("time.sleep"):
                ols.post_threads(c, "C1", [("A-F", book)], d, "11-01-2026")
        posts = [x for x in c.calls if x[0] == "post"]
        parent, index = posts[0], posts[1]
        self.assertIn("Tap your name", index[2]["text"])
        self.assertEqual(index[2]["thread_ts"], parent[1])
        updates = {x[1]: x[2]["text"] for x in c.calls if x[0] == "update"}
        self.assertIn("Ana", updates[index[1]])
        self.assertIn("Bo", updates[index[1]])
        self.assertIn(f"https://x/{index[1]}|Find your name here", updates[parent[1]])

    def test_index_goes_up_as_new_reply_if_fill_fails(self):
        class Fails(FakeClient):
            def chat_update(self, **kw):
                if "Tap your name" in kw["text"]:
                    raise RuntimeError("boom")
                return super().chat_update(**kw)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            book = _book(d / "Order Log.xlsx", 1, 1)
            c = Fails()
            with mock.patch.object(ols, "rep_files", return_value=[("Ana", book)]), \
                    mock.patch("time.sleep"):
                ols.post_threads(c, "C1", [("A-F", book)], d, "x")
        self.assertIn("Ana", [x for x in c.calls if x[0] == "post"][-1][2]["text"])


class TestRouting(unittest.TestCase):
    def _post(self, channel, too_big, letters_ok=True):
        from automations.shared import slack_metrics_post as smp
        with tempfile.TemporaryDirectory() as d:
            book = _book(Path(d) / "x.xlsx", 1, 1)
            with mock.patch.dict("os.environ", {"METRICS_CHANNEL_ID": channel}), \
                    mock.patch.object(order_log, "too_big_for_phone", return_value=too_big), \
                    mock.patch.object(order_log, "_post_letter_threads", return_value=letters_ok) as letters, \
                    mock.patch.object(smp, "post_reply_with_file", return_value={"file": "F"}) as single:
                order_log._post_order_log(book, None, is_empty=False, owner_name="Other",
                                          today=date(2026, 11, 1), post_to_slack=True)
        return letters, single

    def test_small_office_keeps_single_file(self):
        letters, single = self._post("COFFICE", False)
        letters.assert_not_called()
        single.assert_called_once()

    def test_big_office_gets_letters_in_its_own_channel(self):
        letters, single = self._post("COFFICE", True)
        self.assertEqual(letters.call_args[0][3], "COFFICE")
        single.assert_not_called()

    def test_failed_split_falls_back_to_single_file(self):
        _letters, single = self._post("COFFICE", True, letters_ok=False)
        single.assert_called_once()


if __name__ == "__main__":
    unittest.main()
