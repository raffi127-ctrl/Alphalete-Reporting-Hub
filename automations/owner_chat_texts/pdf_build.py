"""Bundle the day's tracker PNGs into ONE PDF — one tracker per page.

Raf 2026-08-23 (#l10-alphalete thread): "Can we make the owners post a PDF so
it's not a bunch of messages going out at once." So the 7:30 pass sends a
single captioned PDF instead of nine caption+image pairs.

Pages keep the channel's post order. The PDF is built from the exact PNGs the
Slack channel got, so the owners see the same boards everyone else does.

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import List, Tuple


def build(found: List[Tuple[dict, Path]], out_dir: Path, day: dt.date) -> Path:
    """One PDF, one page per tracker, in the given order. Raises on empty —
    an empty PDF post reads as a broken send. [[feedback_never_post_blank]]"""
    # PyMuPDF, not PIL: PIL's PDF writer re-encodes pages through its JPEG
    # codec, which not every Pillow build carries (Megan's laptop lacks it).
    # fitz embeds the PNGs losslessly and is already a hard dependency of the
    # board render (screenshot_email._export_png), so it exists wherever this
    # report can run at all.
    import fitz
    if not found:
        raise ValueError("no tracker images to bundle")
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = out_dir / ("country_trackers_%s.pdf" % day.isoformat())
    doc = fitz.open()
    # EVERY page gets the SAME width (Raf 8/23: "PDF is pretty zoomed out").
    # PDF viewers pick one zoom for the whole document and fit the WIDEST
    # page, so sizing pages to their raw pixels let the Verizon board (3728px
    # vs ~1600 for the rest) shrink every other board to ~40% of the screen.
    # One shared width = every page fills the screen; heights scale per board.
    PAGE_W = 800.0
    for _spec, p in found:
        pix = fitz.Pixmap(str(p))
        page = doc.new_page(width=PAGE_W,
                            height=PAGE_W * pix.height / pix.width)
        page.insert_image(page.rect, pixmap=pix)
        pix = None
    doc.save(str(pdf), deflate=True)
    doc.close()
    return pdf
