"""Alphalete Leader's Call — the "join the chat" promo slide.

Raf, #l10-alphalete 2026-09-28: "To the leadership flyer, can we add this
screenshot on there every week just so that we can promote this chat weekly?
... The chat itself is what I'm trying to promote." The chat is the Slack
channel #top-leaders-alphalete-org (private, ~120 members): daily wins, the
Org Sales Board every morning, book club. This slide runs in EVERY week's deck
as the LAST slide (Megan 2026-09-28), after the R&R closer while that lasts.

The picture is Raf's own phone screenshot of the channel (his IMG_2209,
2026-09-28), cropped to the chat — status bar, message box and nav bar cut —
and saved as resources/top-leaders-chat-phone.png. It is a FIXED image on
purpose (that is what he asked for); swap the file to refresh it, nothing
else changes. A missing file must never cost the deck: build_pdf wraps this
slide in the same fail-soft try as the R&R one.

Drawn inside the frame on the deck's normal near-black page (ground + footer
come from onLaterPages), so unlike rr_slide there is nothing to repaint.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Flowable

_RES = Path(__file__).resolve().parents[2] / "resources"
PHONE = _RES / "top-leaders-chat-phone.png"

PAGE_W, PAGE_H = 13.333 * inch, 7.5 * inch
MARGIN = 0.6 * inch

CHANNEL = "#top-leaders-alphalete-org"
KICKER = "J O I N   U S   O N   S L A C K"
TITLE = "Where the org's top leaders hang out"
LINES = [
    "Big wins from every office, the moment they land.",
    "The Org Sales Board, fresh every morning.",
    "Book club, new trucks, and all the hype in between.",
]
# It is a PRIVATE channel (C067TTGFEFR, Megan's About panel 2026-09-28), so
# nobody can search-and-join. Raf, same day: "Owner adds them" — no
# qualification, your office owner puts you in. The card says exactly that.
CTA_1 = "New leaders:"
CTA_2 = "Ask your owner for an invite!"
CTA_3 = ""

# Same palette as build_pdf — typed here so this module imports standalone.
RED = colors.HexColor("#CC3340")
GOLD = colors.HexColor("#C8A24A")
GOLD_HI = colors.HexColor("#E4CE93")
WHITE = colors.HexColor("#F3F6FC")
ICD = colors.HexColor("#C9CBD2")
MUTED = colors.HexColor("#9A9AA6")
CARD = colors.HexColor("#1C1C22")
CARD_STROKE = colors.HexColor("#3C3C46")

# Slack's four brand colours (the mark: blue, green, red, yellow).
SLACK = {"blue": "#36C5F0", "green": "#2EB67D", "red": "#E01E5A", "yellow": "#ECB22E"}


def draw_slack_mark(c, x, y, size):
    """The Slack logo mark, drawn as vectors so it projects crisp at any size
    (Megan 2026-09-28: make sure they know it's a Slack channel). Geometry is
    the official mark's 127x127 box: four pills, each with a dot whose corner
    nearest the pill is squared off. (x, y) = bottom-left, `size` = the box."""
    k = size / 127.0
    r = 13.2 * k                              # pill half-width / dot radius
    def X(v): return x + v * k
    def Y(v): return y + (127 - v) * k       # the SVG's y runs downward
    def pill(col, x0, y0, x1, y1):            # svg coords, y downward
        c.setFillColor(colors.HexColor(col))
        c.roundRect(X(x0), Y(y1), (x1 - x0) * k, (y1 - y0) * k, r, fill=1, stroke=0)
    def dot(col, cx, cy, qx, qy):             # centre + which quadrant is square
        c.setFillColor(colors.HexColor(col))
        c.circle(X(cx), Y(cy), r, fill=1, stroke=0)
        sx = X(cx) if qx > 0 else X(cx) - r
        sy = Y(cy) if qy < 0 else Y(cy) - r   # qy<0 = towards the svg TOP
        c.rect(sx, sy, r, r, fill=1, stroke=0)
    c.saveState()
    pill(SLACK["blue"],   33.8, 66.8, 60.2, 126.4);  dot(SLACK["blue"],   14.0, 80.0, +1, +1)
    pill(SLACK["green"],   0.8, 33.8, 60.2,  60.2);  dot(SLACK["green"],  47.0, 14.0, +1, +1)
    pill(SLACK["red"],    66.9,  0.8, 93.3,  60.2);  dot(SLACK["red"],   113.1, 47.0, -1, -1)
    pill(SLACK["yellow"], 66.9, 66.9, 126.3, 93.3);  dot(SLACK["yellow"], 80.1, 113.1, -1, -1)
    c.restoreState()


def draw_chat(c):
    """Phone screenshot on the right, the pitch on the left. Page coords."""
    top = PAGE_H - 0.75 * inch
    bottom = 0.85 * inch                       # clear of the deck footer rule

    # ---- phone (right): fill the height, keep the aspect, thin gold frame
    img = ImageReader(str(PHONE))
    iw, ih = img.getSize()
    ph = top - bottom
    pw = ph * iw / ih
    px = PAGE_W - MARGIN - pw
    c.saveState()
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.2)
    c.roundRect(px - 4, bottom - 4, pw + 8, ph + 8, 10, fill=0, stroke=1)
    c.drawImage(img, px, bottom, width=pw, height=ph, mask="auto")
    c.restoreState()

    # ---- copy (left), vertically centred against the phone
    x = MARGIN + 0.1 * inch
    maxw = px - 0.5 * inch - x
    y = top - 0.55 * inch
    c.setFillColor(RED)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(x, y, KICKER)

    y -= 0.85 * inch
    c.setFillColor(WHITE)
    size = 40
    while c.stringWidth(TITLE, "Helvetica-Bold", size) > maxw and size > 24:
        size -= 1
    c.setFont("Helvetica-Bold", size)
    c.drawString(x, y, TITLE)

    y -= 0.62 * inch
    mark = 0.34 * inch                        # the Slack mark, then the name
    draw_slack_mark(c, x, y - 0.03 * inch, mark)
    c.setFillColor(GOLD_HI)
    size = 26
    while c.stringWidth(CHANNEL, "Helvetica-Bold", size) > maxw - mark - 0.18 * inch and size > 16:
        size -= 1
    c.setFont("Helvetica-Bold", size)
    c.drawString(x + mark + 0.18 * inch, y, CHANNEL)

    y -= 0.75 * inch
    for line in LINES:
        c.setFillColor(GOLD)
        c.circle(x + 5, y + 5, 3.2, fill=1, stroke=0)
        c.setFillColor(ICD)
        c.setFont("Helvetica", 17)
        c.drawString(x + 0.28 * inch, y, line)
        y -= 0.46 * inch

    # ---- how-to card
    y -= 0.35 * inch
    ch = 1.05 * inch
    cw = min(maxw, 6.4 * inch)
    c.setFillColor(CARD)
    c.setStrokeColor(CARD_STROKE)
    c.setLineWidth(0.8)
    c.roundRect(x, y - ch + 0.3 * inch, cw, ch, 8, fill=1, stroke=1)
    cy = y - 0.12 * inch
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 14)
    c.drawString(x + 0.3 * inch, cy, CTA_1)
    cy -= 0.42 * inch
    c.setFillColor(GOLD_HI)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(x + 0.3 * inch, cy, CTA_2)
    w2 = c.stringWidth(CTA_2, "Helvetica-Bold", 20)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 14)
    c.drawString(x + 0.3 * inch + w2 + 0.18 * inch, cy, CTA_3)


class ChatSlide(Flowable):
    """The weekly chat promo, drawn in page coordinates over the frame."""

    def __init__(self):
        super().__init__()
        if not PHONE.exists():
            raise FileNotFoundError(f"chat slide asset missing: {PHONE}")

    def wrap(self, avail_w, avail_h):
        self.width, self.height = avail_w, avail_h
        return avail_w, avail_h

    def draw(self):
        c = self.canv
        ax, ay = c.absolutePosition(0, 0)
        c.saveState()
        c.translate(-ax, -ay)
        draw_chat(c)
        c.restoreState()
