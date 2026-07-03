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
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import List, Tuple

from gspread.utils import rowcol_to_a1

from automations.org_sales_board.run import SHEET_ID, SANDBOX_TAB
from automations.recruiting_report.fill import open_by_key, _retry
from automations.captainship_drafts import sheet_shot
from automations.scheduled_6_days_out.email_send import (
    FROM_ADDR, SMTP_HOST, SMTP_PORT, app_password,
)

EDIT_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"

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


def section_ranges(g) -> List[Tuple[str, str]]:
    """Return [(name, 'A1:Z9'), …] for the PHASE-1 email sections, by label:
    the top org summary (Product Summary, RAF ORG, ALPHALETE ORG leaderboard)
    + the 8 daily section tables. Captainship blocks land in Phase 2."""
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
    return out


def capture(out_dir: Path) -> List[Tuple[str, Path]]:
    """Screenshot each section of the COPY tab → PNGs. Returns [(name, path)]."""
    sh = open_by_key(SHEET_ID)
    ws = _retry(lambda: sh.worksheet(SANDBOX_TAB))
    grid = _retry(ws.get_all_values)
    gid = ws.id
    ranges = section_ranges(grid)
    if not ranges:
        raise RuntimeError("no sections found on the copy tab — template changed?")
    out_dir.mkdir(parents=True, exist_ok=True)
    items = [(rng, out_dir / f"{name}.png") for name, rng in ranges]
    print(f"[screenshot_email] capturing {len(items)} section(s) from copy tab "
          f"(gid={gid}): {[r for _n, r in ranges]}", flush=True)
    sheet_shot.capture_ranges([(r, p) for r, p in items],
                              edit_url=EDIT_URL, gid=gid)
    return [(name, out_dir / f"{name}.png") for name, _rng in ranges]


_TITLES = {
    "product_summary": "Product Summary — This Week",
    "raf_org": "RAF ORG — Current vs Prior Weeks",
    "org_leaderboard": "ALPHALETE ORG — Leaderboard",
}


def build_email(images: List[Tuple[str, Path]], to_addrs: List[str],
                day: dt.date) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = FROM_ADDR
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = f"Alphalete Org Sales Board {day.month}/{day.day}"
    parts, cids = [], []
    for name, path in images:
        cid = make_msgid()[1:-1]
        cids.append((cid, path))
        # org-top blocks get a title header; daily sections are self-labeled in
        # the image, so they render as just the screenshot.
        title = _TITLES.get(name)
        title_html = (f'<div style="font-weight:bold;font-size:15px;'
                      f'color:#8a0000;margin:18px 0 6px">{title}</div>'
                      if title else '<div style="margin:14px 0 0"></div>')
        parts.append(
            title_html
            + f'<img src="cid:{cid}" style="max-width:1000px;width:100%;'
            f'border:1px solid #ddd">')
    html = (
        '<div style="font-family:Arial,Helvetica,sans-serif;color:#000">'
        '<div style="background:#d9d9d9;text-align:center;padding:10px;'
        'font-size:22px;font-weight:bold;color:#8a0000;border:1px solid #bbb">'
        'ALPHALETE ORG</div>'
        + "".join(parts)
        + '<div style="font-size:11px;color:#888;margin-top:18px">'
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
