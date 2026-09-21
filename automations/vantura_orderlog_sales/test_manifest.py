"""A live exit-0 pass writes the run manifest; a dry run or a hold does not.

2026-09-21: the ticket stayed open after a clean pass — "ran clean, but
nothing can confirm it DELIVERED" — because nothing wrote a manifest.

    python -m unittest automations.vantura_orderlog_sales.test_manifest -v
"""
from __future__ import annotations

import datetime as dt
import sys
import types
import unittest
from unittest import mock

from automations.vantura_orderlog_sales import run

DAY = dt.date(2026, 9, 20)


def _result(campaign="B2B"):
    return {"day": DAY, "campaign": campaign, "col": 6, "rows": {},
            "matched": {}, "covered": True, "unmatched": []}


class ManifestTest(unittest.TestCase):
    def _main(self, argv, *, covered=True, week_ok=(True, "9.20", "9.20")):
        fill = types.SimpleNamespace(open_by_key=lambda _id: object(),
                                     _retry=lambda fn, *a, **k: None)
        alert = types.SimpleNamespace(alert_unmatched=lambda items: None,
                                      resolve_unmatched=lambda: None)
        with mock.patch.dict(sys.modules, {
                    "automations.recruiting_report.fill": fill,
                    "automations.vantura_orderlog_sales.alert": alert}), \
                mock.patch.object(run, "board_grid",
                                  return_value=(mock.Mock(), [])), \
                mock.patch.object(run, "covers", return_value=covered), \
                mock.patch.object(run, "week_ok", return_value=week_ok), \
                mock.patch.object(run, "run_campaign",
                                  side_effect=lambda sh, g, d, c, fn=None:
                                  _result(c)), \
                mock.patch.object(run, "fill_plan", return_value=[]), \
                mock.patch.object(run, "ensure_board_shape"), \
                mock.patch.object(run, "_log"), \
                mock.patch("automations.shared.run_manifest.write_manifest"
                           ) as wm:
            rc = run.main(["--date", DAY.isoformat(), "--campaign", "B2B"]
                          + argv)
        return rc, wm

    def test_live_clean_pass_writes_proof(self):
        rc, wm = self._main(["--fill", "--yes"])
        self.assertEqual(rc, 0)
        wm.assert_called_once()
        self.assertEqual(wm.call_args.args[0], "vantura_orderlog_sales")
        self.assertEqual(wm.call_args.kwargs["succeeded"], ["B2B Sunday 9/20"])

    def test_dry_run_writes_nothing(self):
        for argv in (["--fill"], []):
            rc, wm = self._main(argv)
            self.assertEqual(rc, 0)
            wm.assert_not_called()

    def test_wrong_week_hold_writes_nothing(self):
        rc, wm = self._main(["--fill", "--yes"],
                            week_ok=(False, "9.13", "9.20"))
        self.assertEqual(rc, 75)
        wm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
