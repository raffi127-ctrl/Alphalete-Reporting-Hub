"""The SCI pass must not share the Alphalete pass's incident thread: a clean
SCI run used to close the Alphalete pass's failure (10/9, Rafael Hidalgo)."""
import importlib
import os
import unittest
from unittest import mock

from automations.indeed_source_report import sheet


def _load(env):
    with mock.patch.dict(os.environ, env, clear=False):
        if "INDEED_SOURCE_SPREADSHEET_ID" not in env:
            os.environ.pop("INDEED_SOURCE_SPREADSHEET_ID", None)
        importlib.reload(sheet)
        from automations.indeed_source_report import run
        return importlib.reload(run)


class IncidentKeyTest(unittest.TestCase):
    def tearDown(self):
        _load({})

    def test_alphalete_pass_keeps_the_watcher_key(self):
        run = _load({})
        self.assertEqual(run.INCIDENT_KEY, "standalone-indeed-source-report")

    def test_sci_pass_gets_its_own_key(self):
        run = _load({"INDEED_SOURCE_SPREADSHEET_ID":
                     "1aWWdtMtv1ivZa8fv10cbEzJJUNrO7h9YA8fVvfiRqlg"})
        self.assertEqual(run.INCIDENT_KEY, "standalone-indeed-source-report-sci")
        self.assertIn("SCI", run.LABEL)


if __name__ == "__main__":
    unittest.main()
