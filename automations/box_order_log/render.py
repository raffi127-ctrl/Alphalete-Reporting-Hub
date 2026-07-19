"""Render the collapsed BOX Order Log to a PDF.

Layout, top to bottom:
  1. Title + the window the data covers.
  2. Count of sales by week ending x status  (Carlos: "a count of everything
     by the week ending, like AT&T has").
  3. One section per week ending, newest first, color-coded by status.
  4. A legend saying what each status means for the rep.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

from . import clean

# Georgia is Megan's house face for report output but isn't a reportlab
# built-in and isn't guaranteed on the mini, so we use the closest always-
# present serif rather than risking a font-not-found at 7am on Lucy 2.
BODY_FONT = "Times-Roman"
BOLD_FONT = "Times-Bold"

INK = colors.HexColor("#1A1A1A")
RULE = colors.HexColor("#B7B7B7")
HEAD_BG = colors.HexColor("#3D3D3D")


def _c(hex_str: str) -> colors.Color:
    return colors.HexColor("#" + hex_str)


def _styles():
    ss = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=ss["Title"], fontName=BOLD_FONT,
                                fontSize=20, leading=24, textColor=INK,
                                alignment=TA_LEFT, spaceAfter=2),
        "sub": ParagraphStyle("s", parent=ss["Normal"], fontName=BODY_FONT,
                              fontSize=10, leading=13,
                              textColor=colors.HexColor("#666666")),
        "h2": ParagraphStyle("h", parent=ss["Heading2"], fontName=BOLD_FONT,
                             fontSize=13, leading=16, textColor=INK,
                             spaceBefore=14, spaceAfter=5),
        "note": ParagraphStyle("n", parent=ss["Normal"], fontName=BODY_FONT,
                               fontSize=8.5, leading=11,
                               textColor=colors.HexColor("#666666")),
    }


def _fmt_week(w: Optional[dt.date]) -> str:
    return w.strftime("%m/%d/%Y") if w else "No sale date"


def _summary_table(sales, st) -> Table:
    weeks, statuses, counts = clean.week_counts(sales)
    header = ["Week Ending"] + [s.replace(" by ", " by\n").replace(" to ", " to\n")
                                for s in statuses] + ["TOTAL"]
    data: List[List[str]] = [header]
    for w in weeks:
        row = [_fmt_week(w)]
        total = 0
        for s in statuses:
            n = counts.get((w, s), 0)
            total += n
            row.append(str(n) if n else "")
        row.append(str(total))
        data.append(row)
    totals = ["ALL WEEKS"]
    for s in statuses:
        totals.append(str(sum(counts.get((w, s), 0) for w in weeks)))
    totals.append(str(len(list(sales))))
    data.append(totals)

    tbl = Table(data, repeatRows=1, hAlign="LEFT")
    style = [
        ("FONTNAME", (0, 0), (-1, -1), BODY_FONT),
        ("FONTNAME", (0, 0), (-1, 0), BOLD_FONT),
        ("FONTNAME", (0, -1), (-1, -1), BOLD_FONT),
        ("FONTNAME", (-1, 0), (-1, -1), BOLD_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EDEDED")),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    # Tint each status column with its own color so the summary reads the
    # same way as the detail sections below it.
    for i, s in enumerate(statuses, start=1):
        hexv = clean.STATUS_INK.get(s)
        if hexv:
            style.append(("TEXTCOLOR", (i, 1), (i, -2), _c(hexv)))
    tbl.setStyle(TableStyle(style))
    return tbl


def _detail_table(week_sales) -> Table:
    labels = [label for _, label in clean.COLUMNS]
    data: List[List[str]] = [labels]
    for s in week_sales:
        row = []
        for src, _label in clean.COLUMNS:
            v = (s.fields.get(src) or "").strip()
            if src in ("Sale Date", "Accepted Date") and v:
                d = clean._parse_date(v)
                v = d.strftime("%m/%d") if d else v
            if src == "Business Name" and len(v) > 34:
                v = v[:33] + "…"
            # Sub-status repeats the status verbatim on most rows ("Accepted
            # by Supplier / Accepted by Supplier"). It only earns its column
            # when it adds something — TPV Passed vs TPV Failed, PDF Generated.
            if src == "Contr. Sub-status" and v == s.status:
                v = ""
            row.append(v)
        data.append(row)

    widths = [0.62, 1.55, 2.25, 0.72, 1.45, 1.45, 0.68, 0.45, 1.05]
    tbl = Table(data, colWidths=[w * inch for w in widths],
                repeatRows=1, hAlign="LEFT")
    style = [
        ("FONTNAME", (0, 0), (-1, -1), BODY_FONT),
        ("FONTNAME", (0, 0), (-1, 0), BOLD_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.35, RULE),
        ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
        ("ALIGN", (-2, 1), (-2, -1), "CENTER"),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    status_col = [label for _, label in clean.COLUMNS].index("Status")
    for r, s in enumerate(week_sales, start=1):
        hexv = clean.STATUS_COLORS.get(s.status)
        if hexv:
            style.append(("BACKGROUND", (status_col, r), (status_col, r), _c(hexv)))
        if s.is_cancel or s.status in ("Rejected", "Dropped"):
            style.append(("TEXTCOLOR", (0, r), (-1, r), colors.HexColor("#CC0000")))
    tbl.setStyle(TableStyle(style))
    return tbl


def _legend(styles) -> Table:
    rows = []
    for status in clean.STATUS_PRIORITY:
        meaning = clean.STATUS_MEANING.get(status)
        if meaning:
            rows.append(["", status, meaning])
    tbl = Table(rows, colWidths=[0.22 * inch, 1.8 * inch, 5.0 * inch],
                hAlign="LEFT")
    style = [
        ("FONTNAME", (1, 0), (1, -1), BOLD_FONT),
        ("FONTNAME", (2, 0), (2, -1), BODY_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    for i, row in enumerate(rows):
        hexv = clean.STATUS_COLORS.get(row[1])
        if hexv:
            style.append(("BACKGROUND", (0, i), (0, i), _c(hexv)))
            style.append(("BOX", (0, i), (0, i), 0.3, RULE))
    tbl.setStyle(TableStyle(style))
    return tbl


def render_pdf(sales, stats: Dict[str, int], out_path: Path,
               *, title: str = "BOX Order Log",
               subtitle: str = "") -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    styles = _styles()

    doc = SimpleDocTemplate(
        str(out_path), pagesize=landscape(letter),
        leftMargin=0.45 * inch, rightMargin=0.45 * inch,
        topMargin=0.45 * inch, bottomMargin=0.45 * inch,
        title=title, author="Alphalete Reporting Hub",
    )

    story: List = [Paragraph(title, styles["title"])]
    if subtitle:
        story.append(Paragraph(subtitle, styles["sub"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Sales by Week Ending", styles["h2"]))
    story.append(_summary_table(sales, stats))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "One row per sale. A sale's pipeline steps are collapsed into its "
        "current status — if it reached Accepted by Supplier, the earlier "
        "steps are hidden. Quotes that never became sales are excluded.",
        styles["note"]))

    story.append(Spacer(1, 10))
    story.append(Paragraph("What each status means", styles["h2"]))
    story.append(_legend(styles))

    for week, week_sales in clean.by_week(sales).items():
        story.append(PageBreak())
        story.append(Paragraph(
            "Week Ending {}&nbsp;&nbsp;<font size=10 color='#666666'>"
            "{} sale{}</font>".format(_fmt_week(week), len(week_sales),
                                      "" if len(week_sales) == 1 else "s"),
            styles["h2"]))
        story.append(_detail_table(week_sales))

    doc.build(story)
    return out_path
