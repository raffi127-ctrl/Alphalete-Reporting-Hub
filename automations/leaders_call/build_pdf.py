"""Alphalete Leader's Call — recognition PDF generator.

Adapted from Maud's interactive build_pdf.py (Downloads) into a module that
renders from a RUN's `results` dict ({section_title: [(rep, owner, value)]})
instead of hardcoded lists. Called by run.py ONLY after a fully-successful pull
(no PullFailure / week-roll), so the deck is never built from incomplete data.

One section per page (Fiber, NDS, B2B, JE, BOX, Costco, Frontier — empty
sections skipped), then the green numbered Revenue leaderboard last. Layout,
fonts, and colors are unchanged from the original.

REQUIREMENTS: reportlab (in the report venv).
"""
from __future__ import annotations

import math
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

PAGE_W, PAGE_H = letter
MARGIN = 0.5 * inch

NAVY = colors.HexColor("#1B2A4A")
ACCENT = colors.HexColor("#2D6CDF")
HEADER_BG = colors.HexColor("#1B2A4A")
ROW_ALT = colors.HexColor("#EEF2FB")
GRID = colors.HexColor("#C9D4E8")
TEXT = colors.HexColor("#1A1A1A")
MUTED = colors.HexColor("#5A6B86")

styles = getSampleStyleSheet()
kicker_style = ParagraphStyle("kicker", parent=styles["Normal"], fontName="Helvetica-Bold",
    fontSize=9, textColor=MUTED, spaceAfter=2, leading=11)
title_style = ParagraphStyle("secTitle", parent=styles["Title"], fontName="Helvetica-Bold",
    fontSize=22, textColor=NAVY, spaceAfter=2, leading=26, alignment=TA_LEFT)
count_style = ParagraphStyle("count", parent=styles["Normal"], fontName="Helvetica",
    fontSize=9.5, textColor=MUTED, spaceAfter=10, leading=12)

# Display order + which section_titles are app-pages (Revenue handled separately).
SECTION_ORDER = ["Fiber", "NDS", "B2B", "JE", "BOX", "Costco", "Frontier"]
REVENUE_TITLE = "Revenue over 2K"

REV_HEADER = colors.HexColor("#0B3D2E")
REV_ACCENT = colors.HexColor("#0E7C5A")
REV_BG = colors.HexColor("#0B3D2E")
REV_ROW_ALT = colors.HexColor("#EAF4EF")
REV_GRID = colors.HexColor("#CADED5")
GOLD = colors.HexColor("#C8A24A")
SILVER = colors.HexColor("#7E8794")
BRONZE = colors.HexColor("#B07A47")

rev_title_style = ParagraphStyle("revTitle", parent=styles["Title"], fontName="Helvetica-Bold",
    fontSize=22, textColor=REV_HEADER, spaceAfter=2, leading=25, alignment=TA_LEFT)
rev_kicker_style = ParagraphStyle("revKicker", parent=styles["Normal"], fontName="Helvetica-Bold",
    fontSize=9, textColor=REV_ACCENT, spaceAfter=2, leading=11)


def clean_owner(owner):
    base = str(owner).split("\n")[0].split("[")[0].strip()
    letters = [c for c in base if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        base = base.title()
    return base


def cell_style(size, bold=False, align=TA_LEFT, color=TEXT):
    return ParagraphStyle(f"c{size}{bold}{align}{color}", parent=styles["Normal"],
        fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size, leading=size + 2, textColor=color, alignment=align)


def header_cell(text, align=TA_LEFT, fsize=12):
    return Paragraph(text, cell_style(fsize, bold=True, align=align, color=colors.white))


def body_row(rep, owner, apps, fsize):
    return [
        Paragraph(str(rep), cell_style(fsize)),
        Paragraph(clean_owner(owner), cell_style(fsize, color=MUTED)),
        Paragraph(str(apps), cell_style(fsize, bold=True, align=TA_CENTER, color=ACCENT)),
    ]


def title_block(name, qual, n):
    return [
        Paragraph("ALPHALETE LEADER'S CALL", kicker_style),
        Paragraph(name, title_style),
        Paragraph(f"{qual} &nbsp;&bull;&nbsp; {n} reps", count_style),
    ]


def single_column(name, qual, rows):
    n = len(rows)
    fsize = 12
    if n > 23:
        vpad = 3
    elif n > 16:
        vpad = 4
    elif n > 12:
        vpad = 6
    else:
        vpad = 8

    data = [[header_cell("REP'S NAME"), header_cell("OWNER'S NAME"),
             header_cell("APPS", align=TA_CENTER)]]
    for rep, owner, apps in rows:
        data.append(body_row(rep, owner, apps, fsize))

    usable = PAGE_W - 2 * MARGIN
    tbl = Table(data, colWidths=[usable * 0.40, usable * 0.46, usable * 0.14], repeatRows=1)
    ts = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 1), (-1, -1), vpad), ("BOTTOMPADDING", (0, 1), (-1, -1), vpad),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, ACCENT),
        ("LINEBELOW", (0, 1), (-1, -2), 0.5, GRID),
        ("BOX", (0, 0), (-1, -1), 0.8, GRID),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            ts.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    tbl.setStyle(TableStyle(ts))
    return title_block(name, qual, n) + [tbl]


def two_column(name, qual, rows):
    n = len(rows)
    fsize = 12
    vpad = 2.5
    half = math.ceil(n / 2)
    left, right = rows[:half], rows[half:]

    data = [[header_cell("REP'S NAME"), header_cell("OWNER'S NAME"),
             header_cell("APPS", align=TA_CENTER),
             header_cell("REP'S NAME"), header_cell("OWNER'S NAME"),
             header_cell("APPS", align=TA_CENTER)]]
    for i in range(half):
        lrow = body_row(*left[i], fsize) if i < len(left) else ["", "", ""]
        rrow = body_row(*right[i], fsize) if i < len(right) else [Paragraph("", cell_style(fsize))] * 3
        data.append(lrow + rrow)

    usable = PAGE_W - 2 * MARGIN
    cw = [usable * c for c in (0.205, 0.20, 0.095, 0.205, 0.20, 0.095)]
    tbl = Table(data, colWidths=cw, repeatRows=1)
    ts = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 1), (-1, -1), vpad), ("BOTTOMPADDING", (0, 1), (-1, -1), vpad),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, ACCENT),
        ("LINEBELOW", (0, 1), (-1, -2), 0.5, GRID),
        ("LINEAFTER", (2, 0), (2, -1), 1.0, NAVY),
        ("BOX", (0, 0), (-1, -1), 0.8, GRID),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            ts.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    tbl.setStyle(TableStyle(ts))
    return title_block(name, qual, n) + [tbl]


def build_section(name, qual, rows):
    if len(rows) > 30:
        return two_column(name, qual, rows)
    return single_column(name, qual, rows)


def fmt_money(v):
    return f"${v:,.2f}"


def revenue_page(revenue):
    n = len(revenue)
    half = math.ceil(n / 2)
    vpad = 1.0
    title_h = 66
    usable_h = PAGE_H - 2 * MARGIN
    fsize = 8.0
    while fsize > 6.0:
        header_h = 2 * (fsize + 2) + 10
        body_h = half * (fsize + 2 + 2 * vpad)
        total = title_h + header_h + body_h + 24
        if total <= usable_h:
            break
        fsize -= 0.25
    fsize = max(6.0, fsize)

    left = revenue[:half]
    right = revenue[half:]

    def rank_para(rank):
        color = REV_ACCENT
        if rank == 1:
            color = GOLD
        elif rank == 2:
            color = SILVER
        elif rank == 3:
            color = BRONZE
        return Paragraph(str(rank), ParagraphStyle(f"rk{rank}", parent=styles["Normal"],
            fontName="Helvetica-Bold", fontSize=fsize, leading=fsize + 2,
            textColor=color, alignment=TA_CENTER))

    def hdr(t, align=TA_LEFT):
        return Paragraph(t, ParagraphStyle(f"rh{t}{align}", parent=styles["Normal"],
            fontName="Helvetica-Bold", fontSize=fsize, leading=fsize + 2,
            textColor=colors.white, alignment=align))

    header = [hdr("#", TA_CENTER), hdr("REP'S NAME"), hdr("OWNER'S NAME"), hdr("$", TA_RIGHT),
              hdr("#", TA_CENTER), hdr("REP'S NAME"), hdr("OWNER'S NAME"), hdr("$", TA_RIGHT)]
    data = [header]

    def make_row(idx, item):
        rep, owner, amt = item
        return [
            rank_para(idx),
            Paragraph(str(rep), cell_style(fsize)),
            Paragraph(clean_owner(owner), cell_style(fsize, color=MUTED)),
            Paragraph(fmt_money(amt), cell_style(fsize, bold=True, align=TA_RIGHT, color=REV_ACCENT)),
        ]

    blank = ["", "", "", ""]
    for i in range(half):
        lrow = make_row(i + 1, left[i]) if i < len(left) else blank
        rrow = make_row(i + 1 + half, right[i]) if i < len(right) else blank
        data.append(lrow + rrow)

    usable = PAGE_W - 2 * MARGIN
    grp = (0.045, 0.22, 0.145, 0.09)
    cw = [usable * c for c in (grp + grp)]
    tbl = Table(data, colWidths=cw, repeatRows=1)
    ts = [
        ("BACKGROUND", (0, 0), (-1, 0), REV_BG),
        ("TOPPADDING", (0, 0), (-1, 0), 5), ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING", (0, 1), (-1, -1), vpad), ("BOTTOMPADDING", (0, 1), (-1, -1), vpad),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, REV_ACCENT),
        ("LINEBELOW", (0, 1), (-1, -2), 0.5, REV_GRID),
        ("LINEAFTER", (3, 0), (3, -1), 1.0, REV_HEADER),
        ("BOX", (0, 0), (-1, -1), 0.8, REV_GRID),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            ts.append(("BACKGROUND", (0, i), (-1, i), REV_ROW_ALT))
    tbl.setStyle(TableStyle(ts))

    left_block = [Paragraph("ALPHALETE LEADER'S CALL", rev_kicker_style),
                  Paragraph("Revenue", rev_title_style),
                  Paragraph(f"Over $2K &nbsp;&bull;&nbsp; {n} reps", count_style)]
    return left_block + [tbl]


def _apps_rows(rows):
    """results rows -> (rep, owner, int apps) for the app-section tables."""
    return [(r, o, int(round(float(v)))) for r, o, v in rows]


def build_pdf(results: dict, out_path, qualifiers: dict) -> Path:
    """Render the Leader's Call PDF from a run's `results` dict.

    results: {section_title: [(rep, owner, value)]}. A section that is None or
    empty is skipped (no page). `qualifiers` maps section_title -> the sub-title
    text (e.g. "12+ Apps", "8+ Apps (No Up)"). Revenue (REVENUE_TITLE) renders
    last as the numbered green leaderboard. Returns the output path."""
    out_path = Path(out_path)
    story = []
    for title in SECTION_ORDER:
        rows = results.get(title)
        if not rows:                       # None or [] -> skip the page
            continue
        story.extend(build_section(title, qualifiers.get(title, ""),
                                   _apps_rows(rows)))
        story.append(PageBreak())
    revenue = results.get(REVENUE_TITLE)
    if revenue:
        story.extend(revenue_page([(r, o, float(v)) for r, o, v in revenue]))
    elif story and isinstance(story[-1], PageBreak):
        story.pop()                        # no revenue -> drop the trailing break

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(out_path), pagesize=letter,
        leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN,
        title="Alphalete Leader's Call")
    doc.build(story)
    return out_path


def qualifiers_from_campaigns() -> dict:
    """Sub-title text per section, derived from each campaign's live threshold so
    the PDF label always tracks the config (e.g. BOX 12+ -> 8+)."""
    from automations.leaders_call.run import CAMPAIGNS
    from automations.leaders_call import frontier as fr
    q = {}
    for k in ("fiber", "nds", "b2b", "je", "box", "costco"):
        c = CAMPAIGNS[k]
        q[c.section_title] = f"{int(c.threshold)}+ Apps"
    q["Costco"] = q["Costco"] + " (No Up)"
    q["Frontier"] = f"{int(fr.THRESHOLD)}+ Apps"
    return q
