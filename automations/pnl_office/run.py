"""PNL for the Office — weekly Slack post (Item 3 of the VA-Slack replacements).

Screenshots the 4-row office P&L summary (Total Loss - Reps / Total Loss - Other
/ Total Profit / Gross Profit) for a given week-ending from the `Raf PNL 2026`
tab, as an exact-sheet PNG, and posts it to Slack as Lucy.

Source: 'All in One Local Office - Raf' workbook -> tab 'Raf PNL 2026'.
  - Row 1 has WE headers every 3 cols: "WE 7/12" at the group's first column;
    the group is Brought In | Got Paid | Profit/Loss.
  - The office summary sits in the group's 2nd col (labels) + 3rd col (values):
    e.g. WE 7/12 header CJ1 -> labels CK317:CK320, values CL317:CL320.
  Columns/rows are found by DATE header + row LABEL, never hardcoded.

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

SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
TAB = "Raf PNL 2026"
GID = 1537448816
HEADER_ROW = 1
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


def _cell(vals, r, c) -> str:
    return vals[r - 1][c - 1] if r - 1 < len(vals) and c - 1 < len(vals[r - 1]) else ""


def we_columns(vals, year: int):
    """Return [(col_index, date, label)] for every WE header in row 1."""
    out = []
    row = vals[HEADER_ROW - 1] if len(vals) >= HEADER_ROW else []
    for c, cell in enumerate(row, start=1):
        m = _WE_RE.match(cell.strip())
        if m:
            mo, da = int(m.group(1)), int(m.group(2))
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
    """Find the summary block for a WE group by label. Returns (a1_range,
    label_col, value_col, top_row, bot_row)."""
    label_col, value_col = header_col + 1, header_col + 2
    top = bot = None
    for r in range(1, len(vals) + 1):
        v = _cell(vals, r, label_col).strip()
        if v == TOP_LABEL:
            top = r
        elif v == BOT_LABEL and top is not None:
            bot = r
            break
    if top is None or bot is None:
        raise SystemExit(f"summary labels not found under column {rowcol_to_a1(1, header_col)}")
    rng = f"{rowcol_to_a1(top, label_col)}:{rowcol_to_a1(bot, value_col)}"
    return rng, label_col, value_col, top, bot


def _money(s: str) -> float:
    s = s.replace("$", "").replace(",", "").replace("(", "-").replace(")", "").strip()
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def is_filled(vals, value_col: int, top: int, bot: int) -> bool:
    """Filled = at least one of the 4 summary values is non-zero (a fresh week
    reads blank / $0.00 until the VA enters it)."""
    return any(_money(_cell(vals, r, value_col)) != 0.0 for r in range(top, bot + 1))


def export_png(rng: str, out_path: Path, token: str) -> Path:
    import fitz  # PyMuPDF
    from PIL import Image, ImageChops
    base = (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=pdf"
            f"&gid={GID}&range={rng}&gridlines=false&sheetnames=false"
            f"&printtitle=false&pagenumbers=false&fzr=false"
            f"&top_margin=0.05&bottom_margin=0.05&left_margin=0.05&right_margin=0.05")

    def _fetch(extra):
        for attempt in range(5):
            r = requests.get(base + extra, headers={"Authorization": f"Bearer {token}"}, timeout=90)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.content
        raise RuntimeError(f"export {rng}: throttled (429) after retries")

    doc = fitz.open(stream=_fetch("&portrait=false&fitw=true"), filetype="pdf")

    def _trim(im):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bb = ImageChops.difference(im, bg).getbbox()
        if not bb:
            return im
        pad = 6
        return im.crop((max(0, bb[0] - pad), max(0, bb[1] - pad),
                        min(im.width, bb[2] + pad), min(im.height, bb[3] + pad)))

    pm = doc[0].get_pixmap(dpi=220)
    img = _trim(Image.open(io.BytesIO(pm.tobytes("png"))).convert("RGB"))
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


def build(today: dt.date, override: str | None):
    ws = open_by_key(SHEET_ID).worksheet(TAB)
    vals = ws.get_all_values()
    cols = we_columns(vals, today.year)
    if not cols:
        raise SystemExit("no WE headers found in row 1")
    header_col, we_date, we_label = pick_target(cols, today, override)
    rng, label_col, value_col, top, bot = summary_range(vals, header_col)
    filled = is_filled(vals, value_col, top, bot)
    preview = [(_cell(vals, r, label_col), _cell(vals, r, value_col)) for r in range(top, bot + 1)]
    return {
        "we_label": we_label, "we_date": we_date, "range": rng,
        "filled": filled, "preview": preview,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--we", help="force a week, e.g. '7/12'")
    ap.add_argument("--post", action="store_true",
                    help="ACTUALLY post to Slack (default is dry-run — no posting)")
    ap.add_argument("--out", type=Path, help="PNG output path")
    args = ap.parse_args(argv)

    today = dt.date.today()
    info = build(today, args.we)
    tag = info["we_label"].replace("WE ", "").replace("/", ".")
    caption = f"PNL for the Office WE {tag}"
    print(f"target: {info['we_label']}  (range {info['range']})  filled={info['filled']}")
    for lbl, val in info["preview"]:
        print(f"    {lbl:20} {val}")

    out = args.out or (OUT_DIR / f"{caption}.png")
    export_png(info["range"], out, _token())
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
