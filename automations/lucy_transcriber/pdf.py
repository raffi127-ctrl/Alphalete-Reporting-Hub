"""The transcript as a PDF the rep (and Raf) open -- Megan 2026-11-21: "this
transcript needs to go into like a PDF or something they open", like the
2nd-round auditor sends back.

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
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (KeepTogether, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)

    when = when or dt.datetime.now()
    title = "{}'s pitch".format(who) if who else "Pitch transcript"
    W, H = letter
    band = 1.55 * inch

    def first(c, _doc):
        c.saveState()
        c.setFillColor(colors.HexColor(NAVY))
        c.rect(0, H - band, W, band, stroke=0, fill=1)
        c.setFillColor(colors.HexColor(SOFT))
        c.setFont("Helvetica-Bold", 9)
        c.drawString(0.75 * inch, H - 0.5 * inch, "L U C Y   ·   P I T C H   A U D I T O R")
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 24)
        c.drawString(0.75 * inch, H - 0.95 * inch, title)
        c.setFillColor(colors.HexColor(GOLD))
        c.setFont("Helvetica", 11)
        c.drawString(0.75 * inch, H - 1.25 * inch,
                     "{}  ·  {} long".format(_day(when), _clock(t["seconds"])))
        _footer(c)
        c.restoreState()

    def later(c, doc):
        c.saveState()
        c.setFillColor(colors.HexColor(GREY))
        c.setFont("Helvetica", 9)
        c.drawString(0.75 * inch, H - 0.5 * inch, title)
        c.drawRightString(W - 0.75 * inch, H - 0.5 * inch, "page {}".format(doc.page))
        _footer(c)
        c.restoreState()

    def _footer(c):
        c.setFillColor(colors.HexColor(GREY))
        c.setFont("Helvetica", 7.5)
        c.drawString(0.75 * inch, 0.45 * inch, NOTE)

    doc = SimpleDocTemplate(str(out), pagesize=letter, title=title, author="Lucy",
                            leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                            topMargin=band + 0.35 * inch, bottomMargin=0.8 * inch)
    body_w = W - 1.5 * inch
    label = ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=9,
                           leading=11, textColor=colors.HexColor(GREY))
    text = ParagraphStyle("text", fontName="Helvetica", fontSize=11.5,
                          leading=16, textColor=colors.HexColor(INK))

    story = [Paragraph("WHO DID THE TALKING", label), Spacer(1, 6)]
    talk = t.get("talk") or {}
    order = [sp for sp in ("R", "C", "O") if talk.get(sp)]
    if order:
        widths = [max(body_w * talk[sp] / 100.0, 0.6 * inch) for sp in order]
        scale = body_w / sum(widths)
        bar = Table([["{} {}%".format(ROLES[sp], talk[sp]) for sp in order]],
                    colWidths=[w * scale for w in widths], rowHeights=[0.34 * inch])
        style = [("FONT", (0, 0), (-1, -1), "Helvetica-Bold", 10),
                 ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                 ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                 ("LEFTPADDING", (0, 0), (-1, -1), 8)]
        for i, sp in enumerate(order):
            style.append(("BACKGROUND", (i, 0), (i, 0), colors.HexColor(COLOR[sp])))
        bar.setStyle(TableStyle(style))
        story.append(bar)
    story += [Spacer(1, 22), Paragraph("THE CONVERSATION", label), Spacer(1, 8)]

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
            ("TOPPADDING", (0, 0), (-1, 0), 7), ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
            ("TOPPADDING", (0, 1), (-1, 1), 1)]))
        # A short turn never splits across pages; a long one may.
        story += [KeepTogether([cell]) if len(tu["text"]) < 600 else cell, Spacer(1, 7)]

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.build(story, onFirstPage=first, onLaterPages=later)
    return out


def filename(who: Optional[str], when: dt.datetime) -> str:
    name = "".join(ch for ch in (who or "Pitch") if ch.isalnum() or ch in " -").strip()
    return "Pitch transcript - {} - {} {}.pdf".format(name, when.strftime("%b"), when.day)
