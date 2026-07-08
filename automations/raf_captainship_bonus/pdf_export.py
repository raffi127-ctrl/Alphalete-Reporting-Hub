"""Export the "Captainship Bonuses" 4-week + chart view to a PDF.

Mirrors the Loom's final step: select the metrics + the 4 newest week columns
+ the performance chart and 'Save as PDF' into Downloads, named
"RafCaptainship <M.D>.pdf".

Uses the Sheets export endpoint (docs.google.com/.../export?format=pdf) with a
bounded cell range so only the recent columns print. The floating chart is an
overlay anchored inside the row range, so it renders in the PDF.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional

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
               r1: int = 3, c1: int = 0, r2: int = 111, c2: int = 5,
               landscape: bool = False) -> Path:
    """Download a PDF of the given 0-based half-open cell range [r1:r2, c1:c2].
    Defaults: rows 4..111 (skips the blank top rows, ends just past the chart),
    cols A..E (label + 4 newest weeks). PORTRAIT + fit-to-page so the tall,
    narrow report fills one page (landscape left big side margins). Returns the
    written path."""
    params = {
        "format": "pdf",
        "gid": str(gid),
        "r1": str(r1), "c1": str(c1), "r2": str(r2), "c2": str(c2),
        "portrait": "false" if landscape else "true",
        "scale": "4",          # 4 = fit whole selection to one page
        "gridlines": "false",
        "printtitle": "false",
        "sheetnames": "false",
        "pagenumbers": "false",
        "fzr": "false",
        "top_margin": "0.15", "bottom_margin": "0.15",
        "left_margin": "0.15", "right_margin": "0.15",
    }
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export"
    r = requests.get(url, params=params,
                     headers={"Authorization": f"Bearer {_access_token()}"},
                     timeout=120)
    r.raise_for_status()
    ctype = r.headers.get("Content-Type", "")
    if "pdf" not in ctype.lower():
        raise RuntimeError(f"export did not return a PDF (Content-Type={ctype}); "
                           f"first bytes: {r.content[:200]!r}")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(r.content)
    return out_path


def default_name(we_sunday: dt.date) -> str:
    return f"Raf Captainship WE {we_sunday.month}.{we_sunday.day}.pdf"
