"""The consented scopes and the used scopes must be the same list.

python -m pytest automations/recruiting_report/test_scopes.py
"""
from automations.recruiting_report import fill, sheets_auth


def test_the_two_lists_match():
    """Consented in sheets_auth, used in fill. A scope in one and not the
    other is a token that passes the auth check and then 403s in a run --
    which is how creating an onboarding workbook failed on 2026-11-21."""
    assert sorted(sheets_auth.SHEETS_SCOPES) == sorted(fill.SCOPES)


def test_drive_access_is_the_narrow_one():
    """`drive.file` reaches only files this app made or somebody opened with
    it. Full `drive` would reach everything in Megan's Drive, and nothing
    here needs that."""
    assert "https://www.googleapis.com/auth/drive.file" in fill.SCOPES
    assert "https://www.googleapis.com/auth/drive" not in fill.SCOPES


def test_an_old_token_is_loaded_with_its_own_scopes(tmp_path):
    """2026-11-21: asking Google to refresh a token for a scope it never
    consented to fails with invalid_scope, so passing fill.SCOPES (which now
    includes drive.file) took every Lucy with a pre-change token off Sheets.
    The token must be loaded with the scopes saved IN it."""
    import json
    old = tmp_path / "token.json"
    old.write_text(json.dumps({
        "token": "x", "refresh_token": "r", "client_id": "c",
        "client_secret": "s", "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/spreadsheets"]}))
    creds = fill.load_token_credentials(old)
    assert list(creds.scopes) == ["https://www.googleapis.com/auth/spreadsheets"]
    assert "https://www.googleapis.com/auth/drive.file" in fill.SCOPES
