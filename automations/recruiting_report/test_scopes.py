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
