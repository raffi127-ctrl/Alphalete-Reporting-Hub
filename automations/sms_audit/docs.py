"""Two Word documents off the SMS audit, both covering the whole six weeks.

Megan 2026-09-27: "compile the badly handled message responses from AI
specifically on all 4 accounts into a word document — I need them grouped
together in some way to give feedback on what we're seeing", then "compile a
word document of the common questions asked on all 4 accounts and what the
common response is", and "the word documents need to show the picture of all
6 weeks - not just 1 week".

  python -m automations.sms_audit.docs
  ... docs.py --weeks w0911,w0918,w0925      # a shorter window
  ... docs.py --only ai                      # just the first document

WHY POOLED AND NOT PER-TAB. The sheet answers "how was this account this
week"; these answer "what are we doing wrong, across everything". So every
office-week is loaded and the conversations are pooled into ONE set before a
single count is taken — 21,830 conversations over six weeks and four
accounts — and each document still carries a week-by-week row so a trend is
visible rather than a single lump.

Both are read-only: local JSON in, .docx out, nothing sent anywhere.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

from automations.sms_audit import analyze as A

OUTPUT = Path(__file__).resolve().parents[2] / "output"
OFFICES = collections.OrderedDict([
    ("11280", "Rafael Hidalgo (11280)"),
    ("23965", "Rafael 2nd funnel (23965)"),
    ("24065", "Raf new recruiter test (24065)"),
    ("11580", "Carlos Hidalgo (11580)"),
])
WEEKS = ["w0821", "w0828", "w0904", "w0911", "w0918", "w0925"]
GREY = RGBColor(0x55, 0x5A, 0x60)
RED = RGBColor(0xB8, 0x1C, 0x1C)

KIND_TITLE = {
    "dodged": "Did not answer what was asked",
    "deflected": "Pushed the answer to the interview or a call",
    "informal": "Texting shorthand under the company's name",
}


def week_label(tag):
    return "WE {}/{}".format(int(tag[1:3]), int(tag[3:5]))


def load(weeks):
    """Every office-week, pooled. Returns (per-week convos, all convos)."""
    by_week, pooled = collections.OrderedDict(), {}
    for tag in weeks:
        wk = {}
        for office in OFFICES:
            recs, _s = A.load_office(office, tag)
            log, _s2 = A.load_log(office, tag)
            if not recs or not log:
                continue
            for key, convo in A.log_conversations(
                    log, A.booked_index(recs)).items():
                convo = dict(convo, office=office, week=tag)
                wk[(office, key)] = convo
                pooled[(office, tag, key)] = convo
        if wk:
            by_week[tag] = wk
    return by_week, pooled


# ------------------------------------------------------------------ docx ----

def _doc(title, subtitle):
    d = Document()
    st = d.styles["Normal"]
    st.font.name = "Georgia"
    st.font.size = Pt(11)
    h = d.add_paragraph()
    r = h.add_run(title)
    r.bold = True
    r.font.size = Pt(20)
    p = d.add_paragraph()
    r = p.add_run(subtitle)
    r.font.size = Pt(10)
    r.font.color.rgb = GREY
    return d


def _table(d, headers, rows, widths=None):
    t = d.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    for i, htxt in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(str(htxt))
        run.bold = True
        run.font.size = Pt(10)
    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(str(val))
            run.font.size = Pt(10)
            if i:
                cells[i].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    d.add_paragraph()
    return t


def _h(d, text, size=14, space_before=10):
    p = d.add_paragraph()
    p.paragraph_format.space_before = Pt(space_before)
    r = p.add_run(text)
    r.bold = True
    r.font.size = Pt(size)
    return p


def _qa(d, label, text, colour=None):
    p = d.add_paragraph()
    p.paragraph_format.left_indent = Pt(18)
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run("{} ".format(label))
    r.bold = True
    r.font.size = Pt(10)
    r.font.color.rgb = GREY
    r2 = p.add_run(text)
    r2.font.size = Pt(10)
    if colour is not None:
        r2.font.color.rgb = colour
    return p


# ------------------------------------------------------- document one -------

def ai_failures(by_week, weeks):
    """Every AI reply that handled a direct question badly, all four accounts.

    Grouped by WHAT WAS ASKED rather than by the failure kind, because that
    is the unit of feedback: "when someone asks where the office is, here is
    what the AI does" is a sentence the vendor can act on. The kind is tagged
    on each example so the two readings are both available."""
    rows = []
    for tag, convos in by_week.items():
        # per OFFICE, not per week — dodged_questions returns the reply and
        # who sent it but not which account it came from, and "which account"
        # is half the feedback ("39 of the 44 are one office").
        for office, name in OFFICES.items():
            mine = {k: v for k, v in convos.items() if k[0] == office}
            if not mine:
                continue
            for e in A.dodged_questions(mine):
                if "ai messaging" not in (e.get("sender") or "").lower():
                    continue
                rows.append(dict(e, week=tag, office_name=name))
    return rows


def build_ai_doc(by_week, weeks, path):
    rows = ai_failures(by_week, weeks)
    span = "{} – {}".format(week_label(weeks[0]), week_label(weeks[-1]))
    d = _doc("AI replies that handled a question badly",
             "All four accounts · {} · {} weeks · built {:%d %b %Y}\n"
             "Every case below is a reply sent by AI Messaging, not by a "
             "recruiter.".format(span, len(weeks), dt.date.today()))

    _h(d, "What this is")
    d.add_paragraph(
        "An applicant asked a direct question and the AI's reply did not "
        "answer it. Three things are counted, and they need different fixes: "
        "the reply answered nothing that was asked, the reply pushed the "
        "answer to the interview or a call, or the reply used texting "
        "shorthand under the company's name. A reply only counts if it "
        "arrived within two hours of the question — anything later is not a "
        "response to it.")

    _h(d, "The six weeks at a glance")
    kinds = collections.Counter(r["kind"] for r in rows)
    _table(d, ["Week", "Cases"],
           [[week_label(t), sum(1 for r in rows if r["week"] == t)]
            for t in weeks] + [["TOTAL", len(rows)]])
    _table(d, ["What went wrong", "Cases"],
           [[KIND_TITLE.get(k, k), n] for k, n in kinds.most_common()])
    accts = collections.Counter(r["office_name"] for r in rows)
    _table(d, ["Account", "Cases"],
           [[n, accts.get(n, 0)] for n in OFFICES.values()])

    _h(d, "Grouped by what the applicant asked")
    topics = collections.Counter(r["bucket"] for r in rows)
    order = [t for t, _n in topics.most_common() if t != "(other)"]
    if "(other)" in topics:
        order.append("(other)")
    for topic in order:
        mine = [r for r in rows if r["bucket"] == topic]
        head = topic if topic != "(other)" else "Did not fit a known topic"
        _h(d, "{}  —  {} case{}".format(head, len(mine),
                                        "" if len(mine) == 1 else "s"),
           size=12, space_before=14)
        kc = collections.Counter(r["kind"] for r in mine)
        p = d.add_paragraph()
        r = p.add_run(" · ".join("{}: {}".format(KIND_TITLE.get(k, k), n)
                                 for k, n in kc.most_common()))
        r.font.size = Pt(9)
        r.font.color.rgb = GREY
        for e in mine:
            p = d.add_paragraph()
            p.paragraph_format.space_before = Pt(8)
            p.paragraph_format.space_after = Pt(0)
            meta = "{} · {}{}".format(
                week_label(e["week"]), e.get("name") or "(no name)",
                "  [{}]".format(KIND_TITLE.get(e["kind"], e["kind"])))
            r = p.add_run(meta)
            r.font.size = Pt(9)
            r.font.color.rgb = GREY
            _qa(d, "They asked:", e["question"])
            _qa(d, "AI replied:", e["reply"], RED)

    d.save(str(path))
    return len(rows), path


# ------------------------------------------------------- document two -------

def build_questions_doc(by_week, pooled, weeks, path):
    span = "{} – {}".format(week_label(weeks[0]), week_label(weeks[-1]))
    table = A.question_responses([], pooled, top_n=3)
    per_week = {t: {r["question"]: r["asked"]
                    for r in A.question_responses([], c)}
                for t, c in by_week.items()}

    d = _doc("What applicants ask, and what we say back",
             "All four accounts · {} · {} weeks · {:,} conversations · "
             "built {:%d %b %Y}".format(span, len(weeks), len(pooled),
                                        dt.date.today()))

    _h(d, "What this is")
    d.add_paragraph(
        "Every question applicants asked by text over the six weeks, most "
        "asked first, with the reply we most often send back. An answer only "
        "counts if a person or the AI typed it within two hours — a "
        "scheduled template that happened to fire afterwards is a blast, not "
        "a reply, so it is counted as no answer.")

    _h(d, "Every question, all six weeks")
    _table(d, ["Question", "Asked", "Answered", "No reply", "% answered"],
           [[r["question"], "{:,}".format(r["asked"]),
             "{:,}".format(r["answered"]), "{:,}".format(r["no_reply"]),
             "{:.0f}%".format(100.0 * r["answered"] / r["asked"])
             if r["asked"] else "—"] for r in table])

    _h(d, "Asked per week")
    _table(d, ["Question"] + [week_label(t) for t in weeks],
           [[r["question"]] + [per_week.get(t, {}).get(r["question"], 0)
                               for t in weeks] for r in table])

    _h(d, "What we reply, question by question")
    for r in table:
        _h(d, "{}  —  asked {:,} times".format(r["question"], r["asked"]),
           size=12, space_before=14)
        if r["example"]:
            _qa(d, "For example:", "“{}”".format(r["example"]))
        if r["replies"]:
            p = d.add_paragraph()
            run = p.add_run("What we send back, most common first:")
            run.bold = True
            run.font.size = Pt(10)
            for reply, n in r["replies"]:
                _qa(d, "{}x".format(n), reply)
        else:
            _qa(d, "", "No typed reply was ever sent to this question.")
        if r["no_reply"]:
            bits = ["{:,} got no reply inside two hours".format(r["no_reply"])]
            if r["no_reply_booked"]:
                bits.append("{:,} of those booked anyway (answered on a "
                            "call)".format(r["no_reply_booked"]))
            if r["blast"]:
                bits.append("the template that most often went out instead "
                            "was “{}” ({:,}x)".format(r["blast"],
                                                                r["blast_n"]))
            p = d.add_paragraph()
            run = p.add_run(" · ".join(bits))
            run.font.size = Pt(9)
            run.font.color.rgb = RED
    d.save(str(path))
    return len(table), path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", default=",".join(WEEKS))
    ap.add_argument("--only", choices=["ai", "questions"], default="")
    a = ap.parse_args(argv)
    weeks = [w.strip() for w in a.weeks.split(",") if w.strip()]

    by_week, pooled = load(weeks)
    if not pooled:
        print("[docs] nothing to read — no pulls on disk for {}".format(weeks))
        return 1
    print("[docs] {} office-weeks · {:,} conversations pooled".format(
        sum(1 for _ in by_week), len(pooled)), flush=True)
    OUTPUT.mkdir(exist_ok=True)

    if a.only != "questions":
        n, p = build_ai_doc(by_week, weeks,
                            OUTPUT / "ai-replies-handled-badly.docx")
        print("[docs] {} AI cases -> {}".format(n, p), flush=True)
    if a.only != "ai":
        n, p = build_questions_doc(by_week, pooled, weeks,
                                   OUTPUT / "applicant-questions-and-replies.docx")
        print("[docs] {} questions -> {}".format(n, p), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
