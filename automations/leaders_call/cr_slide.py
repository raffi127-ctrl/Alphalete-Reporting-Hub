"""Alphalete Leader's Call — the Costa Rica 2027 "save the date" slide.

Maud, 2026-11-19 (Raf's ask): "add something in there every week that
mentions Costa Rica please to start promoting the next trip! The dates are
May 18-21." Runs in every week's deck until the trip ends (CR_THROUGH in
build_pdf), right before the #top-leaders chat slide, which stays LAST.

A REAL photo, full-bleed (Eve 2026-11-19: the drawn sunset looked cheap):
resources/costa-rica-beach.jpg = Wikimedia Commons "Playa (261863895).jpeg"
(aerial, Guanacaste), CC0 (public domain, no credit needed). Eve picked it
over a sunset and a resort shot: a public beach, daytime, so nobody reads it
as "this is the hotel we're going to". Swap the file to change
the picture; it is cover-cropped to 16:9, so any landscape photo works.

The one qualification (Maud, 2026-11-19): "they need to be an owner by
then". Trip details live in CR below — edit there, nowhere else.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Flowable

from automations.leaders_call import rr_slide as rr

PAGE_W, PAGE_H = rr.PAGE_W, rr.PAGE_H
PHOTO = Path(__file__).resolve().parents[2] / "resources" / "costa-rica-beach.jpg"
# Required for CC BY photos; empty for CC0. Small, bottom-right, above the footer.
PHOTO_CREDIT = ""

CR = {
    "kicker": "S A V E   T H E   D A T E",
    "title": "NEXT TRIP",
    "place": "Costa Rica",
    "tagline": "pura vida",
    "dates": "MAY 18 – 21, 2027",
    "badge": ["OWNERS", "ONLY", "TRIP"],
    "note_1": "Qualification: be an OWNER by May 18, 2027.",
    "note_2": "Start building your office now!",
}

CX = PAGE_W / 2
WHITE = colors.HexColor("#FFFFFF")
GOLD = colors.HexColor("#FFD27A")
SHADOW = colors.Color(0, 0, 0, 0.55)


def _photo_cover(c):
    """The photo cropped to fill the page (CSS 'cover'), with the top and
    bottom darkened so white text reads; the middle (sun on the water) stays
    bright. The darkening is baked into the pixels with Pillow: stacked
    semi-transparent strips in the PDF show as visible banding."""
    from PIL import Image
    im = Image.open(PHOTO).convert("RGB")
    iw, ih = im.size
    target = PAGE_W / PAGE_H
    if iw / ih > target:                         # too wide → trim the sides
        nw = int(ih * target)
        im = im.crop(((iw - nw) // 2, 0, (iw - nw) // 2 + nw, ih))
    else:                                        # too tall → trim top/bottom
        nh = int(iw / target)
        im = im.crop((0, (ih - nh) // 2, iw, (ih - nh) // 2 + nh))
    w, h = im.size
    mask = Image.new("L", (1, h))
    for y in range(h):
        f = 1 - y / (h - 1.0)                    # 0 = bottom, 1 = top
        a = max(0.55 * (1 - f / 0.40), 0.0) + max(0.45 * (f - 0.50) / 0.50, 0.0)
        mask.putpixel((0, y), int(255 * min(a, 0.55)))
    im = Image.composite(Image.new("RGB", (w, h)), im, mask.resize((w, h)))
    c.drawImage(ImageReader(im), 0, 0, width=PAGE_W, height=PAGE_H)


def draw_cr(c, week_label=""):
    c.saveState()
    _photo_cover(c)

    rr._shadow_text(c, CX, 6.70 * inch, CR["kicker"], "Helvetica-Bold", 17,
                    GOLD, SHADOW, dx=1.2, dy=1.2)
    rr._shadow_text(c, CX, 6.02 * inch, CR["title"], "Helvetica-Bold", 46,
                    WHITE, SHADOW, dx=2.5, dy=2.5, tracking=6)
    rr._shadow_text(c, CX, 4.78 * inch, CR["place"], "Times-Bold", 104,
                    WHITE, SHADOW, dx=3.5, dy=3.5)
    rr._shadow_text(c, CX, 4.22 * inch, CR["tagline"], "Times-BoldItalic", 30,
                    GOLD, colors.Color(0, 0, 0, 0.8), dx=1.6, dy=1.6)

    rr._shadow_text(c, CX, 1.92 * inch, CR["dates"], "Helvetica-Bold", 40,
                    WHITE, SHADOW, dx=2, dy=2, tracking=2)
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.4)
    c.line(CX - 2.3 * inch, 1.66 * inch, CX + 2.3 * inch, 1.66 * inch)
    rr._shadow_text(c, CX, 1.20 * inch, CR["note_1"], "Helvetica-Bold", 20,
                    WHITE, SHADOW, dx=1.2, dy=1.2)
    rr._shadow_text(c, CX, 0.78 * inch, CR["note_2"], "Helvetica-Bold", 22,
                    GOLD, SHADOW, dx=1.2, dy=1.2)

    rr._badge(c, PAGE_W - 1.45 * inch, 6.15 * inch, 0.80 * inch, CR["badge"])
    if PHOTO_CREDIT:
        c.setFillColor(colors.Color(1, 1, 1, 0.7))
        c.setFont("Helvetica", 7.5)
        c.drawRightString(PAGE_W - 0.25 * inch, rr.FOOTER_H + 0.08 * inch, PHOTO_CREDIT)
    c.restoreState()
    rr._footer(c, week_label)


class CRSlide(Flowable):
    """Full-bleed page: paints over the deck's near-black ground (see rr_slide)."""

    def __init__(self, week_label=""):
        super().__init__()
        self.week_label = week_label

    def wrap(self, avail_w, avail_h):
        self.width, self.height = avail_w, avail_h
        return avail_w, avail_h

    def draw(self):
        c = self.canv
        c.saveState()
        x, y = c.absolutePosition(0, 0)
        c.translate(-x, -y)
        draw_cr(c, self.week_label)
        c.restoreState()
