"""An empty 6+ board is posted ONLY when the zero is real.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.scheduled_6_days_out.test_empty_is_real

WHAT THIS GUARDS (2026-09-28). Every office's Metrics thread posted an EMPTY
'Scheduled 6 days out' table on any day an owner had no 6+ installs — 13 of 14
offices on the morning of 9/28 — which breaks Megan's standing rule (no blank
boards in Slack). Her follow-up sets the bar: "if it's empty/skipped then there
truly has to be 0 data — not just missing data". The pull is pinned to ONE day,
so an extract that hasn't loaded that day ALSO filters to 0 rows. So:
  - export has orders for the day, none 6+ out  → the one-line 'none' post
  - export has no orders at all                 → post NOTHING, exit 1
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.scheduled_6_days_out import pull, run

HEADER = ["Owner Name", "Rep", "Customer Name", "sp.Customer Phone",
          "Days to Appointment", "Tech Install", "Product Type (Broken Out)"]


def _export(rows) -> Path:
    d = Path(tempfile.mkdtemp())
    p = d / "orderlog.csv"
    lines = ["\t".join(HEADER)] + ["\t".join(r) for r in rows]
    p.write_text("\n".join(lines) + "\n", encoding="utf-16-le")
    return p


class EmptyIsReal(unittest.TestCase):
    def _run(self, path):
        with mock.patch.object(run.slack_metrics_post, "post_reply_text_only",
                               return_value={"dry_run": True}) as txt, \
             mock.patch.object(run.slack_metrics_post, "post_reply_with_image") as img:
            rc = run._post_none_or_refuse(path, "Jacob Dover", do_post=False)
        return rc, txt, img

    def test_loaded_day_with_no_6plus_posts_the_none_line(self):
        p = _export([["Someone Else", "Rep A", "Cust", "555", "2", "Tech Install",
                      "NEW INTERNET"]])
        self.assertEqual(pull.parse_and_filter(p, owner="Jacob Dover"), [])
        rc, txt, img = self._run(p)
        self.assertEqual(rc, 0)
        txt.assert_called_once()
        self.assertEqual(txt.call_args[0][0], run.NONE_TEXT)
        img.assert_not_called()           # never the empty table

    def test_unloaded_day_posts_nothing_and_fails(self):
        p = _export([])
        rc, txt, img = self._run(p)
        self.assertEqual(rc, 1)
        txt.assert_not_called()
        img.assert_not_called()


if __name__ == "__main__":
    unittest.main()
