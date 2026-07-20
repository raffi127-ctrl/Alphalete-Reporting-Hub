"""Churn tab → PNG, posted alongside the Activations order-log message.

Carlos's ask (Loom 2026-07-19, 5:08): "if all of this right here could get
screenshotted and sent with where the activations order log thing is going
to get posted". That post is the Lucy thread in #alphalete-gp-sales
(automations.box_order_log.run.CHANNEL), so this renders the VISIBLE churn
block and uploads it there.

Rendering reuses the Org Sales Board technique: the Sheets PDF-export
endpoint on an explicit A1 range, rasterised and trimmed. That keeps the
exact-sheet look (conditional fills, borders, fonts) with no browser.

Posting is OFF unless --post is passed. Standing rule: nothing goes to
Slack without Megan saying so.
"""
from __future__ import annotations

import datetime as dt
import io
from pathlib import Path

import requests
from google.auth.transport.requests import Request as _GARequest
from google.oauth2.credentials import Credentials

from automations.recruiting_report.fill import SCOPES, OAUTH_TOKEN_PATH
from automations.vantura_churn.fill import SHEET_ID

# The block Carlos means by "all of this right here": the control box, the
# activation-rate cells, the tiers chart and the rolloff list — i.e. every
# VISIBLE column, down to the end of the rolloff table. Bounds are resolved
# from the tab at render time, never hardcoded row/col indices.
FIRST_COL = "A"


def _access_token() -> str:
    creds = Credentials.from_authorized_user_file(str(OAUTH_TOKEN_PATH), SCOPES)
    creds.refresh(_GARequest())
    return creds.token


def visible_range(ws, helper_first_col: str = "R") -> str:
    """A1 range covering the visible block: columns A..(col before the hidden
    helper block), rows 1..(last row of the rolloff list + a small margin).

    Derived, not hardcoded — the helper block's start and the list's extent
    both move as the layout changes.
    """
    last_col = chr(ord(helper_first_col) - 1)
    # Bound by the widest visible column, not column A: A holds a FILTER whose
    # spill is one row (or #N/A) when there are no disconnects, which would
    # crop the tiers chart and the whole rolloff table out of the shot.
    grid = ws.get(f"{FIRST_COL}1:{last_col}{ws.row_count}")
    last_row = 0
    for i, row in enumerate(grid, start=1):
        if any(str(c).strip() for c in row):
            last_row = i
    return f"{FIRST_COL}1:{last_col}{max(last_row, 20)}"


def render(ws, out_path: Path, rng: str | None = None) -> Path:
    """Render `rng` of `ws` to a trimmed PNG."""
    import fitz  # PyMuPDF
    from PIL import Image, ImageChops
    import time

    rng = rng or visible_range(ws)
    token = _access_token()
    base = (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?"
            f"format=pdf&gid={ws.id}&range={rng}&gridlines=false"
            f"&sheetnames=false&printtitle=false&pagenumbers=false&fzr=false"
            f"&top_margin=0.05&bottom_margin=0.05"
            f"&left_margin=0.05&right_margin=0.05")

    def _fetch(extra):
        for attempt in range(5):        # the export endpoint 429s when hammered
            r = requests.get(base + extra,
                             headers={"Authorization": f"Bearer {token}"},
                             timeout=90)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.content
        raise RuntimeError(f"export {rng}: throttled (429) after retries")

    dpi = 200
    doc = fitz.open(stream=_fetch("&portrait=false&fitw=true"), filetype="pdf")
    if doc.page_count > 1:              # tall list — refit so it stays one page
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
        pages.append(_trim(Image.open(io.BytesIO(pm.tobytes("png")))
                           .convert("RGB")))
    if len(pages) == 1:
        img = pages[0]
    else:
        w = max(p.width for p in pages)
        img = Image.new("RGB", (w, sum(p.height for p in pages)), (255, 255, 255))
        y = 0
        for p in pages:
            img.paste(p, (0, y))
            y += p.height
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def render_report(ws, out_path: Path, helper_first_col: str = "R",
                  rep_col: str = "AG", log=print) -> Path:
    """The whole report as ONE image: churn block + the per-rep list.

    They can't be captured as a single range — the PDF export RENDERS hidden
    columns, so A1:AI would splice the internal helper block (R:AE) into the
    middle of the picture. So each visible block is exported separately and
    composed side by side, mirroring how the tab reads.
    """
    from PIL import Image

    main = render(ws, out_path.with_name(out_path.stem + "_main.png"),
                  visible_range(ws, helper_first_col))
    reps_rng = _rep_range(ws, rep_col)
    if reps_rng is None:
        log("  ⚠ no per-rep list found — screenshot is the churn block only")
        main.replace(out_path)
        return out_path
    reps = render(ws, out_path.with_name(out_path.stem + "_reps.png"),
                  reps_rng)

    a, b = Image.open(main), Image.open(reps)
    # The two exports come back at unrelated scales — the churn block is wide
    # and short so it fits-to-width tiny, the rep list is narrow and tall so
    # it comes back huge. Pasting them as-is makes the churn block
    # unreadable. Normalise on ROW HEIGHT (image height ÷ row count) so text
    # is the same size in both halves.
    rows_a = _range_rows(visible_range(ws, helper_first_col))
    rows_b = _range_rows(reps_rng)
    if rows_a and rows_b:
        rh_a, rh_b = a.height / rows_a, b.height / rows_b
        if rh_b > 0 and abs(rh_a / rh_b - 1) > 0.02:
            scale = rh_a / rh_b
            b = b.resize((max(1, int(b.width * scale)),
                          max(1, int(b.height * scale))), Image.LANCZOS)

    gap = 28
    h = max(a.height, b.height)
    canvas = Image.new("RGB", (a.width + gap + b.width, h), (255, 255, 255))
    canvas.paste(a, (0, 0))
    canvas.paste(b, (a.width + gap, 0))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    for tmp in (main, reps):          # keep only the composed image
        try:
            tmp.unlink()
        except OSError:
            pass
    return out_path


def _range_rows(rng: str):
    """Row count spanned by an A1 range like 'A1:Q24' → 24."""
    import re
    m = re.match(r"^[A-Z]+(\d+):[A-Z]+(\d+)$", str(rng or ""))
    return (int(m.group(2)) - int(m.group(1)) + 1) if m else None


def _rep_range(ws, rep_col: str):
    """A1 range of the per-rep list, or None when it hasn't been written."""
    import gspread.utils as _u
    c0 = _u.a1_to_rowcol(f"{rep_col}1")[1]
    last_col = _u.rowcol_to_a1(1, c0 + 2).rstrip("1")
    vals = ws.get(f"{rep_col}1:{last_col}{ws.row_count}")
    last = 0
    for i, row in enumerate(vals, start=1):
        if any(str(c).strip() for c in row):
            last = i
    return f"{rep_col}1:{last_col}{last}" if last > 1 else None


def post(png: Path, day: dt.date | None = None, thread_ts: str | None = None,
         dry_run: bool = True, log=print) -> dict:
    """Upload the PNG to the Activations order-log channel as Lucy.

    dry_run=True (the default) resolves the channel and reports what WOULD be
    sent without sending it.
    """
    from automations.box_order_log.run import CHANNEL

    day = day or dt.date.today()
    # No %-d: it's glibc-only and this has to render on Windows too.
    title = f"Churn & Activations — {day.strftime('%b')} {day.day}, {day.year}"
    if dry_run:
        log(f"[dry-run] would upload {png.name} ({png.stat().st_size:,} bytes) "
            f"to {CHANNEL[0]} ({CHANNEL[1]})"
            + (f" in thread {thread_ts}" if thread_ts else " as a new message"))
        return {"dry_run": True, "channel": CHANNEL[1], "title": title}

    from automations.shared.slack_metrics_post import _client  # Lucy user token
    client = _client()
    resp = client.files_upload_v2(
        channel=CHANNEL[1], file=str(png), title=title,
        initial_comment=title, thread_ts=thread_ts)
    log(f"  ✓ posted churn screenshot to {CHANNEL[0]}")
    return resp
