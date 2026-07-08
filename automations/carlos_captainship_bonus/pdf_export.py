"""Export the "Carlos B2B Captainship" 5-week + chart view to a PDF.

Loom's final step: select from A2 down through the chart (metrics + 5 newest
week columns + the performance graph) and Save as PDF, named
"Carlos Captainship Weekending <M.D>.pdf" (Sunday date). Portrait + fit-to-page
so the tall, narrow report fills one page.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import requests

from automations.recruiting_report import fill as rfill


def _access_token() -> str:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    creds = Credentials.from_authorized_user_file(
        str(rfill.OAUTH_TOKEN_PATH), rfill.SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            rfill.OAUTH_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError("Sheets OAuth token invalid and can't refresh.")
    return creds.token


def export_pdf(spreadsheet_id: str, gid: int, out_path: Path,
               r1: int = 1, c1: int = 0, r2: int = 82, c2: int = 6,
               landscape: bool = False) -> Path:
    """PDF of the 0-based half-open range [r1:r2, c1:c2]. Defaults: rows 2..82
    (through the chart, before the stray row-83 notes), cols A..F (label + 5
    newest weeks). PORTRAIT + fit-to-page. Returns the written path."""
    params = {
        "format": "pdf", "gid": str(gid),
        "r1": str(r1), "c1": str(c1), "r2": str(r2), "c2": str(c2),
        "portrait": "false" if landscape else "true",
        "scale": "4",                 # 4 = fit whole selection to one page
        "gridlines": "false", "printtitle": "false", "sheetnames": "false",
        "pagenumbers": "false", "fzr": "false",
        "top_margin": "0.15", "bottom_margin": "0.15",
        "left_margin": "0.15", "right_margin": "0.15",
    }
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export"
    r = requests.get(url, params=params,
                     headers={"Authorization": f"Bearer {_access_token()}"},
                     timeout=120)
    r.raise_for_status()
    if "pdf" not in r.headers.get("Content-Type", "").lower():
        raise RuntimeError(f"export did not return a PDF; first bytes: "
                           f"{r.content[:200]!r}")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(r.content)
    return out_path


def default_name(we_sunday: dt.date) -> str:
    return f"Carlos Captainship WE {we_sunday.month}.{we_sunday.day}.pdf"
