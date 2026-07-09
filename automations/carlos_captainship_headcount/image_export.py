"""Render the "Captainship Head count" 4-week view to a trimmed PNG.

The Monday DM: a screenshot of the owner names + the 4 NEWEST week columns
(B..E) + the Total row — exact-sheet look (colors/fonts/borders), no browser.
Uses the Google Sheets PDF-export endpoint, then PyMuPDF -> PIL to raster +
white-trim. Same engine the Org Sales Board screenshots use.
"""
from __future__ import annotations

import datetime as dt
import io
import time
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


def export_png(spreadsheet_id: str, gid: int, rng: str, out_path: Path,
               token: str | None = None) -> Path:
    """PNG of one A1 range (e.g. 'A1:E13') of tab `gid`. Returns the path."""
    import fitz  # PyMuPDF
    from PIL import Image, ImageChops

    token = token or _access_token()
    base = (f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
            f"/export?format=pdf&gid={gid}&range={rng}"
            f"&gridlines=false&sheetnames=false&printtitle=false"
            f"&pagenumbers=false&fzr=false"
            f"&top_margin=0.05&bottom_margin=0.05&left_margin=0.05&right_margin=0.05")

    def _fetch(extra: str) -> bytes:
        for attempt in range(5):        # export endpoint 429s on rapid requests
            r = requests.get(base + extra,
                             headers={"Authorization": f"Bearer {token}"},
                             timeout=90)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            if "pdf" not in r.headers.get("Content-Type", "").lower():
                raise RuntimeError(f"export {rng} did not return a PDF; first "
                                   f"bytes: {r.content[:120]!r}")
            return r.content
        raise RuntimeError(f"export {rng}: throttled (429) after retries")

    # Fit-to-WIDTH landscape (crisp for the short, wide table). Fall back to
    # fit-to-PAGE if it ever paginates, so the whole thing lands on one page.
    dpi = 200
    doc = fitz.open(stream=_fetch("&portrait=false&fitw=true"), filetype="pdf")
    if doc.page_count > 1:
        doc = fitz.open(stream=_fetch("&portrait=true&scale=4"), filetype="pdf")
        dpi = 320

    def _trim(im):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bb = ImageChops.difference(im, bg).getbbox()
        if not bb:
            return im
        pad = 6
        return im.crop((max(0, bb[0] - pad), max(0, bb[1] - pad),
                        min(im.width, bb[2] + pad), min(im.height, bb[3] + pad)))

    pages = []
    for pg in doc:
        pm = pg.get_pixmap(dpi=dpi)
        pages.append(_trim(Image.open(io.BytesIO(pm.tobytes("png"))).convert("RGB")))
    if len(pages) == 1:
        img = pages[0]
    else:
        w = max(p.width for p in pages)
        img = Image.new("RGB", (w, sum(p.height for p in pages)), (255, 255, 255))
        y = 0
        for p in pages:
            img.paste(p, (0, y))
            y += p.height
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def default_name(we_sunday: dt.date) -> str:
    return f"Carlos Captainship Headcount WE {we_sunday.month}.{we_sunday.day}.png"
