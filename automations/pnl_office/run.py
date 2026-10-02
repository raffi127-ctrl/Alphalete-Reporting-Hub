"""PNL for the Office — weekly Slack post (Item 3 of the VA-Slack replacements).

Screenshots the office P&L summary (Total Loss - Reps / Total Profit / Gross
Profit) for a given week-ending from the `RAF PNL 2026 (NEW)` tab, as an
exact-sheet PNG, and posts it to Slack as Lucy.

Source: 'All in One Local Office - Raf' workbook -> tab 'RAF PNL 2026 (NEW)'
(Eve, 2026-09-29; the old 3-cols-per-week tab is now 'RAF PNL 2026 (OLD)').
  - Labels live in column A; row 1 has one "WE 9/27" header per week column.
    e.g. WE 9/20 = column DI -> labels A38:A40, values DI38:DI40.
  - Labels and values aren't side by side, so the PNG is two exports (label
    strip + week strip) at the same scale, stitched together.
  Columns/rows are found by DATE header + row LABEL, never hardcoded. The tab is
  found by gid (its title keeps getting renamed), title as a fallback.
  - Rows collapsed/hidden inside the block are skipped by the PDF export and by
    the filled-gate alike: the PNG shows what Raf sees on screen.

Schedule: LIVE — Fridays 10:00am CST on the mini, retrying q25m until
the target week's column is filled.
Channels: #top-leaders-alphalete-org + #alphalete-lvl1-chat. Slack only (no email).

Usage:
  python -m automations.pnl_office.run              # dry-run (default): PNG only
  python -m automations.pnl_office.run --post      # actually post to Slack
  python -m automations.pnl_office.run --we 7/12   # force a week
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import re
import sys
import time
from pathlib import Path

import requests
from google.auth.transport.requests import Request as _GARequest
from google.oauth2.credentials import Credentials
from gspread.utils import rowcol_to_a1

from automations.recruiting_report.fill import open_by_key, OAUTH_TOKEN_PATH, SCOPES
from automations.shared import sheets_export as _sx
from automations.shared.workbooks import ALL_IN_ONE_RAF

SHEET_ID = ALL_IN_ONE_RAF
# The screenshot moved to the NEW tab on 2026-09-29. Only this report did: the
# other P&L readers (workbooks.main_pnl_tab) still point at the OLD tab's gid.
TAB_GID = 821853035
TAB = "RAF PNL 2026 (NEW)"          # fallback for a sandbox copy (gids differ)
_TAB_CACHED = None


def _tab() -> str:
    """The screenshot tab's CURRENT title, resolved once per process by gid."""
    global _TAB_CACHED
    if _TAB_CACHED is None:
        sheets = open_by_key(SHEET_ID).worksheets()
        hit = [w.title for w in sheets if w.id == TAB_GID]
        if not hit:
            hit = [w.title for w in sheets if w.title.strip().lower() == TAB.lower()]
        if not hit:
            raise SystemExit(f"P&L tab not found: gid {TAB_GID} / {TAB!r}")
        _TAB_CACHED = hit[0]
    return _TAB_CACHED
HEADER_ROW = 1
LABEL_COL = 1                       # column A holds the row labels
TOP_LABEL = "Total Loss - Reps"     # first row of the office summary block
BOT_LABEL = "Gross Profit"          # last row of the office summary block
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "pnl_office"

# Slack targets (Lucy is a member of both). To test safely, set PNL_CHANNEL_ID to
# a scratch channel — it overrides BOTH real channels.
CHANNELS = [
    ("#top-leaders-alphalete-org", "C067TTGFEFR"),
    ("#alphalete-lvl1-chat",       "C09JG28CD27"),
]
# Idempotency: remember the last WE we posted so 25-min retries never double-post.
STATE_PATH = Path.home() / ".config" / "recruiting-report" / "pnl_last_posted.txt"

_WE_RE = re.compile(r"^WE\s+(\d{1,2})/(\d{1,2})")


def _token() -> str:
    creds = Credentials.from_authorized_user_file(str(OAUTH_TOKEN_PATH), SCOPES)
    creds.refresh(_GARequest())
    return creds.token


def _sheet_meta(token: str):
    """(gid, {hidden 1-based rows}) for TAB, straight from the Sheets API.

    The gid is NOT hardcoded: the tab was re-created at least once and the old
    gid made `export?format=pdf` answer 400. Hidden rows come from the same call
    so the console preview + the filled-gate see exactly what the PNG shows.
    """
    tab = _tab()
    url = (f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}"
           f"?includeGridData=true&ranges={requests.utils.quote(tab)}!A1:A600"
           f"&fields=sheets(properties(sheetId,title),data(rowMetadata(hiddenByUser,hiddenByFilter)))")
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    r.raise_for_status()
    for sh in r.json().get("sheets", []):
        if sh["properties"]["title"] != tab:
            continue
        meta = (sh.get("data") or [{}])[0].get("rowMetadata") or []
        hidden = {i for i, m in enumerate(meta, start=1)
                  if m.get("hiddenByUser") or m.get("hiddenByFilter")}
        return sh["properties"]["sheetId"], hidden
    raise SystemExit(f"tab {tab!r} not found in the workbook")


def _cell(vals, r, c) -> str:
    return vals[r - 1][c - 1] if r - 1 < len(vals) and c - 1 < len(vals[r - 1]) else ""


def we_columns(vals, year: int):
    """Return [(col_index, date, label)] for every WE header in row 1.

    Headers run left-to-right in date order and the last one ('WE 1/3') is
    next year's, so a month going backwards bumps the year."""
    out = []
    row = vals[HEADER_ROW - 1] if len(vals) >= HEADER_ROW else []
    prev_mo = 0
    for c, cell in enumerate(row, start=1):
        m = _WE_RE.match(cell.strip())
        if m:
            mo, da = int(m.group(1)), int(m.group(2))
            if mo < prev_mo:
                year += 1
            prev_mo = mo
            out.append((c, dt.date(year, mo, da), cell.strip()))
    return out


def pick_target(cols, today: dt.date, override: str | None):
    """Previous FULLY completed week = the latest WE whose end date is strictly
    before today (a week ending on the run day isn't complete yet). Or the WE
    matching --we override (e.g. '7/12')."""
    if override:
        want = override.strip().lstrip("WE ").strip()
        for c, d, label in cols:
            if label.replace("WE ", "").strip() == want:
                return c, d, label
        raise SystemExit(f"--we {override!r} not found in headers: {[l for *_ , l in cols]}")
    past = [t for t in cols if t[1] < today]
    if not past:
        return min(cols, key=lambda t: t[1])
    return max(past, key=lambda t: t[1])


def summary_range(vals, header_col: int):
    """Find the summary block by column-A label. Returns ([label_range,
    value_range], label_col, value_col, top_row, bot_row)."""
    label_col, value_col = LABEL_COL, header_col
    top = bot = None
    for r in range(1, len(vals) + 1):
        # Case-insensitive: the sheet relabelled "Gross Profit" -> "GROSS PROFIT"
        # on 2026-10-02 and the Friday post never went out.
        v = " ".join(_cell(vals, r, label_col).split()).casefold()
        if v == TOP_LABEL.casefold():
            top = r
        elif v == BOT_LABEL.casefold() and top is not None:
            bot = r
            break
    if top is None or bot is None:
        raise SystemExit(f"summary labels not found under column {rowcol_to_a1(1, header_col)}")
    rng = [f"{rowcol_to_a1(top, c)}:{rowcol_to_a1(bot, c)}" for c in (label_col, value_col)]
    return rng, label_col, value_col, top, bot


def _money(s: str) -> float:
    s = s.replace("$", "").replace(",", "").replace("(", "-").replace(")", "").strip()
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def is_filled(vals, value_col: int, rows) -> bool:
    """Filled = at least one of the summary values on screen is non-zero (a fresh
    week reads blank / $0.00 until the VA enters it). Only the VISIBLE rows count
    — the collapsed cost breakdown can carry leftovers from a formula."""
    return any(_money(_cell(vals, r, value_col)) != 0.0 for r in rows)


def export_png(ranges: list, out_path: Path, token: str, gid: int) -> Path:
    """Export each range at the SAME scale (100%, not fit-to-width, or the
    narrow value strip gets blown up) and stitch them left to right."""
    import fitz  # PyMuPDF
    from PIL import Image, ImageChops

    def _url(rng):
        return (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=pdf"
                f"&gid={gid}&range={rng}&gridlines=false&sheetnames=false"
                f"&printtitle=false&pagenumbers=false&fzr=false&portrait=false&scale=1"
                f"&top_margin=0.05&bottom_margin=0.05&left_margin=0.05&right_margin=0.05")

    def _fetch(rng):
        for attempt in range(5):
            r = requests.get(_url(rng), headers={"Authorization": f"Bearer {token}"}, timeout=90)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            # A hidden tab exports as an empty 993-byte PDF with HTTP 200.
            return _sx.check_pdf(r.content, where=f"export {rng}")
        raise RuntimeError(f"export {rng}: throttled (429) after retries")

    def _trim(im, pad):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bb = ImageChops.difference(im, bg).getbbox()
        if not bb:
            return im
        return im.crop((max(0, bb[0] - pad), max(0, bb[1] - pad),
                        min(im.width, bb[2] + pad), min(im.height, bb[3] + pad)))

    parts = []
    for rng in ranges:
        doc = fitz.open(stream=_fetch(rng), filetype="pdf")
        pm = doc[0].get_pixmap(dpi=220)
        parts.append(_trim(Image.open(io.BytesIO(pm.tobytes("png"))).convert("RGB"), 0))
    pad = 6
    img = Image.new("RGB", (sum(p.width for p in parts) + 2 * pad,
                            max(p.height for p in parts) + 2 * pad), "white")
    x = pad
    for p in parts:
        img.paste(p, (x, pad))
        x += p.width
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def _channels():
    """Real channels, or a single scratch channel if PNL_CHANNEL_ID is set."""
    import os
    scratch = os.environ.get("PNL_CHANNEL_ID")
    if scratch:
        return [(f"scratch ({scratch})", scratch)]
    return CHANNELS


def _publish_hub(status: str) -> None:
    """Flip the Hub card's pill. Best-effort — never fails the run."""
    try:
        from automations.day_orchestrator import hub_publish
        hub_publish.publish_done("pnl_office", "PNL for the Office → #top-leaders + #alphalete-lvl1-chat", status)
    except Exception:  # noqa: BLE001 — Hub publish must never break the post
        pass


def _already_posted(we_label: str) -> bool:
    return STATE_PATH.exists() and STATE_PATH.read_text().strip() == we_label


def _mark_posted(we_label: str) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(we_label)


def post_to_slack(png: Path, caption: str, filename: str, dry_run: bool) -> list:
    """Upload the PNG to each target channel as Lucy. dry_run reports only."""
    from automations.shared import slack_metrics_post as smp
    results = []
    if dry_run:
        return [{"dry_run": True, "channel": name, "id": cid, "caption": caption}
                for name, cid in _channels()]
    client = smp._client()
    for name, cid in _channels():
        resp = client.files_upload_v2(channel=cid, file=str(png),
                                      filename=filename, initial_comment=caption)
        results.append({"channel": name, "id": cid, "ok": resp.get("ok"),
                        "file": (resp.get("file") or {}).get("id")})
    return results


def build(today: dt.date, override: str | None, token: str):
    ws = open_by_key(SHEET_ID).worksheet(_tab())
    vals = ws.get_all_values()
    cols = we_columns(vals, today.year)
    if not cols:
        raise SystemExit("no WE headers found in row 1")
    header_col, we_date, we_label = pick_target(cols, today, override)
    rng, label_col, value_col, top, bot = summary_range(vals, header_col)
    gid, hidden = _sheet_meta(token)
    # What the PNG will actually show: the block minus the collapsed rows.
    shown = [r for r in range(top, bot + 1) if r not in hidden]
    filled = is_filled(vals, value_col, shown)
    preview = [(_cell(vals, r, label_col), _cell(vals, r, value_col)) for r in shown]
    return {
        "we_label": we_label, "we_date": we_date, "range": rng, "gid": gid,
        "filled": filled, "preview": preview, "hidden_in_block": sorted(hidden & set(range(top, bot + 1))),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--we", help="force a week, e.g. '7/12'")
    ap.add_argument("--post", action="store_true",
                    help="ACTUALLY post to Slack (default is dry-run — no posting)")
    ap.add_argument("--out", type=Path, help="PNG output path")
    args = ap.parse_args(argv)

    today = dt.date.today()
    token = _token()
    info = build(today, args.we, token)
    tag = info["we_label"].replace("WE ", "").replace("/", ".")
    caption = f"PNL for the Office WE {tag}"
    print(f"target: {info['we_label']}  (range {info['range']}, gid {info['gid']})  filled={info['filled']}")
    for lbl, val in info["preview"]:
        print(f"    {lbl:20} {val}")
    if info["hidden_in_block"]:
        print(f"    (collapsed in the Sheet, not in the PNG: rows {info['hidden_in_block']})")

    out = args.out or (OUT_DIR / f"{caption}.png")
    export_png(info["range"], out, token, info["gid"])
    print(f"wrote {out}")

    # Gate: never post an unfilled week — the scheduler re-fires every 25 min.
    if not info["filled"]:
        print("NOT FILLED — holding. (Scheduler retries in 25 min.)")
        return 75  # EX_TEMPFAIL: signals the wrapper to retry
    if _already_posted(info["we_label"]):
        print(f"already posted {info['we_label']} — nothing to do.")
        return 0

    if not args.post:
        print("dry-run (default): not posting. Channels that WOULD receive it:")
        for r in post_to_slack(out, caption, f"{caption}.png", dry_run=True):
            print(f"    -> {r['channel']} ({r['id']})")
        return 0

    print("POSTING to Slack as Lucy:")
    try:
        results = post_to_slack(out, caption, f"{caption}.png", dry_run=False)
    except Exception:
        _publish_hub("failed")
        raise
    for r in results:
        print(f"    -> {r['channel']}: ok={r.get('ok')} file={r.get('file')}")
    _mark_posted(info["we_label"])
    # Publish ONLY on a real post (this runs 8x on Fridays).
    _publish_hub("success")
    return 0


if __name__ == "__main__":
    sys.exit(main())
