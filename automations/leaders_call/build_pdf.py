"""Alphalete Leader's Call — recognition slide deck generator.

Renders from a RUN's `results` dict ({section_title: [(rep, owner, value)]}) into a
16:9 WIDESCREEN deck that is PROJECTED on the Monday Leader's Call to ~50-100 people
(Megan 2026-07-21): a branded title slide, then one leaderboard slide per campaign
(Fiber, NDS, B2B, JE, BOX, Costco — empty sections skipped), then the Revenue-over-
$2K slide. Big type readable from the back of the room; deep-navy ground; medals on
the top 3; a per-rep bar scaled from the campaign's qualifying FLOOR (so 12 = empty,
the leader = full); large gold numbers. A campaign with >20 reps splits across two
balanced slides. Called by run.py only after a fully-clean pull.

REQUIREMENTS: reportlab (in the report venv). Brand assets in resources/:
alphalete-logo-hq.png, alphalete-shield.png, wolf-emoji.png.
"""
from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Table, TableStyle,
                                PageBreak, Spacer)
from reportlab.platypus import Image as RLImage
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
from reportlab.lib.utils import ImageReader
from reportlab.graphics.shapes import Drawing, Rect, Circle, String
from reportlab.pdfbase.pdfmetrics import stringWidth

_RES = Path(__file__).resolve().parents[2] / "resources"
LOGO = _RES / "alphalete-logo-hq.png"
SHIELD = _RES / "alphalete-shield.png"
WOLF = _RES / "wolf-emoji.png"

PAGE_W, PAGE_H = 13.333 * inch, 7.5 * inch      # 16:9 widescreen
MARGIN = 0.6 * inch

# Alphalete brand palette — black / gold / red (Megan 2026-07-21: match the brand;
# the ALPHALETE wordmark is red, the wolf is gold, the ground is black).
INK = colors.HexColor("#0C0C0F")                # near-black ground
CARD = colors.HexColor("#1C1C22")               # charcoal top-3 highlight card
TRACK = colors.HexColor("#2C2C34")              # bar track
GOLD = colors.HexColor("#C8A24A")
GOLD_HI = colors.HexColor("#E4CE93")
SILVER = colors.HexColor("#AEB7C4")
BRONZE = colors.HexColor("#C08552")
BARLO = colors.HexColor("#8A7238")              # non-podium bar (muted gold, on-brand)
RED = colors.HexColor("#CC3340")                # brand red (the ALPHALETE wordmark)
WHITE = colors.HexColor("#F3F6FC")
MUTED = colors.HexColor("#9A9AA6")              # neutral gray
ICD = colors.HexColor("#C9CBD2")                # ICD/owner name — warm light gray
CHIP = colors.HexColor("#24242B")               # rank chip fill (ranks 4+)
CHIP_STROKE = colors.HexColor("#3C3C46")
ROW_ALT = colors.HexColor("#131317")
TOP10 = colors.HexColor("#2A1418")              # subtle red-tint highlight band

styles = getSampleStyleSheet()

SECTION_ORDER = ["Fiber", "NDS", "B2B", "BOX", "Costco"]   # JE removed (Carlos 2026-07-21)
REVENUE_TITLE = "Revenue over 2K"

# Body height available under the header/footer, and the smallest row that still
# holds a name-line + ICD-line without the 2-line content overflowing (which would
# spill the slide onto a 2nd page). Cap rows/slide so every row stays >= MIN_RH.
# Reserve enough for the header + gap + footer that the body table always sits on
# the SAME page as its header (a too-tight reserve bumps the table to a blank 2nd
# page). 2.2" reserve keeps ~0.5" of slack under the tallest body.
USABLE_H = PAGE_H - 2.2 * inch - 0.55 * inch
MIN_RH = 0.52 * inch
MAX_PER_COL = max(1, int(USABLE_H // MIN_RH))
PER_SLIDE = 2 * MAX_PER_COL                      # reps per slide before splitting (18)


def clean_owner(owner):
    b = str(owner).split("\n")[0].split("[")[0].strip()
    letters = [c for c in b if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        b = b.title()
    return b


def _fit(text, font, size, max_w, min_size):
    """Shrink `size` until `text` fits `max_w` on ONE line (down to min_size), so a
    long name never wraps — every row stays name-line + ICD-line and the left/right
    columns line up rank-for-rank."""
    while size > min_size and stringWidth(text, font, size) > max_w:
        size -= 0.5
    return size


def _badge(rank, size=30):
    d = Drawing(size, size)
    medal = {1: GOLD, 2: SILVER, 3: BRONZE}.get(rank)
    if medal:
        d.add(Circle(size / 2, size / 2, size / 2, fillColor=medal, strokeColor=None))
        d.add(String(size / 2, size / 2 - 5.6, str(rank), textAnchor="middle",
                     fontName="Helvetica-Bold", fontSize=15, fillColor=INK))
    else:
        d.add(Circle(size / 2, size / 2, size / 2, fillColor=CHIP, strokeColor=CHIP_STROKE,
                     strokeWidth=1.2))
        d.add(String(size / 2, size / 2 - 5.0, str(rank), textAnchor="middle",
                     fontName="Helvetica-Bold", fontSize=14, fillColor=colors.HexColor("#E8EEFA")))
    return d


def _bar(value, vmax, base, width, height=13, top=False):
    # Scale from the qualifying floor (base), not 0 — everyone shown is already
    # >= base, so a 0-anchored bar makes the floor look half-full.
    d = Drawing(width, max(height, 1))
    d.add(Rect(0, 0, width, height, rx=height / 2, ry=height / 2, fillColor=TRACK, strokeColor=None))
    span = vmax - base
    frac = max(0.0, min(1.0, (value - base) / span if span > 0 else 1.0))
    w = max(height, width * frac)
    d.add(Rect(0, 0, w, height, rx=height / 2, ry=height / 2, fillColor=GOLD if top else BARLO,
              strokeColor=None))
    if top:
        d.add(Rect(0, 0, min(w, height * 1.25), height, rx=height / 2, ry=height / 2,
                  fillColor=GOLD_HI, strokeColor=None))
    return d


def rep_para(rep, owner, big, avail_w, rs0=None, os0=None, lead=None):
    rs0 = rs0 if rs0 is not None else (16 if big else 14)
    os0 = os0 if os0 is not None else (12 if big else 11.5)
    owner = clean_owner(owner)
    rs = _fit(str(rep), "Helvetica-Bold", rs0, avail_w, 8.5)   # floor low enough that even
    os_ = _fit(owner, "Helvetica-Bold", os0, avail_w, 8.5)     # a 30+ char name stays one line
    return Paragraph(
        f'<font name="Helvetica-Bold" size="{rs}" color="#F3F6FC">{rep}</font><br/>'
        f'<font name="Helvetica-Bold" size="{os_}" color="#C9CBD2">{owner}</font>',
        ParagraphStyle("rp", leading=lead if lead is not None else rs0 + 4))


def num_para(v, big, money=False, avail_w=60):
    s = f"${v:,.0f}" if money else f"{v}"
    sz0 = (20 if money else 24) if big else (17 if money else 21)
    sz = _fit(s, "Helvetica-Bold", sz0, avail_w, 12)      # shrink so big $ never wraps
    return Paragraph(s, ParagraphStyle("np", alignment=TA_RIGHT, fontName="Helvetica-Bold",
                                       fontSize=sz, textColor=GOLD, leading=sz + 1))


def _col_table(rows, start_rank, vmax, base, col_w, rh, money=False):
    w_badge = 0.5 * inch
    w_num = 1.4 * inch if money else 0.75 * inch
    w_name = 2.35 * inch
    w_bar = col_w - w_badge - w_name - w_num - 0.25 * inch
    data, style = [], [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ALIGN", (0, 0), (0, -1), "CENTER"), ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [INK, ROW_ALT]),
    ]
    for j, (rep, owner, val) in enumerate(rows):
        rank = start_rank + j
        top = rank <= 3
        data.append([_badge(rank),
                     rep_para(rep, owner, top, w_name - 14,
                              rs0=(15 if top else 13.5), os0=(11 if top else 10.5), lead=15.5),
                     _bar(val, vmax, base, w_bar, top=top),
                     num_para(val, top, money, avail_w=w_num - 12)])
        if top:
            style.append(("BACKGROUND", (0, j), (-1, j), CARD))
    t = Table(data, colWidths=[w_badge, w_name, w_bar + 0.25 * inch, w_num],
              rowHeights=[rh] * len(rows))
    t.setStyle(TableStyle(style))
    return t


def header_block(title, qual, n_total, count_text=None):
    icon = RLImage(str(SHIELD), width=0.8 * inch, height=0.8 * inch * (2767 / 3379))
    ct = count_text if count_text is not None else f"{n_total} reps recognized"
    txt = [Paragraph("ALPHALETE LEADER'S CALL",
                     ParagraphStyle("k", fontName="Helvetica-Bold", fontSize=11, textColor=RED,
                                    leading=14, spaceAfter=1)),
           Paragraph(f'{title}<font size="23" color="#C8A24A">&nbsp;&nbsp;&nbsp;{qual}</font>'
                     f'<font size="14" color="#9A9AA6">&nbsp;&nbsp;&bull; {ct}</font>',
                     ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=34, textColor=WHITE,
                                    leading=36))]
    h = Table([[icon, txt]], colWidths=[1.05 * inch, (PAGE_W - 2 * MARGIN) - 1.05 * inch])
    h.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return h


def _slide(title, qual, rows, n_total, vmax, base, money=False, start=1):
    n = len(rows)
    half = math.ceil(n / 2)
    rh = min(0.66 * inch, USABLE_H / max(half, 1))
    usable_w = PAGE_W - 2 * MARGIN
    col_w = (usable_w - 0.4 * inch) / 2
    left = _col_table(rows[:half], start, vmax, base, col_w, rh, money)
    right = (_col_table(rows[half:], start + half, vmax, base, col_w, rh, money)
             if rows[half:] else Spacer(1, 1))
    body = Table([[left, right]], colWidths=[col_w, col_w], style=[
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 0.4 * inch)])
    return [header_block(title, qual, n_total), Spacer(1, 30), body]


REV_COLS = 3                # Revenue is dense (no bars) so ALL earners fit in ~3 slides
REV_PER_COL = 11
REV_PER_SLIDE = REV_COLS * REV_PER_COL


def _rev_cell_table(rows, start_rank, col_w, rh, hi_top10):
    """One dense revenue column: rank chip + name/ICD + $ (no bar). Medals on the
    top 3; the top-10 rows get a subtle highlight band on the first slide."""
    w_badge = 0.40 * inch
    w_num = 1.1 * inch
    w_name = col_w - w_badge - w_num - 0.12 * inch
    data, style = [], [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("ALIGN", (0, 0), (0, -1), "CENTER"), ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [INK, ROW_ALT]),
    ]
    for j, (rep, owner, val) in enumerate(rows):
        rank = start_rank + j
        top = rank <= 3
        data.append([_badge(rank, size=22),
                     rep_para(rep, owner, False, w_name - 10, rs0=11.5, os0=9.5, lead=14),
                     num_para(val, False, True, w_num - 14)])
        if top:
            style.append(("BACKGROUND", (0, j), (-1, j), CARD))
        elif hi_top10 and rank <= 10:
            style.append(("BACKGROUND", (0, j), (-1, j), TOP10))
    t = Table(data, colWidths=[w_badge, w_name, w_num], rowHeights=[rh] * len(rows))
    t.setStyle(TableStyle(style))
    return t


def _revenue_slides(rows_all, n_total):
    """ALL earners over $2K, dense 3-column, across ~3 slides — nobody dropped.
    Slide 1 leads 'Top Revenue' with the top 10 highlighted; the rest continue."""
    rows = sorted(rows_all, key=lambda r: float(r[2]), reverse=True)
    usable_w = PAGE_W - 2 * MARGIN
    gut = 0.24 * inch
    col_full = usable_w / REV_COLS
    col_w = col_full - gut
    rh = min(0.5 * inch, USABLE_H / REV_PER_COL)
    nslides = max(1, math.ceil(len(rows) / REV_PER_SLIDE))
    per_slide = math.ceil(len(rows) / nslides)             # balance across slides

    out = []
    for si in range(nslides):
        chunk = rows[si * per_slide:(si + 1) * per_slide]
        cpc = math.ceil(len(chunk) / REV_COLS)
        cols = [chunk[i * cpc:(i + 1) * cpc] for i in range(REV_COLS)]
        start = si * per_slide + 1
        subs, widths, cstyle = [], [], [("VALIGN", (0, 0), (-1, -1), "TOP"),
                                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                        ("TOPPADDING", (0, 0), (-1, -1), 0),
                                        ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]
        for ci in range(REV_COLS):
            cs = cols[ci] if ci < len(cols) else []
            subs.append(_rev_cell_table(cs, start + ci * cpc, col_w, rh, hi_top10=(si == 0))
                        if cs else Spacer(1, 1))
            widths.append(col_full)
            if ci < REV_COLS - 1:
                cstyle.append(("RIGHTPADDING", (ci, 0), (ci, 0), gut))
        body = Table([subs], colWidths=widths)
        body.setStyle(TableStyle(cstyle))
        title = "Top Revenue" if si == 0 else "Revenue over $2K"
        ct = (f"{n_total} recognized" if nslides == 1
              else f"{n_total} recognized · {si + 1} of {nslides}")
        out.extend([header_block(title, "Over $2K", n_total, count_text=ct), Spacer(1, 24), body])
        out.append(PageBreak())
    if out and isinstance(out[-1], PageBreak):
        out.pop()
    return out


# ---------------------------------------------------------------------------
# Leadership Promotions (finale) — read from Maud's recognition sheet, rendered
# after Revenue: a dramatic "PROMOTIONS" lead-in slide, then the list.
# ---------------------------------------------------------------------------
import re as _re

# The six tiers, ascending, each its own color. Extend as new tiers are added.
LEVEL_COLORS = {
    "Level 1":    "#6FA8FF",   # blue
    "Level 2":    "#5FD3B2",   # teal
    "Level 3":    "#79D06B",   # green
    "Mastermind": "#C58CFF",   # purple
    "Partner":    "#FF9F45",   # amber
    "Ownership":  "#E4CE93",   # gold (the pinnacle)
}


def normalize_level(raw: str):
    """Map the messy sheet text ('LVL 1 Leader', 'Lv1', 'level 2') to the clean
    canonical label + its color. Unknown → shown as-is in gray so it's obvious."""
    s = (raw or "").strip().lower()
    if "mastermind" in s:
        return "Mastermind", LEVEL_COLORS["Mastermind"]
    if "partner" in s:
        return "Partner", LEVEL_COLORS["Partner"]
    if "owner" in s:
        return "Ownership", LEVEL_COLORS["Ownership"]
    m = _re.search(r"(?:level|lvl|lv)\s*([123])", s)
    if m:
        lab = f"Level {m.group(1)}"
        return lab, LEVEL_COLORS[lab]
    return (raw or "").strip(), "#C9CBD2"


PROMO_PER_SLIDE = 12          # promotions per list slide before splitting


def _promo_star(size=24):
    d = Drawing(size, size)
    d.add(Circle(size / 2, size / 2, size / 2, fillColor=GOLD, strokeColor=None))
    d.add(String(size / 2, size / 2 - 4.6, "★", textAnchor="middle",
                 fontName="Helvetica-Bold", fontSize=13, fillColor=INK))   # centered in circle
    return d


def _level_pill(lab, col):
    """The tier as a filled, rounded color pill — the burst of color per card."""
    p = Paragraph(lab.upper(), ParagraphStyle("pill", alignment=TA_CENTER,
                  fontName="Helvetica-Bold", fontSize=11, textColor=INK, leading=13))
    t = Table([[p]], colWidths=[1.5 * inch], rowHeights=[0.34 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(col)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("ROUNDEDCORNERS", [7, 7, 7, 7])]))
    return t


def _promo_col(rows, col_w, rh):
    """One column of promotion CARDS: gold star, rep + trainer/ICD (auto-fit to one
    line so columns stay aligned), a cleaned note, a level-colored left accent, and
    the filled tier pill. Fixed row height locks left/right columns together."""
    w_badge = 0.58 * inch
    w_pill = 1.62 * inch
    w_name = col_w - w_badge - w_pill - 0.16 * inch
    data, style = [], [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, -1), CARD),
        ("LEFTPADDING", (0, 0), (0, -1), 16), ("LEFTPADDING", (1, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ALIGN", (0, 0), (0, -1), "CENTER"), ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -2), 5, INK),        # gap between cards
    ]
    for idx, (rep, trainer, owner, level, note) in enumerate(rows):
        lab, col = normalize_level(level)
        rp = _fit(str(rep), "Helvetica-Bold", 16, w_name - 10, 10)
        subraw = f"Trained by {str(trainer).strip()}  ·  {clean_owner(owner)}"
        ss = _fit(subraw, "Helvetica", 11.5, w_name - 10, 8.5)   # auto-fit → ICD never wraps
        lines = [f'<font name="Helvetica-Bold" size="{rp}" color="#F3F6FC">{rep}</font>',
                 f'<font name="Helvetica" size="{ss}" color="#B4B7C2">{subraw}</font>']
        if note and str(note).strip():
            lines.append(f'<font name="Helvetica-Oblique" size="10.5" color="#F7EBC4">{str(note).strip()}</font>')
        namep = Paragraph("<br/>".join(lines), ParagraphStyle("pn", leading=15.5))
        data.append([_promo_star(), namep, _level_pill(lab, col)])
        style.append(("LINEBEFORE", (0, idx), (0, idx), 4, colors.HexColor(col)))
    t = Table(data, colWidths=[w_badge, w_name, w_pill], rowHeights=[rh] * len(rows))
    t.setStyle(TableStyle(style))
    return t


def _tier_dots():
    """A row of the six tier colors — the promotion ladder, as a splash of color."""
    order = ["Level 1", "Level 2", "Level 3", "Mastermind", "Partner", "Ownership"]
    r, gap = 7, 34
    d = Drawing(gap * (len(order) - 1) + 2 * r, 2 * r)
    for i, lab in enumerate(order):
        d.add(Circle(r + i * gap, r, r, fillColor=colors.HexColor(LEVEL_COLORS[lab]),
                     strokeColor=None))
    d.hAlign = "CENTER"
    return d


def _promotions_intro(n_total, week_label):
    from reportlab.platypus.flowables import HRFlowable
    shield = RLImage(str(SHIELD), width=1.7 * inch, height=1.7 * inch * (2767 / 3379))
    shield.hAlign = "CENTER"
    kick = Paragraph("L E A D E R S H I P", ParagraphStyle("ik", alignment=TA_CENTER,
                     fontName="Helvetica-Bold", fontSize=20, textColor=RED, leading=26, spaceAfter=6))
    big = Paragraph("PROMOTIONS", ParagraphStyle("ib", alignment=TA_CENTER,
                    fontName="Helvetica-Bold", fontSize=70, textColor=GOLD, leading=72))
    rule = HRFlowable(width=175, thickness=2, color=GOLD, hAlign="CENTER",
                      spaceBefore=18, spaceAfter=16)
    count = Paragraph(f"{n_total} NEW LEADERS", ParagraphStyle("ic", alignment=TA_CENTER,
                      fontName="Helvetica-Bold", fontSize=25, textColor=WHITE, leading=30))
    wk = Paragraph(week_label, ParagraphStyle("iw", alignment=TA_CENTER, fontName="Helvetica",
                   fontSize=14, textColor=MUTED, leading=18, spaceBefore=5))
    return [Spacer(1, 0.75 * inch), shield, Spacer(1, 0.32 * inch), kick, big, rule,
            count, wk, Spacer(1, 0.55 * inch), _tier_dots()]


def _promotions_slides(promos, week_label):
    out = _promotions_intro(len(promos), week_label) + [PageBreak()]
    usable_w = PAGE_W - 2 * MARGIN
    col_w = (usable_w - 0.4 * inch) / 2
    num = max(1, math.ceil(len(promos) / PROMO_PER_SLIDE))
    per = math.ceil(len(promos) / num)
    for si in range(num):
        chunk = promos[si * per:(si + 1) * per]
        half = math.ceil(len(chunk) / 2)
        rh = min(0.82 * inch, USABLE_H / max(half, 1))
        left = _promo_col(chunk[:half], col_w, rh)
        right = _promo_col(chunk[half:], col_w, rh) if chunk[half:] else Spacer(1, 1)
        body = Table([[left, right]], colWidths=[col_w, col_w], style=[
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (1, 0), (1, 0), 0),
            ("RIGHTPADDING", (0, 0), (0, 0), 0.4 * inch)])
        title = ("Leadership Promotions" if num == 1
                 else f"Leadership Promotions  ({si + 1}/{num})")
        out += [header_block(title, "New Leaders", len(promos),
                             count_text=f"{len(promos)} promoted"), Spacer(1, 30), body, PageBreak()]
    if out and isinstance(out[-1], PageBreak):
        out.pop()
    return out


def _draw_cover(c, week_label, summary):
    c.saveState()
    c.setFillColor(INK)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.5)
    c.line(MARGIN, PAGE_H - 0.4 * inch, PAGE_W - MARGIN, PAGE_H - 0.4 * inch)
    c.line(MARGIN, 0.4 * inch, PAGE_W - MARGIN, 0.4 * inch)
    # Spread the title block down the page (Megan 2026-07-21: fill more of the slide).
    lw = 2.55 * inch
    logo_top = PAGE_H - 0.95 * inch                 # gap below the top gold rule
    c.drawImage(ImageReader(str(LOGO)), (PAGE_W - lw) / 2, logo_top - lw,
                width=lw, height=lw, mask="auto")
    cy = logo_top - lw - 0.75 * inch
    c.setFillColor(RED)
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(PAGE_W / 2, cy, "A L P H A L E T E   L E A D E R ' S   C A L L")
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 44)
    c.drawCentredString(PAGE_W / 2, cy - 0.85 * inch, "Weekly Recognition")
    c.setFillColor(GOLD_HI)
    c.setFont("Helvetica", 18)
    c.drawCentredString(PAGE_W / 2, cy - 1.45 * inch, week_label)
    if summary:
        c.setFillColor(WHITE)
        c.setFont("Helvetica", 13)
        c.drawCentredString(PAGE_W / 2, cy - 1.95 * inch, summary)
    # brand tagline — the 🐺 is the wolf PNG (base PDF fonts can't render the emoji)
    tag = "Live more.  Dream more.  Do more."
    tf, ts = "Helvetica-BoldOblique", 15
    tw = c.stringWidth(tag, tf, ts)
    try:
        from PIL import Image as _PIL
        wi = _PIL.open(str(WOLF))
        mh = 0.32 * inch
        mw = mh * (wi.width / wi.height)
        gap = 0.10 * inch
        by = 0.9 * inch
        x0 = (PAGE_W - (mw + gap + tw)) / 2
        c.drawImage(ImageReader(str(WOLF)), x0, by - (mh - ts * 0.72) / 2,
                    width=mw, height=mh, mask="auto")
        c.setFillColor(GOLD)
        c.setFont(tf, ts)
        c.drawString(x0 + mw + gap, by, tag)
    except Exception:      # no PIL/asset → just center the tagline text
        c.setFillColor(GOLD)
        c.setFont(tf, ts)
        c.drawCentredString(PAGE_W / 2, 0.9 * inch, tag)
    c.restoreState()


def _make_footer(week_label):
    def draw(c, doc):
        c.saveState()
        c.setFillColor(INK)
        c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        c.setStrokeColor(TRACK)
        c.setLineWidth(0.6)
        c.line(MARGIN, 0.42 * inch, PAGE_W - MARGIN, 0.42 * inch)
        c.setFillColor(ICD)
        c.setFont("Helvetica-Bold", 10.5)
        c.drawString(MARGIN, 0.24 * inch, f"Alphalete Leader's Call   ·   {week_label}")
        c.drawRightString(PAGE_W - MARGIN, 0.24 * inch, f"{doc.page - 1}")
        c.restoreState()
    return draw


def _week_label(sun) -> str:
    # No %-d (Windows-hostile) — build the day by hand. See cross-platform rule.
    return f"Week Ending {sun.strftime('%B')} {sun.day}, {sun.year}"


def _rows_ok(rows) -> bool:
    return isinstance(rows, list) and len(rows) > 0


def build_pdf(results: dict, out_path, qualifiers: dict,
              week_end: "dt.date | None" = None, summary: "str | None" = None,
              promotions: "list | None" = None) -> Path:
    """Render the Leader's Call widescreen deck from a run's `results` dict.

    results: {section_title: [(rep, owner, value)]}. Empty/None sections are
    skipped. `qualifiers` maps section_title -> sub-title (e.g. "12+ Apps").
    week_end (the recognized week's Sunday) and summary are derived if omitted."""
    out_path = Path(out_path)
    bases = bases_from_campaigns()
    if week_end is None:
        try:
            from automations.leaders_call.run import _target_week
            week_end = _target_week()[1]
        except Exception:
            week_end = dt.date.today()
    week_label = _week_label(week_end)

    # Title slide shows just the logo + week (Megan 2026-07-21: dropped the summary
    # line). summary stays None → _draw_cover skips it.

    story = [Spacer(1, 2), PageBreak()]            # page 1 stays blank → cover drawn on it
    order = SECTION_ORDER + [REVENUE_TITLE]
    for title in order:
        rows = results.get(title)
        if not _rows_ok(rows):
            continue
        money = title == REVENUE_TITLE
        rows = [(r, o, float(v) if money else int(round(float(v)))) for r, o, v in rows]
        if money:
            # Revenue: dense 3-column, ALL earners over $2K, top 10 highlighted.
            story.extend(_revenue_slides(rows, len(rows)))
            story.append(PageBreak())
            continue
        vmax = max(r[2] for r in rows)
        base = bases.get(title, 0)
        num = math.ceil(len(rows) / PER_SLIDE)
        per = math.ceil(len(rows) / max(num, 1))    # balanced split (14/13, not 20/7)
        chunks = [rows[i:i + per] for i in range(0, len(rows), per)]
        for ci, chunk in enumerate(chunks):
            label = title if len(chunks) == 1 else f"{title}  ({ci + 1}/{len(chunks)})"
            story.extend(_slide(label, qualifiers.get(title, ""), chunk, len(rows),
                                vmax, base, money, start=ci * per + 1))
            story.append(PageBreak())
    # Finale: the Leadership Promotions lead-in + list, AFTER Revenue. The section
    # loop already left a trailing PageBreak, so extend straight on (no extra break).
    if promotions:
        story.extend(_promotions_slides(promotions, week_label))

    if story and isinstance(story[-1], PageBreak):
        story.pop()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(out_path), pagesize=(PAGE_W, PAGE_H),
                            leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN,
                            bottomMargin=0.55 * inch, title="Alphalete Leader's Call")
    doc.build(story, onFirstPage=lambda c, d: _draw_cover(c, week_label, summary),
              onLaterPages=_make_footer(week_label))
    return out_path


def qualifiers_from_campaigns() -> dict:
    """Sub-title text per section, from each campaign's live threshold."""
    from automations.leaders_call.run import CAMPAIGNS
    q = {}
    for k in ("fiber", "nds", "b2b", "je", "box", "costco"):
        c = CAMPAIGNS[k]
        q[c.section_title] = f"{int(c.threshold)}+ Apps"
    q["Costco"] = q["Costco"] + " (No Up)"
    q[REVENUE_TITLE] = "Over $2K"
    return q


def bases_from_campaigns() -> dict:
    """Bar-scaling floor per section (the qualifying threshold); Revenue floor $2K."""
    from automations.leaders_call.run import CAMPAIGNS
    b = {}
    for k in ("fiber", "nds", "b2b", "je", "box", "costco"):
        c = CAMPAIGNS[k]
        b[c.section_title] = int(c.threshold)
    b[REVENUE_TITLE] = 2000
    return b
