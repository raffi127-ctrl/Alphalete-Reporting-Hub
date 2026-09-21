"""The picture for the two-week board (Eve 2026-09-18, Rafael 2026-09-21).

What each pass sends, top to bottom:

    RETENTION: FIRST SHOWED UP → BOOKED SECOND     <- what the numbers are
    Eastern offices · 11:00 AM local update · ...   <- whose, and when
    (Mondays only)
    LAST WEEK · MON 9/14 – SAT 9/19 · FINAL         <- the whole week just closed
    <header rows 3-4>  <Monday .. Saturday>
    THIS WEEK · MON 9/21 – MON 9/21 (TODAY)         <- the week so far
    <header rows 3-4>  <Monday .. today>

Rafael (2026-09-21): the numbers of earlier days keep moving -- by Monday 11 AM
Friday's callbacks are in -- so every picture carries the whole week so far,
not just today, and Monday's carries the whole week that just ended.

Rendered from the tab itself (Sheets PDF export, the exact sheet look): a header
and a body range per week, stitched into one PNG under drawn caption bands. The
tab is normally the pass's own picture tab (only that pass's offices), or the
full board for a pass that covered everybody.

    python -m automations.first_to_second_below_mark.board_shot
    python -m automations.first_to_second_below_mark.board_shot --tab "1st to 2nd below the mark"
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.recruiting_report import fill
from automations.first_to_second_below_mark import ars_reports as ars
from automations.first_to_second_below_mark import board as b
from automations.first_to_second_below_mark import run as rep

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "below_the_mark"

# The caption bands drawn over each table. Deliberately colours the report uses
# NOWHERE else (Eve, 2026-09-18): the first try reused the day-band grey and the
# alert red, and the captions blended into the tables under them.
CAPTION_BG = (21, 101, 192)         # last week: strong blue   #1565C0
CAPTION_FG = (255, 255, 255)
TODAY_BG = (216, 27, 96)            # this week: fuchsia       #D81B60
TITLE_BG = (33, 33, 33)             # the report's name        #212121
SUBTITLE_BG = (238, 238, 238)
SUBTITLE_FG = (33, 33, 33)


def find_day(values: List[List], day: str, c0: int) -> Optional[Tuple[int, int, str]]:
    """(band row, last office row, band text) of one day in one week's block.

    The day ends at the next band or the end of the tab, then shrinks back to
    the last row that names an office, so the shorter week does not drag the
    other one's filler rows into its picture."""
    want = day.upper()
    band = None
    for i, row in enumerate(values[b.FIRST_BODY_ROW - 1:], b.FIRST_BODY_ROW):
        cell = str(row[c0]) if len(row) > c0 else ""
        head = cell.split(" ", 1)[0]
        if band is None:
            if head == want:
                band = (i, cell)
            continue
        if head.isupper() and head.title() in b.WEEK_DAYS:
            end = i - 1
            break
    else:
        end = len(values)
    if band is None:
        return None
    last = band[0]
    for r in range(band[0] + 1, end + 1):
        row = values[r - 1] if r - 1 < len(values) else []
        if len(row) > c0 and str(row[c0]).strip():
            last = r
    return band[0], last, band[1]


def block_start(values: List[List]) -> Optional[int]:
    """0-indexed column where the second week begins: its 'Owner Name' header.

    Looked for on rows 3 AND 4, because in the columns with no group banner the
    two rows are one merged box and the header sits on row 3 (Eve, 2026-09-18)."""
    want = rep.OWNER_HEADER.lower()
    for r in (b.BANNER_ROW, b.HEADER_ROW):
        row = values[r - 1] if len(values) >= r else []
        hits = [i for i, h in enumerate(row) if rep._norm(str(h)).lower() == want]
        if len(hits) >= 2:
            return hits[1]
    return None


def shown_day(today: dt.date) -> str:
    """The last day this week's part of the picture runs to."""
    return b.WEEK_DAYS[min(today.weekday(), len(b.WEEK_DAYS) - 1)]


def _date_of(band_text: str) -> str:
    """'MONDAY 9/21 (today, still moving)  ·  ...' -> 'MON 9/21'."""
    head = band_text.split("  ·  ", 1)[0].replace("(today, still moving)", "").split()
    return f"{head[0][:3]} {head[1]}" if len(head) > 1 else band_text


def _count(band_text: str) -> str:
    parts = band_text.split("  ·  ")
    return "  ·  ".join(parts[1:]) if len(parts) > 1 else band_text



def subtitle(status: str) -> str:
    """'Eastern offices  ·  11:00 AM local update  ·  offices at or under 40%  ·
    checked Mon 9/21 10:00 CT' out of the tab's status row (row 2)."""
    m = re.search(r"checked (\w{3} \d{1,2}/\d{1,2} \d{1,2}:\d{2}) CT", status or "")
    scope = re.split(r"\s+·\s+(?:offices at or under|every office)", status or "", maxsplit=1)[0]
    if not scope or scope.startswith(("offices at or under", "every office")):
        scope = "All offices"
    what = ("every office" if "every office" in (status or "").lower()
            else f"offices at or under {rep.THRESHOLD:.0%}")
    return "  ·  ".join(p for p in (scope.strip(), what,
                                     f"checked {m.group(1)} CT" if m else "") if p)


def plan(values: List[List], today: dt.date) -> List[dict]:
    """The week blocks of the picture, top to bottom.

    Monday: last week whole (Mon-Sat, final), then this week's Monday. Any
    other day: this week, Monday to today."""
    right = block_start(values)
    if right is None:
        raise SystemExit("cannot find the second week's 'Owner Name' header")
    width = right - b.GAP_COLS
    last_day = shown_day(today)
    blocks = []
    wanted = [(0, "THIS WEEK", b.WEEK_DAYS[:b.WEEK_DAYS.index(last_day) + 1], TODAY_BG)]
    if today.weekday() == 0:
        wanted.insert(0, (right, "LAST WEEK", list(b.WEEK_DAYS), CAPTION_BG))
    for c0, label, days, bg in wanted:
        hits = [(d, find_day(values, d, c0)) for d in days]
        missing = [d for d, h in hits if h is None]
        if missing:
            raise SystemExit(f"no {', '.join(missing)} band in the {label.lower()} block")
        first_row, last_row = hits[0][1][0], hits[-1][1][1]
        first_col, last_col = ars.a1col(c0 + 1), ars.a1col(c0 + width)
        span = f"{_date_of(hits[0][1][2])} – {_date_of(hits[-1][1][2])}"
        if label == "LAST WEEK":
            span += "  ·  FINAL"
        elif hits[-1][1][2].split("  ·  ")[0].endswith("(today, still moving)"):
            span += " (TODAY)"
        blocks.append({
            "caption": f"{label}  ·  {span}", "bg": bg,
            "header": f"{first_col}{b.BANNER_ROW}:{last_col}{b.HEADER_ROW}",
            "body": f"{first_col}{first_row}:{last_col}{last_row}",
            "days": [(d, h[2]) for d, h in hits]})
    return blocks


def comment_for(blocks: List[dict], sub: str) -> str:
    """The Slack text: ONE line saying whose wave it is. Everything else is in
    the picture -- a per-day summary under it read as clutter, since everyone
    opens the image anyway (Eve, 2026-09-21)."""
    scope = re.split(r"\s+·\s+(?:offices at or under|every office)", sub, maxsplit=1)[0]
    return f"*1st to 2nd Below the Mark* — {scope.strip()}"


def _font(size: int):
    from PIL import ImageFont
    for name in ("arialbd.ttf", "Arial Bold.ttf",
                 "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                 "C:/Windows/Fonts/arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                                   # Pillow < 10.1
        return ImageFont.load_default()


# Band height and text size, in pixels of the ~4400px-wide picture. Raised from
# 84 / half-height after the first sample: on a phone the day did not read at a
# glance (Eve, 2026-09-18).
CAPTION_PX = 150
CAPTION_TEXT = 0.6          # share of the band's height the letters take
TITLE_PX = 190
SUBTITLE_PX = 110


def caption(text: str, width: int, bg=CAPTION_BG, height: int = CAPTION_PX,
            fg=CAPTION_FG):
    """A full-width band with the text written large, as a PIL image."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (width, height), bg)
    d = ImageDraw.Draw(im)
    f = _font(int(height * CAPTION_TEXT))
    box = d.textbbox((0, 0), text, font=f)
    d.text((40, (height - (box[3] - box[1])) // 2 - box[1]), text, font=f, fill=fg)
    return im


def build_png(tab: str = b.PICTURE_TAB, today: Optional[dt.date] = None,
              out: Optional[Path] = None, logfn=print) -> Tuple[Path, str]:
    """(png path, Slack comment) for the tab as the last pass left it."""
    from PIL import Image
    from automations.org_sales_board.screenshot_email import _export_png, _access_token

    today = today or dt.datetime.now(dt.timezone.utc).astimezone(rep.CT).date()
    sh = fill.open_by_key(rep.SHEET_ID)
    ws = fill.worksheet_ci(sh, tab)
    values = ws.get("A1:AZ400")
    status = str(values[b.STATUS_ROW - 1][0]) if len(values) >= b.STATUS_ROW and values[b.STATUS_ROW - 1] else ""
    sub = subtitle(status)
    blocks = plan(values, today)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    token = _access_token()
    images = []
    for k, blk in enumerate(blocks):
        hp = OUT_DIR / f"board_{k}_hdr.png"
        bp = OUT_DIR / f"board_{k}_body.png"
        # The export endpoint drops a connection now and then (SSL EOF,
        # 2026-09-21); one picture has up to four exports, so retry each.
        for rng, path in ((blk["header"], hp), (blk["body"], bp)):
            b._with_network_retry(
                lambda: _export_png(ws.id, rng, path, token, spreadsheet_id=rep.SHEET_ID),
                logfn=logfn, what=f"export {rng}", wait=5.0)
        images.append((blk, Image.open(hp).convert("RGB"), Image.open(bp).convert("RGB")))
        logfn(f"  {blk['caption']}: {blk['header']} + {blk['body']}")

    w = max(max(h.width, bd.width) for _, h, bd in images)
    gap = 60
    parts = [caption(b.REPORT_TITLE, w, TITLE_BG, TITLE_PX),
             caption(sub, w, SUBTITLE_BG, SUBTITLE_PX, fg=SUBTITLE_FG),
             Image.new("RGB", (w, gap), (255, 255, 255))]
    for i, (blk, hdr, body) in enumerate(images):
        parts.append(caption(blk["caption"], w, blk["bg"]))
        parts += [hdr, body]
        if i < len(images) - 1:
            parts.append(Image.new("RGB", (w, gap), (255, 255, 255)))
    canvas = Image.new("RGB", (w, sum(p.height for p in parts)), (255, 255, 255))
    y = 0
    for p in parts:
        canvas.paste(p, (0, y))
        y += p.height
    out = out or (OUT_DIR / "below_the_mark_board.png")
    canvas.save(out)
    return out, comment_for(blocks, sub)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="first_to_second_below_mark.board_shot")
    ap.add_argument("--tab", default=b.PICTURE_TAB)
    ap.add_argument("--today", default=None, help="YYYY-MM-DD, to see another day's cut")
    args = ap.parse_args(argv)
    today = dt.date.fromisoformat(args.today) if args.today else None
    png, comment = build_png(tab=args.tab, today=today)
    print(f"{png}\n{comment}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
