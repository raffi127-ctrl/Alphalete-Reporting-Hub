"""The hosted app has to materialise BOTH credential files, or no sheet opens.

ensure_sheets_credentials() existed and was called from nowhere, so every
page that reads a registry failed on Streamlit Cloud and the public page
showed "Couldn't read the registries just now" (Megan 2026-10-06). And the
token alone was not enough: fill._client() checks for the client JSON first
and raises before it ever looks at a token.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_sales_board import cloud


class MaterialisingCredentials(unittest.TestCase):

    def _paths(self, tmp):
        return (mock.patch("automations.recruiting_report.fill."
                           "OAUTH_TOKEN_PATH", tmp / "oauth-token.json"),
                mock.patch("automations.recruiting_report.fill."
                           "OAUTH_CLIENT_PATH", tmp / "oauth-client.json"))

    def test_both_files_are_written(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            tok, cli = self._paths(tmp)
            secrets = {"sheets_oauth_token": json.dumps({"t": 1}),
                       "sheets_oauth_client": json.dumps({"c": 2})}
            with tok, cli, mock.patch.object(
                    cloud, "_secret", lambda n, d=None: secrets.get(n, d)):
                self.assertTrue(cloud.ensure_sheets_credentials())
            self.assertTrue((tmp / "oauth-token.json").exists())
            self.assertTrue((tmp / "oauth-client.json").exists(),
                            "client json is what _client() checks FIRST")

    def test_a_local_token_is_never_overwritten(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            (tmp / "oauth-token.json").write_text('{"mine": true}')
            tok, cli = self._paths(tmp)
            with tok, cli, mock.patch.object(
                    cloud, "_secret",
                    lambda n, d=None: json.dumps({"theirs": True})):
                cloud.ensure_sheets_credentials()
            self.assertIn("mine", (tmp / "oauth-token.json").read_text())

    def test_no_secrets_is_false_not_a_crash(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            tok, cli = self._paths(tmp)
            with tok, cli, mock.patch.object(cloud, "_secret",
                                             lambda n, d=None: None), \
                 mock.patch.dict("os.environ", {}, clear=True):
                self.assertFalse(cloud.ensure_sheets_credentials())

    def test_malformed_json_is_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            tok, cli = self._paths(tmp)
            with tok, cli, mock.patch.object(
                    cloud, "_secret", lambda n, d=None: "not json {"):
                self.assertFalse(cloud.ensure_sheets_credentials())
            self.assertFalse((tmp / "oauth-token.json").exists())


class TheSecretsThatAreActuallyThere(unittest.TestCase):
    """This app's secrets already carry OAuth as a [gcp_oauth] table.

    Asking for a second copy under another name would be two things to
    rotate and two ways to be out of date. The table's keys ARE Google's
    authorized-user format, so it is read straight through.
    """

    TABLE = {"token": "ya29.x", "refresh_token": "1//x",
             "token_uri": "https://oauth2.googleapis.com/token",
             "client_id": "x.apps.googleusercontent.com",
             "client_secret": "GOCSPX-x",
             "scopes": ["https://www.googleapis.com/auth/spreadsheets"]}

    def _run(self, table):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            with mock.patch("automations.recruiting_report.fill."
                            "OAUTH_TOKEN_PATH", tmp / "t.json"), \
                 mock.patch("automations.recruiting_report.fill."
                            "OAUTH_CLIENT_PATH", tmp / "c.json"), \
                 mock.patch.object(
                     cloud, "_secret",
                     lambda n, dflt=None: table if n == "gcp_oauth" else None):
                ok = cloud.ensure_sheets_credentials()
            tok = (json.loads((tmp / "t.json").read_text())
                   if (tmp / "t.json").exists() else None)
            return ok, tok

    def test_the_table_alone_is_enough(self):
        ok, tok = self._run(self.TABLE)
        self.assertTrue(ok, "her existing secrets must need no additions")
        self.assertEqual(tok["refresh_token"], "1//x")

    def test_google_accepts_what_we_write(self):
        from google.oauth2.credentials import Credentials
        _ok, tok = self._run(self.TABLE)
        creds = Credentials.from_authorized_user_info(tok, tok.get("scopes"))
        self.assertTrue(creds.refresh_token)

    def test_the_scope_is_the_one_the_code_asks_for(self):
        from automations.recruiting_report import fill
        self.assertEqual(list(self.TABLE["scopes"]), list(fill.SCOPES))

    def test_a_table_missing_a_refresh_token_is_refused(self):
        bad = dict(self.TABLE)
        bad.pop("refresh_token")
        ok, tok = self._run(bad)
        self.assertFalse(ok)
        self.assertIsNone(tok, "half a credentials file is worse than none")


class TheEntrypointCallsIt(unittest.TestCase):

    def test_streamlit_app_wires_it_up(self):
        """It was defined and called from nowhere for weeks."""
        src = Path("streamlit_app.py").read_text()
        self.assertIn("ensure_sheets_credentials", src)
        # The CALL, not the docstring's mention of it a few lines in.
        self.assertLess(src.index("ensure_sheets_credentials"),
                        src.index("st.navigation(pages"),
                        "must run BEFORE any page opens a sheet")


if __name__ == "__main__":
    unittest.main()
