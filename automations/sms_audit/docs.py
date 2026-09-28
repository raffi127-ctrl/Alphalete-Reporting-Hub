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
from automations.sms_audit import rebuttals as R

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

def scored(by_week, ai_only=True):
    """Every applicant question that HAS an approved answer, and what we
    actually sent back — scored against that answer, not against a guess."""
    out = []
    for tag, convos in by_week.items():
        for (office, _k), c in convos.items():
            msgs = sorted(c["msgs"], key=lambda m: m["when"])
            for i, m in enumerate(msgs):
                if m["dir"] != "In":
                    continue
                is_q, own = A.asks_something(m["body"] or "")
                if not is_q:
                    continue
                nxt = next((x for x in msgs[i + 1:]
                            if x["dir"] == "Out" and not x["template"]), None)
                if nxt is None:
                    continue
                if (nxt["when"] - m["when"]).total_seconds() > 7200:
                    continue
                if ai_only and not A.is_ai(nxt):
                    continue
                verdict = R.score(own, nxt["body"] or "")
                if not verdict:
                    continue
                topic, how, approved = verdict
                out.append({
                    "week": tag, "office": OFFICES[office],
                    "name": c.get("name", ""), "question": own,
                    "reply": " ".join((nxt["body"] or "").split()),
                    "topic": topic, "verdict": how, "approved": approved,
                    "sender": nxt.get("sent_by") or "AI Messaging"})
    return out


VERDICT = {"gave_it": "Gave the approved answer",
           "deflected": "Pushed it to the hiring manager or the interview",
           "ignored": "Never engaged with the question"}


def build_ai_doc(by_week, weeks, path):
    rows = scored(by_week, ai_only=True)
    human = scored(by_week, ai_only=False)
    human = [r for r in human if "ai messaging" not in r["sender"].lower()]
    span = "{} \u2013 {}".format(week_label(weeks[0]), week_label(weeks[-1]))
    d = _doc("Where the AI is not giving our approved answer",
             "All four accounts \u00b7 {} \u00b7 {} weeks \u00b7 built "
             "{:%d %b %Y}".format(span, len(weeks), dt.date.today()))

    _h(d, "How this is judged")
    d.add_paragraph(
        "Not by whether a reply seems responsive \u2014 by whether it gave "
        "the answer the company has already decided on. Every question "
        "below has an approved answer in the ARS Processes 2026 doc, under "
        "REBUTTALS and the SMS Templates table. A reply counts as correct "
        "when it carries those facts, in any wording; a recruiter who says "
        "it their own way has answered.")
    d.add_paragraph(
        "That doc is live and still being edited \u2014 this is a snapshot "
        "taken 26 Sep 2026. Re-pull it before treating any number here as "
        "final.")

    g = sum(1 for r in rows if r["verdict"] == "gave_it")
    hg = sum(1 for r in human if r["verdict"] == "gave_it")
    _h(d, "The headline")
    _table(d, ["Who replied", "Questions", "Gave the approved answer",
               "Deflected", "Ignored it"],
           [["The AI", len(rows), "{} ({:.0f}%)".format(
               g, 100.0 * g / len(rows) if rows else 0),
             sum(1 for r in rows if r["verdict"] == "deflected"),
             sum(1 for r in rows if r["verdict"] == "ignored")],
            ["A recruiter", len(human), "{} ({:.0f}%)".format(
                hg, 100.0 * hg / len(human) if human else 0),
             sum(1 for r in human if r["verdict"] == "deflected"),
             sum(1 for r in human if r["verdict"] == "ignored")]])

    _h(d, "By question, all six weeks")
    rowsout = []
    for topic, _q, _a, _m in R.REBUTTALS:
        mine = [r for r in rows if r["topic"] == topic]
        if not mine:
            continue
        gi = sum(1 for r in mine if r["verdict"] == "gave_it")
        rowsout.append([topic, len(mine), gi,
                        sum(1 for r in mine if r["verdict"] == "deflected"),
                        sum(1 for r in mine if r["verdict"] == "ignored"),
                        "{:.0f}%".format(100.0 * gi / len(mine))])
    rowsout.sort(key=lambda r: int(r[1]), reverse=True)
    _table(d, ["Question", "Asked", "Gave it", "Deflected", "Ignored",
               "% right"], rowsout)

    _h(d, "Week by week")
    _table(d, ["Week", "Questions", "Gave it", "% right"],
           [[week_label(t),
             sum(1 for r in rows if r["week"] == t),
             sum(1 for r in rows if r["week"] == t
                 and r["verdict"] == "gave_it"),
             "{:.0f}%".format(
                 100.0 * sum(1 for r in rows if r["week"] == t
                             and r["verdict"] == "gave_it")
                 / max(1, sum(1 for r in rows if r["week"] == t)))]
            for t in weeks])

    for topic, _q, _a, _m in R.REBUTTALS:
        bad = [r for r in rows if r["topic"] == topic
               and r["verdict"] != "gave_it"]
        if not bad:
            continue
        _h(d, "{}  \u2014  {} reply/replies that missed it".format(
            topic, len(bad)), size=13, space_before=16)
        _qa(d, "Our approved answer:", bad[0]["approved"])
        for e in bad[:12]:
            p = d.add_paragraph()
            p.paragraph_format.space_before = Pt(8)
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run("{} \u00b7 {} \u00b7 {}  [{}]".format(
                week_label(e["week"]), e["office"],
                e["name"] or "(no name)", VERDICT[e["verdict"]]))
            r.font.size = Pt(9)
            r.font.color.rgb = GREY
            _qa(d, "They asked:", e["question"])
            _qa(d, "AI replied:", e["reply"], RED)
        if len(bad) > 12:
            p = d.add_paragraph()
            r = p.add_run("\u2026 and {} more of the same.".format(len(bad) - 12))
            r.font.size = Pt(9)
            r.font.color.rgb = GREY

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
