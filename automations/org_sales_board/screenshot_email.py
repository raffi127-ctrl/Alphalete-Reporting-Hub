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
from typing import List, Optional, Tuple

import requests
from google.auth.transport.requests import Request as _GARequest
from google.oauth2.credentials import Credentials
from gspread.utils import rowcol_to_a1

from automations.org_sales_board.run import SHEET_ID, SANDBOX_TAB
from automations.recruiting_report.fill import (
    open_by_key, _retry, SCOPES, OAUTH_TOKEN_PATH,
)
from automations.shared import board_email_html as _beh
from automations.scheduled_6_days_out.email_send import (
    FROM_ADDR, SMTP_HOST, SMTP_PORT, app_password,
    PHOTO_EMBED_PX, PHOTO_IMG, _signature_html, _circular_photo_png,
)

# Rollout recipient tiers (Megan 2026-07-03).
# Maud removed 2026-07-21 — on maternity leave (add her back on return).
PREVIEW_TO = ["Meganhidalgo1191@gmail.com"]
PROVING_TO = ["raffi127@gmail.com",
              "Meganhidalgo1191@gmail.com"]
# GO-LIVE distro — Gmail contact GROUPS, expanded to live addresses at send time
# via the People API (automations.shared.contacts_auth). Names must match the
# groups in alphaletereporting@gmail.com's contacts exactly.
#
# ONE GROUP, not three (Eve 2026-07-29): she named "Alphalete Org Owners" as the
# official distro when the send went live. The old three-group plan (Megan
# 2026-07-04) also carried "Carlos' Captain Team" + "Raf's Captain Team"; they
# are left here commented rather than deleted because turning them back on is a
# decision, not a rediscovery. Erring narrow is deliberate: an org-wide sales
# email sent to two extra groups cannot be taken back, and an under-send is a
# quiet one-line fix.
DISTRO_GROUPS = ["Alphalete Org Owners"]
# DISTRO_GROUPS += ["Carlos' Captain Team", "Raf's Captain Team"]

_LB_WEEKS = 4          # leaderboard columns to show: this week + 3 prior (== the email)

# RASTER RESOLUTION for every board screenshot in every board email — this
# module's own, the Country board's, the All Units board's. ONE constant because
# they all render through _export_png.
#
# 2.0 doubles the pixels the PDF is rasterised at (200 -> 400 dpi, or 320 -> 640
# on the fit-to-page path). It is NOT an upscale: the export is vector, so the
# glyphs are genuinely re-drawn at twice the size. The emails paint these into a
# 900-CSS-px column (shared.board_email_html.DISPLAY_PX), which is 1800 device
# pixels on any retina screen — under-rendering was the whole reason the numbers
# looked pixelated when Eve enlarged them (2026-07-31). Raising DISPLAY_PX
# without raising this re-breaks it, and vice versa: they are a pair.
RENDER_SCALE = 2.0

# The All Units Org Sales Board is a SECOND SECTION of this email as of
# 2026-07-31 (Eve: "lo que antes eran dos mails, hay que juntarlos en uno"). Its
# images carry this name prefix; build_email puts the labelled divider in front
# of the first one. It used to be its own mail via automations.board_emails —
# that board entry is retired and its orchestrator slot switched off, so the
# board is delivered exactly once.
ALLUNITS_PREFIX = "allunits_"


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


def _colnum(letters: str) -> int:
    """'A' -> 1, 'L' -> 12. The inverse of _colletter."""
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def column_pixels(sh, gid: int) -> List[int]:
    """Each column's width ON THE SHEET, in sheet pixels (hidden columns → 0).

    Read from the tab, never a table of numbers in here: a column someone
    widens has to change the email with it. See `_range_width_px`."""
    meta = _retry(lambda: sh.fetch_sheet_metadata(
        {"fields": "sheets(properties(sheetId),"
                   "data(columnMetadata(pixelSize,hiddenByUser)))"}))
    for s in meta.get("sheets", []):
        if s.get("properties", {}).get("sheetId") != gid:
            continue
        data = s.get("data") or [{}]
        return [0 if c.get("hiddenByUser") else int(c.get("pixelSize") or 100)
                for c in (data[0].get("columnMetadata") or [])]
    return []


def _range_width_px(colpx: List[int], rng: str) -> int:
    """How wide 'A24:F87' is on the sheet, in sheet pixels.

    WHY THIS EXISTS. The Sheets PDF export is fit-to-WIDTH, so every block comes
    back the same number of image pixels wide however many columns it has: the
    six-column A:F leaderboard and a twelve-column A:L daily table both fill the
    page. Showing them all at the same width in the email then blew the
    leaderboard up to ~1.9x the text size of the tables around it (Eve,
    2026-07-31: "la letra casi el doble de grande").

    Sizing each image against the WIDEST block instead puts one sheet pixel at
    the same size in every image — the proportions the board actually has in
    Sheets. Returns 0 when the range can't be read, and build_email falls back
    to the old equal-width layout rather than guessing."""
    import re
    m = re.match(r"^([A-Z]+)\d+:([A-Z]+)\d+$", rng.strip().upper())
    if not m or not colpx:
        return 0
    a, b = _colnum(m.group(1)), _colnum(m.group(2))
    return sum(colpx[c - 1] for c in range(a, b + 1) if c - 1 < len(colpx))


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
            # Weeks run most-recent-LEFT from the first "WE " column; keep only the
            # last _LB_WEEKS of them so each rep's row shows the past 4 weeks of
            # sales (Megan 2026-07-08). Columns are all visible — unlike the daily
            # WE-history stack, which lives in hidden rows and won't render.
            hdr = g[lbh - 1] if lbh - 1 < len(g) else []
            first_we = next((ci for ci in range(2, len(hdr) + 1)
                             if (hdr[ci - 1] or "").strip().lower().startswith("we ")), 3)
            right = min(first_we + _LB_WEEKS - 1, _last_col(g, lbh, lbh))
            out.append((f"cap{title}_leaderboard", f"A{lbh}:{_colletter(right)}{tot}"))
        anchor = tot or lbh or summ_end or ps
        dh = find(lambda x: "running week totals" in _rowtext(g, x), anchor + 1, anchor + 12)
        if dh:
            dtot = find(lambda x: _cell(g, x, 1).lower() in ("totals", "total"),
                        dh + 2, dh + 40)
            if dtot:
                # WE-history week-stack sits directly below Totals — last _LB_WEEKS
                # weeks. Render reps → Totals → stack as ONE image so there's no gap
                # between the Totals row and WE 7.5. Those stack rows are HIDDEN on
                # the copy tab, so emit a _wehide span marker; capture() unhides
                # exactly that span before the PDF export (then restores it) — the
                # export skips hidden rows, else the stack collapses to one week.
                we_start, we_end, n = dtot + 1, dtot, 0
                for rr in range(dtot + 1, min(dtot + 30, len(g) + 1)):
                    lab = (_cell(g, rr, 1) + " " + _cell(g, rr, 2)).strip().lower()
                    if lab.startswith("we "):
                        we_end, n = rr, n + 1
                        if n >= _LB_WEEKS:
                            break
                    elif lab:
                        break                      # non-WE row → stack ended
                if we_end > dtot:
                    out.append((f"cap{title}_daily", f"A{dh}:L{we_end}"))
                    out.append((f"cap{title}_wehide", f"A{we_start}:L{we_end}"))
                else:
                    out.append((f"cap{title}_daily", f"A{dh}:L{dtot}"))
    return out


def _bottom_org_ranges(g, start: int = None) -> List[Tuple[str, str]]:
    """Bottom 'X ORG - Current vs Prior Weeks' summary tables (RAF w/out Carlos &
    Colten, CARLOS, COLTEN, BEN). Header → 'Sales ( 4 Week AVG)' row; the frozen
    Last/Prior/2wp/3wp history rows below are excluded. Same org filter: include an
    ORG only if its head is on the ALPHALETE ORG leaderboard (RAF→Rafael,
    BEN→Benjamin Burden, etc.).

    `start` = first row of the bottom region, so the TOP 'RAF ORG - Current vs
    Prior Weeks' block (a different table: the whole org, Carlos + Colten
    included) can't be swept in. It used to be a hardcoded `range(1600, …)`, which
    silently skipped RAF w/out at row 1592 — the block was 8 rows above the magic
    number, so the email carried CARLOS and COLTEN but never RAF's own. Default:
    everything after the last daily section. [[no hardcoded rows]]"""
    import re
    lb = _label_row(g, "ALPHALETE ORG", col=0, start=2)
    lb_end = _block_end(g, lb) if lb else 0
    firsts = {_cell(g, r, 2).split()[0].lower() for r in range(lb or 1, lb_end + 1)
              if _cell(g, r, 1).isdigit() and _cell(g, r, 2)}
    if start is None:
        dailies = _daily_section_ranges(g)
        start = (int(re.search(r"(\d+)$", dailies[-1][1]).group(1)) + 1
                 if dailies else (lb_end or 1) + 1)
    out = []
    for r in range(start, len(g) + 1):
        text = (_cell(g, r, 1) + " " + _cell(g, r, 2)).lower().strip()
        if not re.search(r"\borg\b.*current vs prior", text):
            continue
        short = text.split()[0].rstrip("'s")
        if not any(fn.startswith(short) for fn in firsts):
            continue
        end = next((x for x in range(r, r + 16)
                    if _cell(g, x, 2).lower().startswith("sales ( 4 week")), None)
        if end:
            out.append((f"botorg_{short}", f"A{r}:J{end}"))
    return out


def _top_org_range(g, after: int, before: int) -> Optional[Tuple[str, str]]:
    """The TOP 'RAF ORG - Current vs Prior Weeks' box — the one that sits
    between Product Summary and the ALPHALETE ORG leaderboard.

    This is the WHOLE org, Carlos and Colten included, which is what makes it
    different from the bottom 'RAF ORG (w/out Carlos & Colten)' box that closes
    the email. It was dropped on 2026-07-29 as "the same table twice over" and
    Eve asked for it back on 2026-07-31: the two answer different questions, and
    this is the one that belongs at the top, right under the summary.

    Bounded by ROWS WE FOUND (`after` = the end of Product Summary, `before` =
    the leaderboard header) rather than searched for globally, so the four
    bottom Current-vs-Prior boxes can't be picked up here by mistake."""
    import re
    for r in range(after + 1, max(after + 1, before)):
        text = (_cell(g, r, 1) + " " + _cell(g, r, 2)).lower().strip()
        if not re.search(r"\borg\b.*current vs prior", text):
            continue
        # Same bottom edge as the other Current-vs-Prior boxes: the 4-week
        # average row. The frozen week-by-week history under it stays out.
        end = next((x for x in range(r, min(r + 16, before))
                    if _cell(g, x, 2).lower().startswith("sales ( 4 week")), None)
        if end:
            return ("top_org_current_vs_prior", f"A{r}:J{end}")
    return None


def section_ranges(g) -> List[Tuple[str, str]]:
    """Return [(name, 'A1:Z9'), …] for the full email, by label:

        Product Summary → ALPHALETE ORG leaderboard → the 8 daily section tables
        (Retail NL … Retail Internet) → RAF ORG (w/out Carlos & Colten), CARLOS
        ORG, COLTEN ORG — Current vs Prior Weeks.

    SHAPE SET BY EVE 2026-07-29: the email runs to the Retail Internet daily box
    and then closes with one Current-vs-Prior summary per org. Two things left:

    - The 7 CAPTAINSHIP blocks (21 images) are OUT. They tripled the email's
      length and are the Captainship Reports' job, not this one's.
      `_captainship_ranges` is kept below, uncalled, so putting them back is a
      one-line change.
    - The TOP 'RAF ORG - Current vs Prior Weeks' (row ~16) was taken out the
      same day as "the same table twice over" and PUT BACK on 2026-07-31: it is
      the whole org WITH Carlos and Colten, where the bottom 'RAF ORG (w/out
      Carlos & Colten)' box that leads the closing trio is Rafael's own. Two
      different questions, so both are in — the top one right under Product
      Summary, where Eve reads it. See `_top_org_range`.
    """
    out = []
    ps = _label_row(g, "Product Summary", col=1)
    ps_end = 0
    if ps:
        ps_end = _block_end(g, ps)
        out.append(("product_summary",
                    f"A{ps}:{_colletter(_last_col(g, ps, ps_end))}{ps_end}"))
    lb = _label_row(g, "ALPHALETE ORG", col=0, start=2)   # skip the r1 title cell
    top = _top_org_range(g, ps_end, lb or 1) if ps else None
    # BETWEEN Product Summary and the ALPHALETE ORG leaderboard (Eve,
    # 2026-07-31). It is the whole org, Carlos and Colten included, so it reads
    # as the second half of the summary at the top — not as one of the three
    # per-org boxes that close the email. It was briefly moved down to lead that
    # closing group; it belongs here.
    if top:
        out.append(top)
    if lb:
        end = _block_end(g, lb)
        first_val = next((c for c in range(3, len(g[lb - 1]) + 1)
                          if _cell(g, lb, c)), 3)
        last = first_val + _LB_WEEKS - 1
        out.append(("org_leaderboard", f"A{lb}:{_colletter(last)}{end}"))
    out.extend(_daily_section_ranges(g))
    out.extend(_bottom_org_ranges(g))
    return out


def _access_token() -> str:
    creds = Credentials.from_authorized_user_file(str(OAUTH_TOKEN_PATH), SCOPES)
    creds.refresh(_GARequest())
    return creds.token


def _export_png(gid: int, rng: str, out_path: Path, token: str,
                spreadsheet_id: str | None = None,
                scale: float = None) -> Path:
    """Render one A1 range of a tab to a trimmed PNG via the Sheets PDF export
    endpoint — exact-sheet look (colors/fonts/borders), no browser.

    `spreadsheet_id` defaults to this module's SHEET_ID (the ORG board's
    workbook). Pass it explicitly to render a tab in a DIFFERENT workbook —
    `gid` alone is not enough, since the export URL needs the file too, and a
    gid from another workbook silently renders the wrong sheet. Used by
    country_sales_board.slack_post, whose tab lives in the ATT Program - Focus
    Report workbook.

    `scale` multiplies the RASTER DPI (default RENDER_SCALE). It does not stretch
    a small image — the PDF is vector, so a higher DPI genuinely re-renders the
    text at more pixels."""
    import fitz  # PyMuPDF
    from PIL import Image, ImageChops
    import time
    scale = RENDER_SCALE if scale is None else scale
    base = (f"https://docs.google.com/spreadsheets/d/"
            f"{spreadsheet_id or SHEET_ID}/export?format=pdf"
            f"&gid={gid}&range={rng}&gridlines=false&sheetnames=false"
            f"&printtitle=false&pagenumbers=false&fzr=false"
            f"&top_margin=0.05&bottom_margin=0.05&left_margin=0.05&right_margin=0.05")

    def _fetch(extra):
        # The export endpoint 429s on rapid requests, and this email is the
        # heaviest user of it: 14 Org sections + 4 All Units blocks, each of which
        # may need a SECOND fetch when the first paginates — ~36 requests in a
        # run. The old ladder (5 tries, 5s..25s, ~75s of patience) ran out
        # mid-render and killed the whole email over one throttled block
        # (2026-07-31). Retry-After is honoured when Google sends it, else back
        # off 8s..64s over 8 tries — ~4½ minutes, which is longer than any
        # per-minute window it is enforcing.
        for attempt in range(8):
            r = requests.get(base + extra,
                             headers={"Authorization": f"Bearer {token}"}, timeout=90)
            if r.status_code in (429, 503):
                wait = 8 * (attempt + 1)
                try:
                    wait = max(wait, int(r.headers.get("Retry-After", 0)))
                except (TypeError, ValueError):
                    pass
                print(f"    …export {rng} throttled ({r.status_code}), "
                      f"retry {attempt + 1}/8 in {wait}s", flush=True)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.content
        raise RuntimeError(f"export {rng}: throttled (429) after retries")

    # Default: fit-to-WIDTH, landscape (crisp for the wide short tables). If that
    # paginates (a tall block like the leaderboard), re-render fit-to-PAGE so the
    # whole thing lands on ONE page — no stitch seam / mid-table gap.
    dpi = round(200 * scale)
    doc = fitz.open(stream=_fetch("&portrait=false&fitw=true"), filetype="pdf")
    if doc.page_count > 1:
        doc = fitz.open(stream=_fetch("&portrait=true&scale=4"), filetype="pdf")
        dpi = round(320 * scale)       # fit-to-page shrinks — raise DPI to stay crisp

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


def stitch_vertical(paths: List[Path], out: Path, gap: int = 28) -> Path:
    """Stack rendered blocks into ONE image, left-aligned on a white canvas sized
    to the widest, with a white gutter between them.

    Deliberately PADS rather than SCALES: blocks render at different widths (a
    10-column summary vs a 25-column delta chart) and resampling the narrow one
    up to match would soften text instead of enlarging it.

    Used for the SLACK DMs, which take a single file. The EMAILS do not stitch —
    they send one image per block so each one gets the full 900px column instead
    of being padded down to whatever fraction of the widest block it occupies.
    That padding is what made the narrow tables unreadable in the mail."""
    from PIL import Image
    ims = [Image.open(p).convert("RGB") for p in paths]
    if len(ims) == 1:
        ims[0].save(out)
        return out
    w = max(i.width for i in ims)
    h = sum(i.height for i in ims) + gap * (len(ims) - 1)
    canvas = Image.new("RGB", (w, h), (255, 255, 255))
    y = 0
    for im in ims:
        canvas.paste(im, (0, y))
        y += im.height + gap
    canvas.save(out)
    return out


def _stack_row_spans(ranges) -> List[Tuple[int, int]]:
    """1-based (first,last) hidden row spans to reveal for the WE-history stacks.
    These _wehide markers are NOT rendered — they only tell capture() which rows
    to unhide (and later re-hide) so the merged daily image shows all 4 weeks."""
    import re
    spans = []
    for name, rng in ranges:
        if name.endswith("_wehide"):
            m = re.match(r"[A-Z]+(\d+):[A-Z]+(\d+)", rng)
            if m:
                spans.append((int(m.group(1)), int(m.group(2))))
    return spans


def _set_rows_hidden(sh, gid: int, spans: List[Tuple[int, int]], hidden: bool) -> None:
    reqs = [{"updateDimensionProperties": {
                "range": {"sheetId": gid, "dimension": "ROWS",
                          "startIndex": a - 1, "endIndex": b},
                "properties": {"hiddenByUser": hidden},
                "fields": "hiddenByUser"}}
            for (a, b) in spans if b >= a]
    if reqs:
        _retry(lambda: sh.batch_update({"requests": reqs}))


def capture(out_dir: Path) -> List[Tuple[str, Path, int]]:
    """Render each section of the COPY tab → PNGs via PDF export.

    Returns [(name, path, sheet_width_px)]. The third item is how wide the block
    is ON THE SHEET, which is what lets the email show them all at one scale
    instead of stretching each to the same width — see `_range_width_px`."""
    sh = open_by_key(SHEET_ID)
    ws = _retry(lambda: sh.worksheet(SANDBOX_TAB))
    grid = _retry(ws.get_all_values)
    gid = ws.id
    ranges = section_ranges(grid)
    if not ranges:
        raise RuntimeError("no sections found on the copy tab — template changed?")
    out_dir.mkdir(parents=True, exist_ok=True)
    token = _access_token()
    colpx = column_pixels(sh, gid)
    print(f"[screenshot_email] rendering {len(ranges)} section(s) from copy tab "
          f"(gid={gid})", flush=True)
    # The captainship WE-history stacks live in hidden rows; the PDF export skips
    # hidden rows, so reveal exactly the 4-week spans we're about to shoot, then
    # restore the copy tab's original state (only the first/most-recent week
    # visible) in a finally so a render crash can't leave the tab expanded.
    spans = _stack_row_spans(ranges)
    if spans:
        _set_rows_hidden(sh, gid, spans, hidden=False)
        print(f"[screenshot_email] revealed {len(spans)} WE-history stack(s) "
              "for the render", flush=True)
    import time
    out = []
    render = [(n, r) for (n, r) in ranges if not n.endswith("_wehide")]
    try:
        for i, (name, rng) in enumerate(render):
            if i:
                time.sleep(2)      # gentle pacing so the export endpoint doesn't 429
            p = _export_png(gid, rng, out_dir / f"{name}.png", token)
            w = _range_width_px(colpx, rng)
            print(f"    {name:26} {rng:14} {w or '?':>5}px sheet  -> {p.name}",
                  flush=True)
            out.append((name, p, w))
    finally:
        rehide = [(a + 1, b) for (a, b) in spans if b > a]   # keep 1st week visible
        if rehide:
            _set_rows_hidden(sh, gid, rehide, hidden=True)
    out.extend(capture_all_units(out_dir))
    return out


def capture_all_units(out_dir: Path) -> List[Tuple[str, Path, int]]:
    """The All Units Org Sales Board's blocks, appended to this email's images.

    Rendered by the board's OWN module (all_campaigns_board.slack_post), which is
    also what its Slack DM uses — so the section here can never disagree with the
    board's other channel, and a change to the board's shape is still fixed in
    one place. This function only decides that it goes in this mail.

    NEVER FATAL. The Org board is the bulk of the email and it going out without
    the All Units section beats it not going out at all, so a failure here logs
    and returns nothing. A silently missing section is visible — the divider and
    the images are simply absent — unlike a swallowed exception mid-board."""
    try:
        import shutil
        from automations.all_campaigns_board.slack_post import build_pngs
        parts, rng = build_pngs()
        # COPY into this email's dated folder. The board's own renderer writes to
        # one fixed filename that tomorrow's run overwrites, and --send-reviewed
        # mails the files the manifest names — which may be hours old by the time
        # a checkmark lands. Without the copy the approved Org sections would go
        # out beside a NEWER All Units board.
        out_dir.mkdir(parents=True, exist_ok=True)
        copied = []
        for name, p, w in parts:
            dest = out_dir / f"{name}.png"
            shutil.copyfile(p, dest)
            # `w` is the block's width ON THE SHEET, carried through so the All
            # Units blocks scale against the Org ones instead of each section
            # having its own private idea of full width.
            copied.append((name, dest, w))
        print(f"[screenshot_email] All Units section: {rng} "
              f"-> {len(copied)} image(s)", flush=True)
        return copied
    except Exception as e:  # noqa: BLE001
        print(f"[screenshot_email] ⚠ All Units section SKIPPED "
              f"({type(e).__name__}: {e}) — mailing the Org board alone",
              flush=True)
        return []


def build_email(images: List[Tuple], to_addrs: List[str],
                day: dt.date) -> EmailMessage:
    """`day` is the day the numbers are FOR — yesterday, not the run date (Eve
    2026-07-29). The board only ever carries completed days, so a 7/29 run shows
    7/28's sales; titling it 7/29 dated the email a day ahead of the sales it
    was showing. Same rule as the Country Sales Board Slack DM."""
    msg = EmailMessage()
    msg["From"] = FROM_ADDR
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = f"Alphalete Org Sales Board {day.month}/{day.day}"
    # Every image is self-labeled (its own red title bar), so no typed headers —
    # just the screenshots stacked under the board banner (Megan 2026-07-03).
    #
    # LAYOUT lives in shared.board_email_html, not here — the Country board email
    # had a second copy of it and the two had drifted. Both lessons that layout
    # encodes are documented there: one <tr><td> per image (Gmail flows bare
    # <img> tags two-per-row and the browser preview hides it), and each image
    # sized to its block's real width ON THE SHEET so one sheet pixel is the same
    # size in every image.
    # ONE scale for the whole mail, Org sections and All Units alike, so the same
    # ten-column table is the same size on both sides of the divider. The delta
    # chart is excluded from setting it (see board_email_html.FULL_BLEED) — it is
    # half again as wide as anything else and would otherwise shrink every normal
    # table to ~63px per column.
    widest = _beh.scale_of(images)
    rows, cids = [], []
    rows.append(_beh.banner_row("ALPHALETE ORG"))
    seen_allunits = False
    for entry in images:
        name, path = entry[0], entry[1]
        # The All Units board rides in THIS email now (Eve 2026-07-31: "lo que
        # antes eran dos mails, hay que juntarlos en uno"). Its images are the
        # ones named allunits_*, and the divider goes in front of the first of
        # them — derived from the names so the manifest stays a flat list and
        # --send-reviewed needs no second concept.
        if not seen_allunits and str(name).startswith(ALLUNITS_PREFIX):
            rows.append(_beh.separator_row())
            seen_allunits = True
        cid = make_msgid()[1:-1]
        cids.append((cid, path))
        rows.append(_beh.image_row(cid, alt=str(name),
                                   width_px=_beh.sheet_px(entry),
                                   widest_px=widest))
    # Copy-vs-VA comparison breakdown chart: RETIRED 2026-07-21 (Megan). The VA
    # tab is no longer hand-filled and Eve verifies the automation directly, so
    # the chart only produced false "missed pull" rows off the bottom
    # leaderboard/history tables. Removed from the board email.
    # Evelyn signs it (Eve, 2026-07-31), from the single definition in
    # scheduled_6_days_out — the same block the captainship reports carry. It
    # replaces the grey "Auto-generated" line: this goes to the whole owner
    # distro, and a report from a person reads as one somebody stands behind.
    cid_photo = make_msgid()[1:-1]
    rows.append(_beh.text_row('Best,<br><br>'
                              + _signature_html(f"<{cid_photo}>")))
    html = _beh.document(rows)
    msg.set_content("Alphalete Org Sales Board + All Units Org Sales Board — "
                    "see the HTML version for the screenshots.\n\n"
                    "Best,\nEvelyn Sobrino")
    msg.add_alternative(html, subtype="html")
    html_part = msg.get_payload()[-1]
    for cid, path in cids:
        html_part.add_related(Path(path).read_bytes(), "image", "png",
                              cid=f"<{cid}>")
    html_part.add_related(_circular_photo_png(PHOTO_IMG, PHOTO_EMBED_PX),
                          maintype="image", subtype="png",
                          cid=f"<{cid_photo}>")
    return msg


def out_dir_for(day: dt.date) -> Path:
    return Path("output") / "sales_board_shots" / day.isoformat()


def _write_manifest(out_dir: Path, images: List[Tuple]) -> Path:
    """Record the ORDER the images go in the email, and how wide each block is
    on the sheet. --send-reviewed mails these exact files rather than
    re-capturing: what was approved is what goes out, even if the board moved
    between the review post and the checkmark. `sheet_px` rides along so the
    send lays them out at exactly the scale the reviewed preview did."""
    import json
    rows = [{"name": n, "file": Path(f).name, "sheet_px": (rest[0] if rest else 0)}
            for (n, f, *rest) in images]
    p = out_dir / "manifest.json"
    p.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return p


def reviewed_images(day: dt.date) -> List[Tuple[str, Path, int]]:
    """The day's captured images, in email order, from the manifest.

    `sheet_px` is 0 for a manifest written before the widths existed; the email
    then keeps the old equal-width layout rather than mis-scaling a day that has
    already been approved."""
    import json
    out_dir = out_dir_for(day)
    man = out_dir / "manifest.json"
    if not man.exists():
        raise RuntimeError(
            f"no manifest in {out_dir} — nothing was captured for "
            f"{day:%Y-%m-%d}. Build the preview first (--dry-run).")
    rows = json.loads(man.read_text(encoding="utf-8"))
    images = [(r["name"], out_dir / r["file"], int(r.get("sheet_px") or 0))
              for r in rows]
    missing = [str(p) for _n, p, _w in images if not p.exists()]
    if missing:
        raise RuntimeError(f"manifest lists files that are gone: {missing}")
    return images


def preview_html(msg: EmailMessage) -> str:
    """The email as ONE self-contained HTML string — every inline cid: image
    swapped for a data: URI. Used for the on-disk preview and, through it, for
    the PDF the reviewers approve, so what they see is the built email itself
    and not a second rendering of the same data."""
    import base64
    body = msg.get_body(preferencelist=("html",))
    html = body.get_content()
    for part in msg.walk():
        cid = (part.get("Content-ID") or "").strip("<>")
        if cid and part.get_content_maintype() == "image":
            b64 = base64.b64encode(part.get_payload(decode=True)).decode()
            html = html.replace(
                f"cid:{cid}", f"data:{part.get_content_type()};base64,{b64}")
    return ("<!doctype html><meta charset='utf-8'>"
            f"<title>{msg['Subject']}</title>"
            f"<body style='margin:24px;background:#fff'>{html}</body>")


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


def _draft(msg: EmailMessage, out_dir: Path, images: List[Tuple]) -> None:
    """Land `msg` as a Gmail draft for review, and write the on-disk preview too.

    RETRIES THE UPLOAD. This email is ~9MB of inline PNGs and the render that
    produced them takes ~4 minutes; a single dropped connection on the upload used
    to throw away the whole run (ConnectionResetError, 2026-08-01). Three attempts
    with a short backoff, and `--draft --send-reviewed` re-uploads from the images
    already on disk so even an exhausted retry costs nothing to redo."""
    import time
    from automations.shared.gmail_draft import create_draft
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "preview.eml").write_bytes(bytes(msg))
    (out_dir / "preview.html").write_text(preview_html(msg), encoding="utf-8")
    for attempt in range(3):
        try:
            create_draft(msg)
            break
        except Exception as e:  # noqa: BLE001 — any transport failure is retryable
            if attempt == 2:
                raise
            print(f"[screenshot_email] draft upload failed "
                  f"({type(e).__name__}), retry {attempt + 1}/2", flush=True)
            time.sleep(5 * (attempt + 1))
    kb = sum(Path(p).stat().st_size for _n, p, *_ in images) // 1024
    print(f"[screenshot_email] DRAFT created — nothing sent. To: {msg['To']}\n"
          f"  subject: {msg['Subject']}\n"
          f"  {kb} KB of images across {len(images)} block(s)\n"
          f"  preview: {out_dir / 'preview.html'}", flush=True)
    print("=== done (draft) ===", flush=True)


def board_fill_ok() -> Tuple[bool, str]:
    """The email must reflect a COMPLETE fill. Reads the board's run manifest and
    returns (ok, reason). Safe to send ONLY when today's fill is data-complete —
    a clean run, or INCOMPLETE *only* because of VA-compare differences (all the
    data is there, the VA tab just disagrees). A failed/skipped SECTION, PROGRAM,
    or CAPTAINSHIP pull means data is missing → NOT safe (Megan 2026-07-03)."""
    from automations.shared import run_manifest as _rm
    m = _rm.read_manifest("org-sales-board")
    if not m:
        return False, "no Sales Board fill manifest found (did the board run?)"
    ts = str(m.get("run_ts") or "")[:10]
    if ts != dt.date.today().isoformat():
        return False, f"Sales Board fill is not from today (manifest run_ts {ts or '?'})"
    missing = [f for f in (m.get("failed") or [])
               if not str(f).lower().startswith("compare:")]
    if missing:
        return False, "Sales Board fill INCOMPLETE — missing data: " + "; ".join(missing)
    return True, ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Daily Sales Board screenshot email")
    ap.add_argument("--dry-run", action="store_true",
                    help="capture the screenshots + build the email, but DON'T send")
    ap.add_argument("--preview", action="store_true",
                    help="send to Megan only (sign-off before the proving list)")
    ap.add_argument("--to", help="comma-separated override recipients")
    ap.add_argument("--distro", action="store_true",
                    help="GO-LIVE: send to the 3 contact groups, expanded live via "
                         "the People API (needs contacts_auth authorized)")
    ap.add_argument("--force", action="store_true",
                    help="skip the board-fill-complete guard (manual/laptop testing)")
    ap.add_argument("--draft", action="store_true",
                    help="land the built email as a Gmail DRAFT and send nothing. "
                         "For checking the layout in a real mail client — Gmail "
                         "lays images out differently from the on-disk preview. "
                         "DO NOT press Send on the draft: Gmail's compose window "
                         "strips inline images out of what it sends. "
                         "[[project_captainship-gmail-cid-scramble]]")
    ap.add_argument("--send-reviewed", action="store_true",
                    help="mail the images ALREADY captured for --date (from the "
                         "manifest) — no re-capture. What was approved is what "
                         "goes out. This is what the review gate calls.")
    ap.add_argument("--date", default=None,
                    help="run date (default today). With --send-reviewed, which "
                         "day's captured images to mail.")
    a = ap.parse_args(argv)
    today = dt.date.fromisoformat(a.date) if a.date else dt.date.today()

    # --- the approved path: mail exactly what was reviewed, rebuild nothing ---
    if a.send_reviewed:
        images = reviewed_images(today)
        print(f"[screenshot_email] mailing {len(images)} reviewed image(s) from "
              f"{out_dir_for(today)}", flush=True)
        to = _recipients(a)
        if to is None:
            return 2
        msg = build_email(images, to, today - dt.timedelta(days=1))
        if a.draft:
            # --draft ON TOP OF --send-reviewed: rebuild the mail from the images
            # already on disk and re-upload, capturing nothing. The 18-block
            # render takes ~4 minutes and the Gmail upload is ~9MB, so a dropped
            # connection on the last step used to cost the whole render
            # (ConnectionResetError, 2026-08-01). Now it costs one retry.
            _draft(msg, out_dir_for(today), images)
            return 0
        if a.dry_run:
            print(f"[screenshot_email] DRY-RUN — not sent. Would go to: {to}",
                  flush=True)
            print("=== done (dry-run) ===", flush=True)
            return 0
        send(msg)
        print(f"[screenshot_email] sent to {to}", flush=True)
        _publish_sent()
        print("=== done ===", flush=True)
        return 0

    # GUARD: never email a partial board on the AUTOMATED run. Only a DATA-COMPLETE
    # fill is safe (clean, or INCOMPLETE only from VA-compare notes). A missing
    # section/captainship pull → don't send. Bypassed by: --dry-run (never sends);
    # --force (CLI); and HUB_MANUAL_RUN (any manual Hub play — the board manifest is
    # machine-local + stale on the box that didn't run the fill, and a manual click
    # is a human decision, so the play button must always run). [[feedback_hub_run_anywhere]]
    import os as _os
    # --draft never mails anyone, so it is held to the same standard as --dry-run:
    # the guards below are about not SENDING a partial board.
    _manual = a.force or _os.environ.get("HUB_MANUAL_RUN") or a.draft
    if not (a.dry_run or _manual):
        ok, why = board_fill_ok()
        if not ok:
            print(f"[screenshot_email] NOT SENT — {why}. The email would show "
                  f"incomplete/incorrect numbers. (--force overrides.)", flush=True)
            return 2

    # SECOND GUARD (Eve 2026-07-29): the manifest above says "the fill RAN clean";
    # this says "yesterday is actually ON the board". A run that succeeded having
    # written nothing passes the first and fails this one. Same rule the
    # orchestrator's readiness probe uses (org_sales_board.data_gate), so the
    # scheduled path holds the report instead of sending early — this repeat is
    # for every OTHER path (manual, Hub, another machine). Always PRINTED, so a
    # dry-run shows exactly what the automated run would decide.
    from automations.org_sales_board import data_gate
    _gate_ok, _gate_why = data_gate.gate()
    print(f"[screenshot_email] data gate: {'OK' if _gate_ok else 'HOLD'} — {_gate_why}",
          flush=True)
    if not (_gate_ok or a.dry_run or _manual):
        print("[screenshot_email] NOT SENT — the board is short of yesterday. "
              "It sends by itself once the missing section fills (or at "
              f"{data_gate.SEND_ANYWAY_AFTER}). (--force overrides.)", flush=True)
        return 2

    out_dir = out_dir_for(today)
    images = capture(out_dir)
    _write_manifest(out_dir, images)
    print(f"[screenshot_email] saved: {[str(p) for _n, p, *_ in images]}",
          flush=True)

    to = _recipients(a)
    if to is None:
        return 2
    # Subject carries YESTERDAY — the day the board's numbers are for.
    msg = build_email(images, to, today - dt.timedelta(days=1))

    if a.draft:
        _draft(msg, out_dir, images)
        return 0

    if a.dry_run:
        eml = out_dir / "preview.eml"
        eml.write_bytes(bytes(msg))
        html = out_dir / "preview.html"
        html.write_text(preview_html(msg), encoding="utf-8")
        print(f"[screenshot_email] DRY-RUN — not sent. Recipients would be: {to}\n"
              f"  email written to {eml}\n"
              f"  openable preview  {html}", flush=True)
        print("=== done (dry-run) ===", flush=True)   # Hub success sentinel
        return 0
    send(msg)
    print(f"[screenshot_email] sent to {to}", flush=True)
    _publish_sent()
    print("=== done ===", flush=True)                 # Hub reads this as success
    return 0


_DISTRO_SEED = Path(__file__).resolve().parent / "distro_fallback.json"
_DISTRO_CACHE = (Path(__file__).resolve().parents[2] / "output" / "distro_cache"
                 / "alphalete_org_owners.json")


def _cache_distro(emails: List[str]) -> None:
    """Remember a GOOD expansion. Best-effort — caching must never fail a send."""
    import json
    try:
        _DISTRO_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _DISTRO_CACHE.write_text(json.dumps(
            {"group": DISTRO_GROUPS[0], "as_of": dt.date.today().isoformat(),
             "emails": emails}, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _last_known_distro() -> Tuple[List[str], str]:
    """The newest list we have without the People API: the runtime cache if a
    live expansion has ever succeeded on this machine, else the checked-in seed.
    Returns (emails, 'as-of date · source')."""
    import json
    best: Tuple[List[str], str] = ([], "")
    for path, label in ((_DISTRO_CACHE, "cached from a live expansion"),
                        (_DISTRO_SEED, "checked-in seed")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        emails = [e for e in (d.get("emails") or []) if e]
        if emails and d.get("as_of", "") >= best[1][:10]:
            best = (emails, f"{d.get('as_of', '?')} · {label}")
    return best


def _recipients(a) -> Optional[List[str]]:
    """Resolve the recipient list from the flags. None = refuse to send (the
    caller returns 2) — an under-sent distro is worse than no email."""
    if a.to:
        return [x.strip() for x in a.to.split(",") if x.strip()]
    if a.distro:
        from automations.shared.contacts_auth import expand_groups
        try:
            to, missing = expand_groups(DISTRO_GROUPS)
        except Exception as e:  # noqa: BLE001
            # A DEAD CONTACTS TOKEN MUST NOT SWALLOW THE EMAIL. On 2026-07-31
            # the token came back 'invalid_grant: expired or revoked', this
            # raised, the process died with exit 1, and the gate reported "Could
            # not send" every 15 minutes with an approved board sitting there.
            # Re-authorizing is a browser flow and nobody can sit at the mini, so
            # a Contacts outage would have meant no board email for days.
            # Same call the 6-days-out emails already make: fall back to the last
            # good list and SAY SO — never silently. [[feedback_fill_but_flag]]
            fallback, since = _last_known_distro()
            if not fallback:
                print(f"[screenshot_email] NOT SENT — contacts lookup failed "
                      f"({type(e).__name__}: {str(e).splitlines()[0][:120]}) and "
                      f"there is no cached distro to fall back on.", flush=True)
                return None
            print(f"[screenshot_email] ⚠ CONTACTS LOOKUP FAILED "
                  f"({type(e).__name__}: {str(e).splitlines()[0][:120]}).\n"
                  f"    Falling back to the last known distro: "
                  f"{len(fallback)} address(es), {since}. Anyone added to "
                  f"'{DISTRO_GROUPS[0]}' since then will NOT get this email — "
                  f"re-authorize Contacts (mini_control set_contacts_ro_token).",
                  flush=True)
            return fallback
        if missing:                         # fail loudly — never silently under-send
            print(f"[screenshot_email] NOT SENT — distro group(s) not found: "
                  f"{missing}. Check the names match the contacts groups.", flush=True)
            return None
        if not to:
            print("[screenshot_email] NOT SENT — distro expanded to 0 addresses.",
                  flush=True)
            return None
        print(f"[screenshot_email] distro expanded to {len(to)} address(es)", flush=True)
        _cache_distro(to)
        return to
    return PREVIEW_TO if a.preview else PROVING_TO


def _publish_sent() -> None:
    """Tell the Hub the board email ACTUALLY WENT OUT today — from WHATEVER machine
    sent it. The card used to reflect only the mini's 4am orchestrator run, so a
    morning failure left it red for the rest of the day even after the email had
    been sent by hand from another machine (Megan 2026-07-14: "this should go
    green if it's been sent for that day — not just the morning run"). The Hub
    marks a card run-today off any SUCCESS row on the Hub Activity tab, so
    publishing here makes the card tell the truth: sent = green. Doubly so now
    that the send is a separate review-gate run from the morning build.
    A run under the orchestrator / `lucy rerun` also publishes its own row; a
    second success row is harmless (the Hub looks for ANY success today)."""
    try:
        from automations.day_orchestrator import hub_publish
        hub_publish.publish_done("org_sales_board_email",
                                 "Org. Sales Board Email", status="success")
    except Exception:  # noqa: BLE001 — the Hub must never fail a delivered email
        pass


if __name__ == "__main__":
    sys.exit(main())
