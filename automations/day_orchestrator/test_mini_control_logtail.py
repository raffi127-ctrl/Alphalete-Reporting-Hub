"""`logtail` must never truncate silently, and page 1 must be the NEWEST page.

WHY THIS EXISTS (Megan 2026-09-15). The action ended `(head + body)[:470]`: a
cut mid-word, with nothing in the output saying anything had been withheld. A
13-line log came back looking like a 4-line log that simply stopped, and that
was read — by Claude, out loud, twice — as evidence the run had done nothing.
The line that settled it ("TEXTED trackers_pdf -> Alphalete Owners, 27
participants") had been sitting in the log the whole time, just past the cut.

A silent truncation is worse than a short answer because it is indistinguishable
from evidence. Two rules fall out, and both are pinned here:
  1. if anything was withheld, SAY SO — per line and per page;
  2. page 1 holds the END of the log, because `logtail` is a tail. Paging
     forward from the oldest line put the one line that mattered on page 4.

    python -m unittest automations.day_orchestrator.test_mini_control_logtail
"""
import os
import unittest
from pathlib import Path

from automations.day_orchestrator import mini_control as mc

LOGS = Path(mc.REPO_ROOT) / "output" / "logs"

# The real 2026-09-15 shape: a noisy header, filler, answer on the last line.
_NOISE = ("/Users/alphalete/recruiting-report/.venv/lib/python3.9/site-packages/"
          "urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports "
          "OpenSSL 1.1.1+, currently the 'ssl' module is compiled with "
          "LibreSSL 2.8.3. See: https://github.com/urllib3/urllib3/issues/3020")
_ANSWER = ("TEXTED trackers_pdf -> Alphalete Owners "
           "(chat any;+;b1fa5909bac24814870ad43635104be5, 27 participants)")


class LogtailTruncation(unittest.TestCase):

    NAME = "zzz_logtail_unittest_fixture"

    def _write(self, lines):
        LOGS.mkdir(parents=True, exist_ok=True)
        p = LOGS / (self.NAME + ".log")
        p.write_text("\n".join(lines))
        self.addCleanup(lambda: os.path.exists(p) and os.unlink(p))
        return p

    def _big(self):
        return self._write(
            ["$ python -m automations.owner_chat_texts.run --send --resend",
             "[2026-09-15T11:04:52]", "", _NOISE]
            + ["downloading tracker %d of 9" % i for i in range(1, 8)]
            + [_ANSWER])

    def test_the_answer_is_on_page_one(self):
        """The whole point: a tail's newest line must not need a second call."""
        self._big()
        ok, out = mc._action_logtail(self.NAME)
        self.assertTrue(ok)
        self.assertIn("TEXTED trackers_pdf", out)

    def test_it_never_exceeds_the_cell(self):
        self._big()
        ok, out = mc._action_logtail(self.NAME)
        self.assertLessEqual(len(out), mc._LOGTAIL_CELL)

    def test_it_says_when_it_withheld_lines(self):
        """The bug was silence, not brevity."""
        self._big()
        _, out = mc._action_logtail(self.NAME)
        self.assertIn("older line(s) not shown", out)
        self.assertIn("page 1/", out)

    def test_later_pages_walk_backwards_into_older_lines(self):
        self._big()
        _, page2 = mc._action_logtail('%s "" 15 2' % self.NAME)
        self.assertIn("downloading tracker", page2)
        self.assertIn("page 2/", page2)

    def test_every_picked_line_is_reachable_by_paging(self):
        self._big()
        seen, page = "", 1
        while page <= 12:
            ok, out = mc._action_logtail('%s "" 15 %d' % (self.NAME, page))
            self.assertTrue(ok)
            seen += out
            if "(newest first)" not in out or "page {}/{}".format(page, page) in out:
                break
            page += 1
        self.assertIn("TEXTED trackers_pdf", seen)
        self.assertIn("downloading tracker 1 of 9", seen)

    def test_an_overlong_line_says_how_much_it_cut(self):
        self._write(["x" * 400])
        _, out = mc._action_logtail(self.NAME)
        self.assertIn("…[+", out)
        self.assertIn("chars]", out)

    def test_a_short_log_gets_no_paging_footer(self):
        """A fix that shouts on every call teaches people to ignore the shout."""
        self._write(["all good", _ANSWER])
        _, out = mc._action_logtail(self.NAME)
        self.assertNotIn("not shown", out)
        self.assertIn("TEXTED trackers_pdf", out)

    def test_a_single_line_longer_than_a_page_still_shows(self):
        """Never paginate into empty pages — one line always fits its own page."""
        self._write(["y" * 199, "z" * 199, "w" * 199])
        ok, out = mc._action_logtail(self.NAME)
        self.assertTrue(ok)
        self.assertTrue(out.strip())

    def test_page_beyond_the_end_clamps_instead_of_erroring(self):
        self._big()
        ok, out = mc._action_logtail('%s "" 15 99' % self.NAME)
        self.assertTrue(ok)
        self.assertTrue(out.strip())

    def test_grep_still_narrows(self):
        self._big()
        _, out = mc._action_logtail("%s TEXTED" % self.NAME)
        self.assertIn("TEXTED trackers_pdf", out)
        self.assertNotIn("downloading tracker", out)


class Paginate(unittest.TestCase):

    def test_it_never_returns_an_empty_page(self):
        pages = mc._paginate(["a" * 500, "b" * 500], 100)
        self.assertTrue(all(pg for pg in pages))

    def test_it_never_splits_a_line(self):
        lines = ["line-%d" % i for i in range(50)]
        flat = [l for pg in mc._paginate(lines, 100) for l in pg]
        self.assertEqual(flat, lines)

    def test_empty_in_empty_out(self):
        self.assertEqual(mc._paginate([], 100), [])


if __name__ == "__main__":
    unittest.main()
