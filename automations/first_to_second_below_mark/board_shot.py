"""The DM picture for the two-week board (Eve, 2026-09-18).

Two tables, one ABOVE the other, each under a band that says which day it is so
nobody mistakes one for the other:

    LAST WEEK · FRIDAY 9/11        <- the same weekday, a week ago
    <header rows 3-4 of the right-hand week>
    <that day's band and offices>

    THIS WEEK · FRIDAY 9/18 (TODAY)
    <header rows 3-4 of the left-hand week>
    <today's band and offices>

Rendered from the PREVIEW tab itself (Sheets PDF export, the exact sheet look),
four ranges -- a header and a day for each week -- stitched into one PNG. Only
the rows of that day are taken, so the picture stays short however long the
rest of the week is.

    python -m automations.first_to_second_below_mark.board_shot            # today
    python -m automations.first_to_second_below_mark.board_shot --day Tuesday
"""
from __future__ import annotations

import argparse
import datetime as dt
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
        if head.isupper() and head.title() in ars.DAYS:
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


def caption(text: str, width: int, bg=CAPTION_BG, height: int = 84):
    """A full-width dark band with the day written large, as a PIL image."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (width, height), bg)
    d = ImageDraw.Draw(im)
    f = _font(int(height * 0.5))
    box = d.textbbox((0, 0), text, font=f)
    d.text((24, (height - (box[3] - box[1])) // 2 - box[1]), text, font=f, fill=CAPTION_FG)
    return im


def build_png(day: Optional[str] = None, tab: str = b.BOARD_TAB,
              out: Optional[Path] = None, logfn=print) -> Tuple[Path, str]:
    """(png path, Slack comment) for one day: last week's on top, this week's below."""
    from PIL import Image
    from automations.org_sales_board.screenshot_email import _export_png, _access_token

    day = day or rep.default_day()
    sh = fill.open_by_key(rep.SHEET_ID)
    ws = fill.worksheet_ci(sh, tab)
    values = ws.get("A1:AZ400")
    right = block_start(values)
    if right is None:
        raise SystemExit(f"{tab!r}: cannot find the second week's 'Owner Name' header")
    width = right - b.GAP_COLS
    last_col_l, last_col_r = ars.a1col(width), ars.a1col(right + width)

    pieces = []                        # (caption text, caption bg, header rng, body rng, band)
    for c0, first, last_col, label in ((right, ars.a1col(right + 1), last_col_r, "LAST WEEK"),
                                       (0, "A", last_col_l, "THIS WEEK")):
        hit = find_day(values, day, c0)
        if hit is None:
            raise SystemExit(f"{tab!r}: no {day.upper()} band in the {label.lower()} block")
        band_row, last_row, band_text = hit
        date = band_text.split("  ·  ", 1)[0].replace("(today, still moving)", "(today)")
        pieces.append((f"{label}  ·  {date}", TODAY_BG if c0 == 0 else CAPTION_BG,
                       f"{first}{b.BANNER_ROW}:{last_col}{b.HEADER_ROW}",
                       f"{first}{band_row}:{last_col}{last_row}", band_text))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    token = _access_token()
    blocks = []
    for k, (cap, bg, hdr, body, _) in enumerate(pieces):
        hp = OUT_DIR / f"board_{k}_hdr.png"
        bp = OUT_DIR / f"board_{k}_body.png"
        _export_png(ws.id, hdr, hp, token, spreadsheet_id=rep.SHEET_ID)
        _export_png(ws.id, body, bp, token, spreadsheet_id=rep.SHEET_ID)
        blocks.append((cap, bg, Image.open(hp).convert("RGB"), Image.open(bp).convert("RGB")))
        logfn(f"  {cap}: {hdr} + {body}")

    w = max(max(h.width, bd.width) for _, _, h, bd in blocks)
    gap = 60
    parts = []
    for i, (cap, bg, hdr, body) in enumerate(blocks):
        parts.append(caption(cap, w, bg))
        parts += [hdr, body]
        if i < len(blocks) - 1:
            parts.append(Image.new("RGB", (w, gap), (255, 255, 255)))
    canvas = Image.new("RGB", (w, sum(p.height for p in parts)), (255, 255, 255))
    y = 0
    for p in parts:
        canvas.paste(p, (0, y))
        y += p.height
    out = out or (OUT_DIR / "below_the_mark_board.png")
    canvas.save(out)

    # The comment carries the two counts so the message reads without opening it.
    def count(text):
        return text.split("  ·  ", 1)[1] if "  ·  " in text else text
    def when(cap):
        return cap.split("·")[-1].replace("(today)", "").strip().title()
    comment = (f"*1st to 2nd Below the Mark* — {day}\n"
               f"• Last week, {when(pieces[0][0])}: {count(pieces[0][4])}\n"
               f"• Today, {when(pieces[1][0])}: {count(pieces[1][4])}")
    return out, comment


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="first_to_second_below_mark.board_shot")
    ap.add_argument("--day", default=None, choices=ars.DAYS + [d.lower() for d in ars.DAYS])
    ap.add_argument("--tab", default=b.BOARD_TAB)
    args = ap.parse_args(argv)
    png, comment = build_png(day=args.day.title() if args.day else None, tab=args.tab)
    print(f"{png}\n{comment}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
