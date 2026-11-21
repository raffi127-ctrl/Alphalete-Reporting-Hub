"""The transcript as a PDF the rep (and Raf) open -- Megan 2026-11-21: "this
transcript needs to go into like a PDF or something they open", like the
2nd-round auditor sends back.

PHONE-SHAPED, BIG TEXT (Megan 2026-11-21, on the first Letter-size version:
"super hard to read, I can't zoom in"). Slack's viewer fits the page to its
width, so a narrow page is what makes the words big -- 5 x 8.5 in, 16 pt.

Page 1 opens with a navy band (the auditor's colours): who, when, how long.
Then one bar showing who did the talking, and the conversation with every turn
marked REP (blue) or CUSTOMER (orange) and its time. Helvetica only, so it
renders the same on every Lucy and on Windows -- no font files.
"""
from __future__ import annotations  # Lucy runs Python 3.9

import datetime as dt
from pathlib import Path
from typing import Dict, Optional
from xml.sax.saxutils import escape

from automations.lucy_transcriber.transcribe import ROLES, _clock

NAVY = "#1F2A44"
SOFT = "#C9D3EA"
GOLD = "#F3E3A6"
INK = "#1A1A1A"
GREY = "#6B7280"
COLOR = {"R": "#2F6FDE", "C": "#E8781A", "O": "#9CA3AF"}
TINT = {"R": "#EEF3FC", "C": "#FDF1E7", "O": "#F3F4F6"}
PAGE = (5.0, 8.5)        # inches -- phone-shaped; see the module note

NOTE = ("Words transcribed by Lucy. Who said each line is worked out from the "
        "conversation, so a one-word reply (\"okay\", \"yeah\") can now and then "
        "land on the wrong side.")


def _day(when: dt.datetime) -> str:
    hour = when.strftime("%I:%M %p").lstrip("0")
    return "{}, {} {}, {} at {}".format(when.strftime("%A"), when.strftime("%B"),
                                       when.day, when.year, hour)


def render(t: Dict, out: Path, who: Optional[str] = None,
           when: Optional[dt.datetime] = None) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, NextPageTemplate,
                                    PageTemplate, Paragraph, Spacer, Table, TableStyle)

    when = when or dt.datetime.now()
    title = "{}'s pitch".format(who) if who else "Pitch transcript"
    W, H = PAGE[0] * inch, PAGE[1] * inch
    band = 1.45 * inch
    side = 0.4 * inch

    def first(c, _doc):
        c.saveState()
        c.setFillColor(colors.HexColor(NAVY))
        c.rect(0, H - band, W, band, stroke=0, fill=1)
        c.setFillColor(colors.HexColor(SOFT))
        c.setFont("Helvetica-Bold", 10)
        c.drawString(side, H - 0.42 * inch, "L U C Y  ·  P I T C H   A U D I T O R")
        c.setFillColor(colors.white)
        size = 24
        while size > 15 and c.stringWidth(title, "Helvetica-Bold", size) > W - 2 * side:
            size -= 1
        c.setFont("Helvetica-Bold", size)
        c.drawString(side, H - 0.85 * inch, title)
        c.setFillColor(colors.HexColor(GOLD))
        c.setFont("Helvetica", 12.5)
        c.drawString(side, H - 1.12 * inch, _day(when))
        c.drawString(side, H - 1.32 * inch, "{} long".format(_clock(t["seconds"])))
        c.restoreState()

    def later(c, doc):
        c.saveState()
        c.setFillColor(colors.HexColor(GREY))
        c.setFont("Helvetica", 11)
        c.drawString(side, H - 0.4 * inch, title)
        c.drawRightString(W - side, H - 0.4 * inch, "page {}".format(doc.page))
        c.restoreState()

    # Page 1 sits under the navy band; later pages use the whole page.
    bottom = 0.45 * inch
    doc = BaseDocTemplate(str(out), pagesize=(W, H), title=title, author="Lucy")
    doc.addPageTemplates([
        PageTemplate("first", [Frame(side, bottom, W - 2 * side,
                                     H - band - 0.3 * inch - bottom, id="f1",
                                     leftPadding=0, rightPadding=0)], onPage=first),
        PageTemplate("later", [Frame(side, bottom, W - 2 * side,
                                     H - 0.65 * inch - bottom, id="f2",
                                     leftPadding=0, rightPadding=0)], onPage=later)])
    body_w = W - 2 * side
    label = ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=11.5,
                           leading=14, textColor=colors.HexColor(GREY))
    text = ParagraphStyle("text", fontName="Helvetica", fontSize=16,
                          leading=22, textColor=colors.HexColor(INK))
    small = ParagraphStyle("small", fontName="Helvetica", fontSize=10,
                           leading=13, textColor=colors.HexColor(GREY))

    story = [NextPageTemplate("later"), Paragraph("WHO DID THE TALKING", label), Spacer(1, 6)]
    talk = t.get("talk") or {}
    order = [sp for sp in ("R", "C", "O") if talk.get(sp)]
    if order:
        from reportlab.pdfbase.pdfmetrics import stringWidth
        labels = ["{} {}%".format(ROLES[sp], talk[sp]) for sp in order]
        # Every label fits inside its own colour; the biggest share gives up
        # the room (it is a picture of who talked more, not a ruler).
        need = [stringWidth(l, "Helvetica-Bold", 13) + 18 for l in labels]
        widths = [max(body_w * talk[sp] / 100.0, n) for sp, n in zip(order, need)]
        big = widths.index(max(widths))
        widths[big] -= sum(widths) - body_w
        bar = Table([labels], colWidths=widths, rowHeights=[0.42 * inch])
        style = [("FONT", (0, 0), (-1, -1), "Helvetica-Bold", 13),
                 ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                 ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                 ("LEFTPADDING", (0, 0), (-1, -1), 8)]
        for i, sp in enumerate(order):
            style.append(("BACKGROUND", (i, 0), (i, 0), colors.HexColor(COLOR[sp])))
        bar.setStyle(TableStyle(style))
        story.append(bar)
    story += [Spacer(1, 20), Paragraph("THE CONVERSATION", label), Spacer(1, 8)]

    for tu in t["turns"]:
        sp = tu["speaker"]
        head = Paragraph(
            '<font color="{}"><b>{}</b></font>&nbsp;&nbsp;<font color="{}">{}</font>'.format(
                COLOR[sp], ROLES[sp].upper(), GREY, _clock(tu["start"])), label)
        cell = Table([[head], [Paragraph(escape(tu["text"]), text)]],
                     colWidths=[body_w - 6])
        cell.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(TINT[sp])),
            ("LINEBEFORE", (0, 0), (0, -1), 4, colors.HexColor(COLOR[sp])),
            ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, 0), 8), ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
            ("TOPPADDING", (0, 1), (-1, 1), 1)]))
        # A short turn never splits across pages; a long one may.
        story += [KeepTogether([cell]) if len(tu["text"]) < 400 else cell, Spacer(1, 8)]
    story += [Spacer(1, 10), Paragraph(NOTE, small)]

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.build(story)
    return out


def filename(who: Optional[str], when: dt.datetime) -> str:
    name = "".join(ch for ch in (who or "Pitch") if ch.isalnum() or ch in " -").strip()
    return "Pitch transcript - {} - {} {}.pdf".format(name, when.strftime("%b"), when.day)
