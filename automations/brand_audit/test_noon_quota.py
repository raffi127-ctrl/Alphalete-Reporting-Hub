"""A 429 on the noon read waits and retries instead of killing the whole
Brand Health Audit (11/17 12:00:05, intake.read_companies)."""
import unittest
from unittest import mock

import gspread

from automations.brand_audit import intake, sheets


def _quota_error():
    resp = mock.Mock(status_code=429)
    resp.json.return_value = {"error": {"code": 429, "message": "Quota exceeded",
                                        "status": "RESOURCE_EXHAUSTED"}}
    return gspread.exceptions.APIError(resp)


class NoonQuota(unittest.TestCase):
    def test_read_companies_survives_one_429(self):
        ws = mock.Mock()
        ws.get_all_values.side_effect = [_quota_error(), [["Company Name"], ["Acme"]]]
        sh = mock.Mock(sheet1=ws)
        with mock.patch.object(sheets, "open_by_key", return_value=sh), \
                mock.patch.object(sheets.time, "sleep") as slept, \
                mock.patch.object(intake, "parse_rows", side_effect=lambda h, r: r):
            got = intake.read_companies("sheet-id")
        self.assertEqual(got, [["Acme"]])
        self.assertEqual(ws.get_all_values.call_count, 2)
        slept.assert_called_once()

    def test_real_error_is_not_retried(self):
        resp = mock.Mock(status_code=403)
        resp.json.return_value = {"error": {"code": 403, "message": "no",
                                            "status": "PERMISSION_DENIED"}}
        ws = mock.Mock()
        ws.get_all_values.side_effect = gspread.exceptions.APIError(resp)
        with mock.patch.object(sheets, "open_by_key", return_value=mock.Mock(sheet1=ws)), \
                mock.patch.object(sheets.time, "sleep") as slept:
            with self.assertRaises(gspread.exceptions.APIError):
                intake.read_companies("sheet-id")
        slept.assert_not_called()


if __name__ == "__main__":
    unittest.main()
