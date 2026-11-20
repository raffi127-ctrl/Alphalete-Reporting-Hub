"""Every plist in deploy/ must be readable by Python, not just by launchd.

THE DEFECT THIS PINS. A double hyphen inside an XML comment ends the comment
early. `plutil -lint` says OK and launchd runs the job perfectly, but Python's
plistlib sits on expat, where that is a hard syntax error. So the job keeps
firing while our own tooling cannot see it at all -- and a reader that fails
this way fails QUIETLY: morning_diag reported "orch-plist-err", the drift check
reported "unknown(no-plist)", and schedule_guard skipped the file. All three
look exactly like "no such job".

On 2026-11-20 twelve of the 175 plists in deploy/ carried it, the live
com.alphalete.b2b-dispositions-hourly among them. Several plists already warn
about it in their own comments; a warning is not a check.

TWO LAYERS, because either alone is not enough:
  - the files stay valid XML (this module);
  - the readers survive one anyway (schedule_guard._load_plist strips comments
    and retries, and morning_diag now goes through it).

    PYTHONPATH=. .venv/bin/python -m unittest \
        automations.day_orchestrator.test_deploy_plists_parse
"""
from __future__ import annotations

import plistlib
import re
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
_COMMENT = re.compile(r"<!--(.*?)-->", re.S)

_FIX = ("write the flag out in words instead -- 'today' flag, not the "
        "hyphenated form -- and use an em dash for a parenthetical")


def _plists():
    return sorted(DEPLOY.glob("*.plist"))


class DeployPlistsAreValidXml(unittest.TestCase):

    def test_the_scan_sees_the_plists(self):
        """A glob that matched nothing would make every test below vacuous."""
        self.assertGreater(len(_plists()), 100,
                           "deploy/*.plist matched almost nothing -- wrong path?")

    def test_every_plist_loads_with_plain_plistlib(self):
        """No comment-stripping fallback. This is the strict gate."""
        broken = []
        for p in _plists():
            try:
                plistlib.loads(p.read_bytes())
            except Exception as exc:  # noqa: BLE001
                broken.append("%s: %s" % (p.name, exc))
        self.assertEqual(broken, [], "\n" + "\n".join(broken) + "\n\n" + _FIX)

    def test_no_double_hyphen_inside_any_xml_comment(self):
        """The cause, named directly, so the failure explains itself.

        test_every_plist_loads_with_plain_plistlib already fails on these, but
        its expat message ("not well-formed (invalid token)") says nothing about
        hyphens and sent two people hunting the wrong thing.
        """
        hits = []
        for p in _plists():
            for body in _COMMENT.findall(p.read_text(errors="replace")):
                for line in body.splitlines():
                    if "--" in line:
                        hits.append("%s: %s" % (p.name, line.strip()))
        self.assertEqual(hits, [],
                         "\ndouble hyphen inside an XML comment:\n"
                         + "\n".join(hits) + "\n\n" + _FIX)

    def test_a_planted_defect_would_actually_be_caught(self):
        """Guards the guard: a check that cannot fail is not a check."""
        good = b'<?xml version="1.0"?><plist version="1.0"><dict/></plist>'
        self.assertIsNotNone(plistlib.loads(good))
        planted = good.replace(b"<dict/>", b"<!-- a --b comment --><dict/>")
        with self.assertRaises(Exception):
            plistlib.loads(planted)
        self.assertTrue(_COMMENT.findall(planted.decode()))


class ReadersSurviveADefectiveComment(unittest.TestCase):
    """The second layer: valid files are the goal, a resilient reader is the net."""

    def test_schedule_guard_reads_a_plist_plistlib_refuses(self):
        from automations.day_orchestrator import schedule_guard as SG
        import tempfile
        bad = ('<?xml version="1.0"?><plist version="1.0"><dict>'
               '<!-- a --b comment -->'
               '<key>StartCalendarInterval</key><dict>'
               '<key>Hour</key><integer>4</integer></dict></dict></plist>')
        with tempfile.NamedTemporaryFile("w", suffix=".plist", delete=False) as fh:
            fh.write(bad)
            path = Path(fh.name)
        try:
            with self.assertRaises(Exception):
                plistlib.loads(bad.encode())
            got = SG._load_plist(path)
            self.assertIsNotNone(got, "_load_plist lost its comment-stripping retry")
            self.assertEqual(got["StartCalendarInterval"]["Hour"], 4)
        finally:
            path.unlink()

    def test_morning_diag_does_not_call_plistlib_directly(self):
        """It did, and went blind to a job that was firing the whole time."""
        import inspect

        from automations.day_orchestrator import morning_diag as MD
        src = inspect.getsource(MD)
        self.assertNotIn("plistlib.load(", src,
                         "morning_diag is reading plists raw again -- go "
                         "through schedule_guard._load_plist")
