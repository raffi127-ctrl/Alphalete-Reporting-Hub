"""The churn post step outlasts a shared-login read-quota stall.

    python -m unittest automations.churn.test_render_quota

2026-11-20: Haytham's churn filled its Sheet on Lucy 4, then the read-back for
the pictures hit 'Read requests per minute per user' (Lucy 2/3/4 share one
login) and the metric posted nothing.
"""
import datetime as dt
import unittest
from pathlib import Path
from unittest import mock

import gspread

from automations.churn import run as R


def _quota():
    resp = mock.Mock(status_code=429)
    resp.json.return_value = {"error": {"code": 429, "message": "Quota exceeded",
                                        "status": "RESOURCE_EXHAUSTED"}}
    return gspread.exceptions.APIError(resp)


class _Fill:
    def __init__(self):
        self.opens = 0

    def open_ws(self):
        self.opens += 1
        return "ws"

    def find_sections(self, ws):
        return {"0-30": {}}


@mock.patch.object(R.time, "sleep", lambda s: None)
class RenderPatiently(unittest.TestCase):

    def _render(self, outcomes):
        outcomes = list(outcomes)

        def render_all(ws, sections, today, out_dir):
            o = outcomes.pop(0)
            if isinstance(o, Exception):
                raise o
            return o

        fill, render = _Fill(), mock.Mock(render_all_sections=render_all)
        return fill, R._render_patiently(fill, render, dt.date(2026, 11, 20),
                                         Path("/tmp"))

    def test_a_stall_that_clears_still_renders(self):
        fill, (sections, paths) = self._render([_quota(), {"0-30": "p.png"}])
        self.assertEqual(paths, {"0-30": "p.png"})
        self.assertEqual(fill.opens, 2)          # the tab is re-read after the wait

    def test_a_stall_that_never_clears_still_fails(self):
        with self.assertRaises(gspread.exceptions.APIError):
            self._render([_quota(), _quota(), _quota()])

    def test_other_errors_are_not_waited_out(self):
        with self.assertRaises(ValueError):
            self._render([ValueError("bad sheet")])


if __name__ == "__main__":
    unittest.main()
