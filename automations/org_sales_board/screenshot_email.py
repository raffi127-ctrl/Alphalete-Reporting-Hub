"""Daily 'Alphalete Org Sales Board' SCREENSHOT email.

Sends real, exact-sheet screenshots (via the captainship_drafts sheet_shot
engine, repointed at THIS board's COPY TAB) of the three sections the existing
HTML email carries:

  1. Product Summary - This Week   (+ Frontier + Grand Total)
  2. RAF ORG - Current vs Prior Weeks
  3. ALPHALETE ORG leaderboard      (recent 4 weeks — matches the email)

Sections are located by their col-A/col-B LABEL, never by hardcoded rows, so a
template shift survives. Screenshots come from the copy tab (fully cross-checked
against the VA every run). Runs on the mini after the morning fill.

Rollout gate (Megan 2026-07-03): preview goes to Megan ONLY until she signs off;
then Maud + Rafael + Megan; then the full distro.

    python -m automations.org_sales_board.screenshot_email --dry-run   # capture only, no send
    python -m automations.org_sales_board.screenshot_email --preview   # send to Megan only
    python -m automations.org_sales_board.screenshot_email             # send to the proving list
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import List, Tuple

import requests
from google.auth.transport.requests import Request as _GARequest
from google.oauth2.credentials import Credentials
from gspread.utils import rowcol_to_a1

from automations.org_sales_board.run import SHEET_ID, SANDBOX_TAB
from automations.recruiting_report.fill import (
    open_by_key, _retry, SCOPES, OAUTH_TOKEN_PATH,
)
from automations.scheduled_6_days_out.email_send import (
    FROM_ADDR, SMTP_HOST, SMTP_PORT, app_password,
)

# Rollout recipient tiers (Megan 2026-07-03).
PREVIEW_TO = ["Meganhidalgo1191@gmail.com"]
PROVING_TO = ["maudmiller4@gmail.com", "raffi127@gmail.com",
              "Meganhidalgo1191@gmail.com"]
# DISTRO_TO — the full ~79-person list — wired only after Megan proves it out.

_LB_WEEKS = 4          # leaderboard columns to show: this week + 3 prior (== the email)


def _cell(g, r, c):
    return (g[r - 1][c - 1] if r - 1 < len(g) and c - 1 < len(g[r - 1]) else "").strip()


def _label_row(g, needle, *, col, start=1):
    """1-based row whose col-A (col=0) or col-B (col=1) starts with `needle`."""
    for r in range(start, len(g) + 1):
        if _cell(g, r, col + 1).lower().startswith(needle.lower()):
            return r
    return None


def _block_end(g, start):
    """Last row of a block that begins at `start` — the row before the first
    fully-blank (col A & B) row after it."""
    for r in range(start + 1, len(g) + 1):
        if not _cell(g, r, 1) and not _cell(g, r, 2):
            return r - 1
    return len(g)


def _last_col(g, r0, r1, cap=None):
    """Right-most 1-based column with any content across rows r0..r1."""
    last = 1
    for r in range(r0, r1 + 1):
        row = g[r - 1] if r - 1 < len(g) else []
        for c in range(len(row), 0, -1):
            if str(row[c - 1]).strip():
                last = max(last, c)
                break
    return min(last, cap) if cap else last


def _colletter(c):
    return rowcol_to_a1(1, c)[:-1]


def _daily_section_ranges(g) -> List[Tuple[str, str]]:
    """The 8 daily section tables between the ORG leaderboard and the first
    captainship block. Each: header row (col A = section name, col C = 'Monday',
    day cols C-I, then RUNNING/LAST/PREVIOUS WEEK'S TOTALS) → the 'Last Week' row.
    COLLAPSED: stops at Last Week, drops the trailing 'Org Head' helper column."""
    out = []
    lb = _label_row(g, "ALPHALETE ORG", col=0, start=2)
    region_start = (_block_end(g, lb) + 1) if lb else 87
    # region ends at the first captainship PERFORMANCE / CAPTAIN TEAM block
    perf = _label_row(g, "CAPTAIN TEAM", col=0, start=region_start) or \
        _label_row(g, "PERFORMANCE", col=1, start=region_start) or len(g)
    for r in range(region_start, perf):
        # header row = has 'RUNNING WEEK TOTALS' (day-order agnostic: Frontier
        # runs Sun-Sat, the rest Mon-Sun) + a section name in col A.
        rowtext = " ".join(_cell(g, r, c) for c in range(1, len(g[r - 1]) + 1)).lower()
        if "running week totals" not in rowtext or not _cell(g, r, 1):
            continue
        name = _cell(g, r, 1)
        # right edge = the 'PREVIOUS WEEK'S TOTALS' column on the header row
        right = next((c for c in range(4, len(g[r - 1]) + 1)
                      if "previous week" in _cell(g, r, c).lower()), None)
        if right is None:
            right = _last_col(g, r, r)
        # bottom = the 'Last Week' row (the summary row right under Totals)
        end = None
        for rr in range(r + 1, min(r + 30, len(g) + 1)):
            if _cell(g, rr, 1).lower() == "last week":
                end = rr
                break
            if _cell(g, rr, 1).lower() in ("totals", "total"):
                end = rr        # fallback: Totals if no Last Week row follows
        if end:
            key = "section_" + name.lower().replace(" ", "_").replace("/", "_")
            out.append((key, f"A{r}:{_colletter(right)}{end}"))
    return out


def _org_leaderboard_names(g) -> set:
    """Normalized ICD names listed in the ALPHALETE ORG leaderboard (rank rows).
    A captainship is only emailed if one of its reps is in this set."""
    from automations.alphalete_org_report.tableau_http import _norm_owner
    lb = _label_row(g, "ALPHALETE ORG", col=0, start=2)
    if not lb:
        return set()
    end = _block_end(g, lb)
    return {_norm_owner(_cell(g, r, 2)) for r in range(lb, end + 1)
            if _cell(g, r, 1).isdigit() and _cell(g, r, 2)}


def _rowtext(g, r):
    return " ".join(_cell(g, r, c) for c in range(1, 14)).lower()


def _istitle(g, r):
    up = (_cell(g, r, 1) + " " + _cell(g, r, 2)).upper()
    return ("PERFORMANCE" in up or up.strip().endswith("CAPTAIN TEAM")
            or "CAPTAINSHIP TEAM" in up)


def _captainship_ranges(g) -> List[Tuple[str, str]]:
    """Every captainship performance block, in board order, as 3 sub-images:
    Summary (title + Product Summary + Current-vs-Prior, cols A:J), CAPTAIN TEAM
    leaderboard (A..header's WE cols, ≤10 weeks like the email), and the daily
    table (A:L, through Totals — WE-history stack excluded). Found by label."""
    from automations.alphalete_org_report.tableau_http import _norm_owner
    org = _org_leaderboard_names(g)

    def find(pred, r0, r1):
        return next((x for x in range(r0, min(r1, len(g) + 1)) if pred(x)), None)
    region_end = find(lambda r: "org - current vs prior"
                      in (_cell(g, r, 1) + _cell(g, r, 2)).lower(),
                      300, len(g) + 1) or len(g)
    out = []
    for ps in range(200, region_end):
        if not _cell(g, ps, 2).lower().startswith("product summary"):
            continue
        title, rr = ps, ps - 1          # topmost contiguous title row above ps
        while rr > 200:
            if not (_cell(g, rr, 1) + _cell(g, rr, 2)).strip():
                rr -= 1
                continue
            if _istitle(g, rr):
                title = rr
                rr -= 1
                continue
            break
        summ_end = find(lambda x: _cell(g, x, 2).lower().startswith("sales ( 4 week"),
                        ps, ps + 20)
        lbh = find(lambda x: _cell(g, x, 1) == "CAPTAIN TEAM",
                   (summ_end or ps), (summ_end or ps) + 8)
        tot = None
        if lbh:
            tot = find(lambda x: _cell(g, x, 1).upper() in ("TOTALS", "TOTAL"),
                       lbh + 2, lbh + 40)
        # ORG-MEMBERSHIP FILTER (Megan 2026-07-03): only email a captainship whose
        # ICD is in the ALPHALETE ORG leaderboard — i.e. one of its reps is there.
        # Captainships that live ONLY in the captainship lists are dropped.
        reps = ({_norm_owner(_cell(g, x, 2)) for x in range(lbh + 1, tot)
                 if _cell(g, x, 1).isdigit() and _cell(g, x, 2)}
                if lbh and tot else set())
        if not (reps & org):
            continue
        if summ_end:
            out.append((f"cap{title}_summary", f"A{title}:J{summ_end}"))
        if lbh and tot:
            right = min(_last_col(g, lbh, lbh), 12)       # header's WE cols, ≤10 wks
            out.append((f"cap{title}_leaderboard", f"A{lbh}:{_colletter(right)}{tot}"))
        anchor = tot or lbh or summ_end or ps
        dh = find(lambda x: "running week totals" in _rowtext(g, x), anchor + 1, anchor + 12)
        if dh:
            dtot = find(lambda x: _cell(g, x, 1).lower() in ("totals", "total"),
                        dh + 2, dh + 40)
            if dtot:
                out.append((f"cap{title}_daily", f"A{dh}:L{dtot}"))
    return out


def section_ranges(g) -> List[Tuple[str, str]]:
    """Return [(name, 'A1:Z9'), …] for the full email, by label: the top org
    summary (Product Summary, RAF ORG, ALPHALETE ORG leaderboard), the 8 daily
    section tables, and every captainship block (3 sub-images each). Bottom ORG
    summaries = Phase 3."""
    out = []
    ps = _label_row(g, "Product Summary", col=1)
    if ps:
        end = _block_end(g, ps)
        out.append(("product_summary", f"A{ps}:{_colletter(_last_col(g, ps, end))}{end}"))
    raf = _label_row(g, "RAF ORG", col=1)
    if raf:
        end = _block_end(g, raf)
        out.append(("raf_org", f"A{raf}:{_colletter(_last_col(g, raf, end))}{end}"))
    lb = _label_row(g, "ALPHALETE ORG", col=0, start=2)   # skip the r1 title cell
    if lb:
        end = _block_end(g, lb)
        first_val = next((c for c in range(3, len(g[lb - 1]) + 1)
                          if _cell(g, lb, c)), 3)
        last = first_val + _LB_WEEKS - 1
        out.append(("org_leaderboard", f"A{lb}:{_colletter(last)}{end}"))
    out.extend(_daily_section_ranges(g))
    out.extend(_captainship_ranges(g))
    return out


def _access_token() -> str:
    creds = Credentials.from_authorized_user_file(str(OAUTH_TOKEN_PATH), SCOPES)
    creds.refresh(_GARequest())
    return creds.token


def _export_png(gid: int, rng: str, out_path: Path, token: str) -> Path:
    """Render one A1 range of the copy tab to a trimmed PNG via the Sheets PDF
    export endpoint — exact-sheet look (colors/fonts/borders), no browser."""
    import fitz  # PyMuPDF
    from PIL import Image, ImageChops
    import time
    base = (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=pdf"
            f"&gid={gid}&range={rng}&gridlines=false&sheetnames=false"
            f"&printtitle=false&pagenumbers=false&fzr=false"
            f"&top_margin=0.05&bottom_margin=0.05&left_margin=0.05&right_margin=0.05")

    def _fetch(extra):
        for attempt in range(5):       # export endpoint 429s on rapid requests
            r = requests.get(base + extra,
                             headers={"Authorization": f"Bearer {token}"}, timeout=90)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.content
        raise RuntimeError(f"export {rng}: throttled (429) after retries")

    # Default: fit-to-WIDTH, landscape (crisp for the wide short tables). If that
    # paginates (a tall block like the leaderboard), re-render fit-to-PAGE so the
    # whole thing lands on ONE page — no stitch seam / mid-table gap.
    dpi = 200
    doc = fitz.open(stream=_fetch("&portrait=false&fitw=true"), filetype="pdf")
    if doc.page_count > 1:
        doc = fitz.open(stream=_fetch("&portrait=true&scale=4"), filetype="pdf")
        dpi = 320                      # fit-to-page shrinks — raise DPI to stay crisp

    def _trim(im):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bb = ImageChops.difference(im, bg).getbbox()
        if not bb:
            return im
        pad = 6
        return im.crop((max(0, bb[0] - pad), max(0, bb[1] - pad),
                        min(im.width, bb[2] + pad), min(im.height, bb[3] + pad)))

    pages = []
    for pg in doc:                       # normally 1 page now; stitch as a fallback
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
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def capture(out_dir: Path) -> List[Tuple[str, Path]]:
    """Render each section of the COPY tab → PNGs via PDF export. [(name, path)]."""
    sh = open_by_key(SHEET_ID)
    ws = _retry(lambda: sh.worksheet(SANDBOX_TAB))
    grid = _retry(ws.get_all_values)
    gid = ws.id
    ranges = section_ranges(grid)
    if not ranges:
        raise RuntimeError("no sections found on the copy tab — template changed?")
    out_dir.mkdir(parents=True, exist_ok=True)
    token = _access_token()
    print(f"[screenshot_email] rendering {len(ranges)} section(s) from copy tab "
          f"(gid={gid})", flush=True)
    import time
    out = []
    for i, (name, rng) in enumerate(ranges):
        if i:
            time.sleep(2)          # gentle pacing so the export endpoint doesn't 429
        p = _export_png(gid, rng, out_dir / f"{name}.png", token)
        print(f"    {name:26} {rng}  -> {p.name}", flush=True)
        out.append((name, p))
    return out


def build_email(images: List[Tuple[str, Path]], to_addrs: List[str],
                day: dt.date) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = FROM_ADDR
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = f"Alphalete Org Sales Board {day.month}/{day.day}"
    # Every image is self-labeled (its own red title bar), so no typed headers
    # and no top banner — just the screenshots stacked (Megan 2026-07-03).
    parts, cids = [], []
    for name, path in images:
        cid = make_msgid()[1:-1]
        cids.append((cid, path))
        parts.append(
            f'<img src="cid:{cid}" style="max-width:1000px;width:100%;'
            f'border:1px solid #ddd;margin:0 0 16px">')
    # 'ALPHALETE ORG' banner, constrained to the table width (not full-page).
    banner = ('<div style="background:#d9d9d9;text-align:center;padding:10px;'
              'font-size:22px;font-weight:bold;color:#8a0000;border:1px solid #bbb;'
              'max-width:1000px;width:100%;box-sizing:border-box;margin:0 0 16px">'
              'ALPHALETE ORG</div>')
    html = (
        '<div style="font-family:Arial,Helvetica,sans-serif;color:#000">'
        + banner
        + "".join(parts)
        + '<div style="font-size:11px;color:#888;margin-top:6px">'
        'Auto-generated from the Sales Board (copy tab), cross-checked against '
        'the VA tab. — Alphalete Reporting</div></div>')
    msg.set_content("Alphalete Org Sales Board — see the HTML version for the "
                    "screenshots.")
    msg.add_alternative(html, subtype="html")
    html_part = msg.get_payload()[-1]
    for cid, path in cids:
        html_part.add_related(Path(path).read_bytes(), "image", "png",
                              cid=f"<{cid}>")
    return msg


def send(msg: EmailMessage) -> None:
    # certifi's CA bundle — the python.org macOS build ships without system CAs,
    # so a default context fails SSL verification (works on the mini either way).
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as s:
        s.login(FROM_ADDR, app_password())
        s.send_message(msg)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Daily Sales Board screenshot email")
    ap.add_argument("--dry-run", action="store_true",
                    help="capture the screenshots + build the email, but DON'T send")
    ap.add_argument("--preview", action="store_true",
                    help="send to Megan only (sign-off before the proving list)")
    ap.add_argument("--to", help="comma-separated override recipients")
    a = ap.parse_args(argv)

    out_dir = Path("output") / "sales_board_shots" / dt.date.today().isoformat()
    images = capture(out_dir)
    print(f"[screenshot_email] saved: {[str(p) for _n, p in images]}", flush=True)

    if a.to:
        to = [x.strip() for x in a.to.split(",") if x.strip()]
    elif a.preview:
        to = PREVIEW_TO
    else:
        to = PROVING_TO
    msg = build_email(images, to, dt.date.today())

    if a.dry_run:
        eml = out_dir / "preview.eml"
        eml.write_bytes(bytes(msg))
        print(f"[screenshot_email] DRY-RUN — not sent. Recipients would be: {to}\n"
              f"  email written to {eml}", flush=True)
        return 0
    send(msg)
    print(f"[screenshot_email] sent to {to}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
