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


def visible_range(ws, helper_first_col: str = None) -> str:
    """A1 range covering the report block: columns A..(col before the helper
    block), rows 1..last populated.

    The helper column is DERIVED from the tab's own formulas by default — it
    moves when a column is inserted or removed, and a stale constant here
    silently reframes the shot. Bounded by the widest visible column, not
    column A: A holds a FILTER whose spill is one row (or #N/A) when there
    are no disconnects, which would crop the whole table out.
    """
    from automations.vantura_churn import fill
    if helper_first_col is None:
        helper_first_col = fill._colletter(fill.helper_bounds(ws)["f0"])
    scan_last = fill._col_idx(helper_first_col) - 1
    grid = ws.get(f"{FIRST_COL}1:{fill._colletter(scan_last)}{ws.row_count}")
    # Bound to the last row AND last column that actually hold content — the
    # block ends a column or two before the helper block, so stopping at
    # helper-1 leaves a blank strip of white on the right of the shot.
    last_row = last_col_i = 0
    for i, row in enumerate(grid, start=1):
        for j, c in enumerate(row):
            if str(c).strip():
                last_row = i
                last_col_i = max(last_col_i, j)
    return (f"{FIRST_COL}1:{fill._colletter(last_col_i)}"
            f"{max(last_row, 20)}")


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


def render_report(ws, out_path: Path, helper_first_col: str = None,
                  rep_col: str = None, log=print) -> Path:
    """The whole report as ONE image: churn block + the per-rep list.

    ONE range covers both: the PDF export omits columns hidden on the tab, so
    the helper block drops out of the middle by itself and the rep list lands
    right next to the churn block. That only holds while those columns are
    actually hidden — a freshly duplicated tab does NOT inherit the hidden
    state, so fill.hide_helper_columns() runs before this. Both the helper
    and rep-list columns are derived, never assumed.
    """
    reps_rng = _rep_range(ws, rep_col)
    main_rng = visible_range(ws, helper_first_col)
    if reps_rng is None:
        log("  ⚠ no per-rep list found — screenshot is the churn block only")
        return render(ws, out_path, main_rng)

    last_row = max(_range_rows(main_rng) or 0, _range_rows(reps_rng) or 0)
    last_col = reps_rng.split(":")[1].rstrip("0123456789")
    return render(ws, out_path, f"A1:{last_col}{last_row}")


def _range_rows(rng: str):
    """Row count spanned by an A1 range like 'A1:Q24' → 24."""
    import re
    m = re.match(r"^[A-Z]+(\d+):[A-Z]+(\d+)$", str(rng or ""))
    return (int(m.group(2)) - int(m.group(1)) + 1) if m else None


def _rep_range(ws, rep_col: str = None):
    """A1 range of the per-rep list, or None when it hasn't been written.

    Column derived from the helper block by default — a constant goes stale
    the moment a column is inserted or removed.
    """
    from automations.vantura_churn import fill
    if rep_col is None:
        rep_col = fill._colletter(fill.rep_list_col(ws))
    c0 = fill._col_idx(rep_col)
    # Bound to the actual content, not a fixed width — the list dropped from
    # 3 columns to 2 (0-30 only) on 2026-07-20, so scan a small window and
    # stop at the last column/row that holds anything.
    vals = ws.get(f"{rep_col}1:{fill._colletter(c0 + 3)}{ws.row_count}")
    last_row = last_col_i = 0
    for i, row in enumerate(vals, start=1):
        for j, c in enumerate(row):
            if str(c).strip():
                last_row = i
                last_col_i = max(last_col_i, c0 + j)
    if last_row <= 1:
        return None
    return f"{rep_col}1:{fill._colletter(last_col_i)}{last_row}"


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
