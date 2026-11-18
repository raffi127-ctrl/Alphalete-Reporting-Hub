"""A slow relay must not read as a crash, or as the office's internet.

WHAT WENT WRONG (2026-11-16/17). Every upsert in the relay script read its
WHOLE tab under the one lock every office shares -- 'ICD Knocks' had grown to
13.9 MB and 'ICD Faults' to 12.4 MB -- so calls queued past the laptop's
30-second wait. The timeout escaped relay._post bare, run.main filed it as a
"crash" (one more call to the same slow relay), and the channel read "the
laptop timed out (slow internet)" for 42 offices in the same minutes: 931
times on 11/17, up from 4 a day in late October.
"""
from __future__ import annotations

import pathlib
import re
import socket
import unittest
import urllib.error
from unittest import mock

from automations.icd_alerts import post as P
from automations.icd_alerts import relay as R

GS = (pathlib.Path(__file__).resolve().parents[2]
      / "resources" / "icd-alerts-relay.gs")


def _code_only(src: str) -> str:
    """The script with its comments removed, so a sentence ABOUT
    getDataRange cannot pass or fail the test."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def _body(name: str) -> str:
    """The source of one top-level function, comments stripped."""
    src = _code_only(GS.read_text())
    at = src.index("function %s(" % name)
    nxt = src.find("\nfunction ", at + 1)
    return src[at: nxt if nxt != -1 else len(src)]


class UpsertsReadOnlyTheirKeysTest(unittest.TestCase):
    """The three writes every office makes all day find their row from the
    key columns alone -- never the JSON or traceback columns beside them."""

    def test_no_whole_tab_read_in_the_hot_upserts(self):
        for fn in ("_upsert", "_upsertKnocks", "_upsertFault"):
            with self.subTest(fn=fn):
                body = _body(fn)
                self.assertNotIn("getDataRange", body,
                                 "%s reads its whole tab under the shared "
                                 "lock again" % fn)
                self.assertIn("_keyRows(sh,", body)

    def test_fault_match_stops_before_the_detail_column(self):
        # Office, Day, Stage, Summary = 4. Column 5 is a full traceback.
        self.assertIn("_keyRows(sh, 4)", _body("_upsertFault"))

    def test_fault_count_is_read_from_its_own_cell(self):
        body = _body("_upsertFault")
        self.assertNotIn("rows[i][5]", body,
                         "the count is past the columns _keyRows reads")
        self.assertIn("getRange(i + 1, 6).getValue()", body)


class _Opener:
    def __init__(self, exc):
        self.exc = exc

    def open(self, req, timeout=None):
        raise self.exc


class SlowRelayIsARelayErrorTest(unittest.TestCase):
    def _post_raising(self, exc):
        with mock.patch.object(R.urllib.request, "build_opener",
                               return_value=_Opener(exc)):
            return R._post("https://script.google.com/x/exec", b"{}")

    def test_read_timeout_becomes_relay_error(self):
        for exc in (socket.timeout("The read operation timed out"),
                    TimeoutError("The read operation timed out")):
            with self.subTest(exc=type(exc).__name__):
                with self.assertRaises(R.RelayError) as cm:
                    self._post_raising(exc)
                self.assertIn("Nothing is lost", str(cm.exception))

    def test_connect_timeout_wrapped_by_urllib_becomes_relay_error(self):
        with self.assertRaises(R.RelayError):
            self._post_raising(urllib.error.URLError(socket.timeout("timed out")))

    def test_other_network_errors_are_left_alone(self):
        # send() already words these ("no internet connection"); _post must
        # not swallow them into the slow-server message.
        with self.assertRaises(urllib.error.URLError) as cm:
            self._post_raising(urllib.error.URLError("nodename nor servname"))
        self.assertNotIsInstance(cm.exception, R.RelayError)

    def test_report_files_nothing_for_a_relay_error(self):
        from automations.icd_alerts import run
        with mock.patch.object(run.R, "report_fault") as rf:
            run._report("crash", R.RelayError("slow"))
        rf.assert_not_called()


class CalmLineNamesTheRightSideTest(unittest.TestCase):
    def test_crash_read_timeout_is_our_server(self):
        for summary in ("timeout: The read operation timed out",
                        "TimeoutError: The read operation timed out"):
            with self.subTest(summary=summary):
                said = P.short_reason("crash", summary)
                self.assertIn("our reporting server", said)
                self.assertNotIn("slow internet", said)

    def test_ownerville_timeout_still_reads_as_before(self):
        said = P.short_reason("knocks",
                              "TimeoutError: Page.goto: Timeout 25000ms")
        self.assertEqual(said, "OwnerVille timed out (slow internet or a "
                               "slow site)")


if __name__ == "__main__":
    unittest.main()
