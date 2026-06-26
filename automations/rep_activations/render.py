"""Render the two weekly Rep Activation tables as a single PNG.

Two tables side by side (mirrors the mockup) — "Last Week" and "This Week",
each with columns: Rep Name | Posted | Pending | Total | Canceled/Disconnected.
Rows are tinted by **Total** (Megan's bands):

    green  Total >= 11
    cyan   Total 7-10
    yellow Total 4-6
    gray   Total 1-3
    red    Total 0

PIL ImageDraw with 2x supersampling + LANCZOS downscale for crisp text, and a
cross-platform font lookup (Windows + macOS + Linux) — no hard-coded Mac paths.
Pattern follows automations/total_knocks/render.py.

Standalone smoke test (no Tableau pull, writes a demo PNG to output/):
    python -m automations.rep_activations.render --demo
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 2x supersample: draw big, downscale once at the end.
S = 2

# Logical (pre-scale) sizes.
TITLE_H = 28
HEADER_H = 24
ROW_H = 22
PAD = 14
GAP = 30          # horizontal space between the two tables
CELL_PAD = 7
MIN_REP_W = 150
NUM_W = 62

# Display columns: (header, row-key, alignment).
COLS = [
    ("Rep Name", "rep", "left"),
    ("Posted", "posted", "center"),
    ("Pending", "pending", "center"),
    ("Total", "total", "center"),
    ("Canceled/Disconnected", "canceled", "center"),
]

# (min Total inclusive, RGB fill) — first match wins, checked high -> low.
BANDS = [
    (11, (169, 208, 142)),   # green  #A9D08E
    (7,  (159, 227, 240)),   # cyan   #9FE3F0
    (4,  (255, 229, 153)),   # yellow #FFE599
    (1,  (217, 217, 217)),   # gray   #D9D9D9
    (0,  (234, 153, 153)),   # red    #EA9999
]
HEADER_BG = (242, 242, 242)
GRID = (0, 0, 0)
TEXT = (0, 0, 0)
WHITE = (255, 255, 255)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\segoeuib.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        if bold else
        [r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf",
         "/System/Library/Fonts/Supplemental/Arial.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _band(total: int):
    for threshold, color in BANDS:
        if total >= threshold:
            return color
    return BANDS[-1][1]


def _cell(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, text: str,
          font, align: str, fill_bg, fg=TEXT) -> None:
    if fill_bg is not None:
        d.rectangle([x, y, x + w, y + h], fill=fill_bg)
    d.rectangle([x, y, x + w, y + h], outline=GRID, width=S)
    tw = int(d.textlength(text, font=font))
    asc, desc = font.getmetrics()
    ty = y + (h - (asc + desc)) // 2
    if align == "left":
        tx = x + CELL_PAD * S
    elif align == "right":
        tx = x + w - CELL_PAD * S - tw
    else:
        tx = x + (w - tw) // 2
    d.text((tx, ty), text, font=font, fill=fg)


def _build_table(title: str, table: dict, fonts) -> Image.Image:
    f_title, f_head, f_cell, f_rep = fonts
    rows = table["rows"]

    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    rep_w = max(MIN_REP_W * S,
                int(probe.textlength("Rep Name", font=f_head)) + 2 * CELL_PAD * S)
    for r in rows:
        rep_w = max(rep_w,
                    int(probe.textlength(r["rep"], font=f_rep)) + 2 * CELL_PAD * S)

    col_w = [rep_w]
    for header, _key, _align in COLS[1:]:
        col_w.append(max(NUM_W * S,
                         int(probe.textlength(header, font=f_head)) + 2 * CELL_PAD * S))
    table_w = sum(col_w)

    title_h, header_h, row_h = TITLE_H * S, HEADER_H * S, ROW_H * S
    img_h = title_h + header_h + row_h * max(len(rows), 1)
    img = Image.new("RGB", (table_w, img_h), WHITE)
    d = ImageDraw.Draw(img)

    # Centered title (no border — matches the mockup's caption above the grid).
    tw = int(d.textlength(title, font=f_title))
    asc, desc = f_title.getmetrics()
    d.text(((table_w - tw) // 2, (title_h - (asc + desc)) // 2), title,
           font=f_title, fill=TEXT)

    # Header row.
    y, x = title_h, 0
    for (header, key, _align), w in zip(COLS, col_w):
        _cell(d, x, y, w, header_h, header, f_head,
              "left" if key == "rep" else "center", HEADER_BG)
        x += w

    # Data rows.
    y += header_h
    if not rows:
        _cell(d, 0, y, table_w, row_h, "No data", f_cell, "left", WHITE)
    for r in rows:
        band = _band(r["total"])
        x = 0
        for (_header, key, _align), w in zip(COLS, col_w):
            val = str(r[key])
            if key == "rep":
                _cell(d, x, y, w, row_h, val, f_rep, "left", band)
            else:
                _cell(d, x, y, w, row_h, val, f_cell, "center", band)
            x += w
        y += row_h

    return img


def render(summary: dict, out_path) -> Path:
    """Compose the two tables into one PNG and write it to ``out_path``."""
    fonts = (_font(16 * S, bold=True), _font(12 * S, bold=True),
             _font(12 * S), _font(12 * S, bold=True))

    left = _build_table(f"Last Week: {summary['last']['label']}",
                        summary["last"], fonts)
    right = _build_table(f"This Week: {summary['this']['label']}",
                         summary["this"], fonts)

    canvas_w = PAD * S + left.width + GAP * S + right.width + PAD * S
    canvas_h = PAD * S + max(left.height, right.height) + PAD * S
    canvas = Image.new("RGB", (canvas_w, canvas_h), WHITE)
    canvas.paste(left, (PAD * S, PAD * S))
    canvas.paste(right, (PAD * S + left.width + GAP * S, PAD * S))

    final = canvas.resize((canvas_w // S, canvas_h // S), Image.LANCZOS)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    final.save(out_path)
    return out_path


def _demo() -> Path:
    """Render a fake summary so the layout/colors can be eyeballed offline."""
    def mk(seed):
        rows = [{"rep": n, "posted": p, "pending": pe,
                 "total": p + pe, "canceled": c}
                for n, p, pe, c in seed]
        rows.sort(key=lambda r: (-r["total"], r["rep"].lower()))
        return {"label": "6.14 - 6.20", "rows": rows}

    last = mk([("Santana Gradney", 12, 21, 0), ("Travis Smith", 1, 20, 0),
               ("Cyrus Wade", 5, 5, 1), ("Amarion Hill", 4, 2, 0),
               ("Juana Mendoza", 1, 1, 0), ("Mario Oviedo", 0, 0, 0)])
    this = mk([("Santana Gradney", 11, 21, 0), ("Travis Smith", 2, 20, 0),
               ("Cyrus Wade", 1, 5, 1), ("Amarion Hill", 0, 2, 0),
               ("Juana Mendoza", 0, 1, 0), ("Mario Oviedo", 0, 0, 0)])
    this["label"] = "6.21 - 6.27"
    return render({"last": last, "this": this},
                  Path("output") / "rep_activations_demo.png")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true",
                    help="render a fake-data PNG to output/ (no Tableau pull)")
    args = ap.parse_args()
    if args.demo:
        print(f"[rep_activations.render] wrote {_demo()}")
    else:
        ap.error("nothing to do — pass --demo for an offline smoke test")
