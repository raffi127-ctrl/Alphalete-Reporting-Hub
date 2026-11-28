"""Stitch a bundle's parts into one PDF: one page per part, the part's text
(if it has any beyond a title) drawn above its picture(s)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

_FONTS = ["/System/Library/Fonts/Helvetica.ttc",
          "/System/Library/Fonts/Supplemental/Arial.ttf",
          "/Library/Fonts/Arial.ttf"]
# Emoji and other astral-plane symbols draw as boxes in system fonts.
_ASTRAL = re.compile("[\U00010000-\U0010FFFF☀-➿️‍]")


def _font(size: int, bold: bool = False):
    for path in _FONTS:
        try:
            return ImageFont.truetype(path, size, index=1 if (bold and path.endswith(".ttc")) else 0)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def clean(text: str) -> str:
    return _ASTRAL.sub("", text or "").replace("\r", "")


def _wrap(draw, text: str, font, width: int) -> List[str]:
    out = []
    for para in clean(text).split("\n"):
        words, line = para.split(" "), ""
        for w in words:
            trial = (line + " " + w).strip()
            if draw.textlength(trial, font=font) <= width or not line:
                line = trial
            else:
                out.append(line)
                line = w
        out.append(line)
    return out


def text_block(text: str, width: int, heading: Optional[str] = None) -> Image.Image:
    size = max(18, width // 45)
    font, bold = _font(size), _font(int(size * 1.25), bold=True)
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    pad = size
    lines = _wrap(probe, text, font, width - 2 * pad) if text else []
    line_h = int(size * 1.4)
    head_h = int(size * 1.25 * 1.6) if heading else 0
    h = pad + head_h + line_h * len(lines) + pad
    im = Image.new("RGB", (width, h), "white")
    dr = ImageDraw.Draw(im)
    y = pad
    if heading:
        dr.text((pad, y), clean(heading), font=bold, fill=(20, 20, 20))
        y += head_h
    for ln in lines:
        dr.text((pad, y), ln, font=font, fill=(30, 30, 30))
        y += line_h
    return im


def page(heading: str, text: str, images: Sequence) -> Image.Image:
    pics = [Image.open(p).convert("RGB") for p in images]
    width = max([p.width for p in pics] + [1200])
    blocks = [text_block(text, width, heading=heading)]
    for p in pics:
        if p.width != width:                          # centre narrower pictures
            canvas = Image.new("RGB", (width, p.height), "white")
            canvas.paste(p, ((width - p.width) // 2, 0))
            p = canvas
        blocks.append(p)
    h = sum(b.height for b in blocks)
    out = Image.new("RGB", (width, h), "white")
    y = 0
    for b in blocks:
        out.paste(b, (0, y))
        y += b.height
    return out


def build(pages: Sequence[Tuple[str, str, Sequence]], out: Path) -> Path:
    """pages = [(heading, text, [image paths])] -> one PDF."""
    ims = [page(h, t, imgs) for h, t, imgs in pages]
    if not ims:
        raise ValueError("no pages")
    out.parent.mkdir(parents=True, exist_ok=True)
    ims[0].save(out, "PDF", resolution=150.0, save_all=True, append_images=ims[1:])
    return out
