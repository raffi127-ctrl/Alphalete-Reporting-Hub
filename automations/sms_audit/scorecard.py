# -*- coding: utf-8 -*-
"""One weekly scorecard per recruiter, week over week.

Megan 2026-10-06: "maybe each recruiter gets their own scorecard for the
week- with a breakdown of what they need to work on week over week stats".

Everything here is already measured somewhere in the audit; this slices it
by PERSON and by WEEK so one recruiter can be handed their own page.

Two traps this module exists to avoid:

**The same person has two names.** Bookings come back as "L. Robinson"
(the Retention Report's initial-and-surname form) while texts come back as
"Leticia Robinson". Keyed naively, every scorecard shows bookings with no
texts or texts with no bookings. `key_of` folds both to first-initial +
surname, and `display` keeps the longest spelling seen.

**A week with no pull must stay blank.** analyze.load_log warns that a
suffixed run with no matching log quietly borrows the current week — which
is how two different weeks once ended up identical. A week is skipped
entirely unless BOTH its booking dump and its log are on disk.
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import argparse
import collections
import datetime as dt
import re
import statistics
import sys
from pathlib import Path

from automations.sms_audit import analyze as A
from automations.sms_audit import gradecard as GC
from automations.sms_audit import offices as O
from automations.sms_audit import retention as R

OUTPUT = Path(__file__).resolve().parents[2] / "output"
AI_NAMES = {"a messaging", "ai messaging", "lucy resume pushing", "system",
            "scheduled sms"}
# Below this many texts in a week a rate is one bad morning, not a trend.
MIN_TEXTS = 25


def key_of(name):
    """'L. Robinson' and 'Leticia Robinson' -> the same key.

    A trailing team tag is dropped before the surname is taken, but only
    when a real surname is left behind. Without that, "Max Jimenez APT"
    keys on APT, and so do "Anthony Zelaya APT" and "Abdiel Amador APT" —
    three people on one scorecard. With it, "C. NLR" and "Caitlyn NLR"
    still pair, because stripping NLR there would leave nothing to match
    on."""
    n = re.sub(r"[^A-Za-z .'-]", " ", (name or "")).strip()
    if not n:
        return ""
    parts = [p for p in re.split(r"\s+", n) if p]
    if len(parts) >= 3 and parts[-1].isupper() and 2 <= len(parts[-1]) <= 4:
        parts = parts[:-1]
    if len(parts) == 1:
        return parts[0].lower().strip(".")
    first, last = parts[0], parts[-1]
    return "{}.{}".format(first[0].lower(), last.lower())


def is_ai(name):
    n = re.sub(r"[^a-z ]", "", (name or "").lower()).strip()
    return n in AI_NAMES or key_of(name) in {key_of(x) for x in AI_NAMES}


def _median(xs):
    return statistics.median(xs) if xs else None


def week_stats(office, tag):
    """{key: {...}} for one week, or {} when that week was not pulled."""
    oid = office if isinstance(office, str) else office["office"]
    recs, _s = A.load_office(oid, tag)
    log, _s2 = A.load_log(oid, tag)
    if not recs or not log:
        return {}                      # never borrow another week's answer
    convos = A.log_conversations(log, A.booked_index(recs))

    out = collections.defaultdict(lambda: {
        "display": "", "booked": 0, "shown": 0, "texts": 0,
        "typing": 0, "house": 0, "dodged": 0, "replies": [],
        "issues": collections.Counter(), "examples": []})

    def slot(name):
        k = key_of(name)
        if not k:
            return None
        d = out[k]
        def _fullness(x):
            return (sum(c.isalpha() for c in x or ""), len(x or ""))
        if _fullness(name) > _fullness(d["display"]):
            d["display"] = name
        return d

    for r in recs:
        d = slot(r.get("booked_by"))
        if d is None:
            continue
        d["booked"] += 1
        if "No Show" not in (r.get("status") or ""):
            d["shown"] += 1

    for row in log:
        if (row.get("type") or "").strip() != "Out":
            continue
        d = slot(row.get("sent_by") or row.get("source"))
        if d is not None:
            d["texts"] += 1

    for e in A.text_errors(convos):
        d = slot(e.get("sender"))
        if d is not None:
            d["typing"] += 1

    for e in A.who_to_talk_to(convos, oid):
        d = slot(e.get("sender"))
        if d is None:
            continue
        n = int(e.get("count") or 0)
        d["house"] += n
        d["issues"][e.get("issue") or "?"] += n
        for ex in (e.get("examples") or [])[:2]:
            d["examples"].append((e.get("issue") or "?", ex.get("body") or ""))

    for e in A.dodged_questions(convos):
        d = slot(e.get("sender"))
        if d is not None:
            d["dodged"] += 1

    for st in A.reply_speed_by_sender(convos, min_n=1):
        d = slot(st.get("who"))
        if d is not None:
            d["replies"] = st
    return dict(out)


def collect(office, weeks=None):
    """{key: {'display', 'weeks': {tag: stats}}} across every pulled week."""
    weeks = weeks or R.WEEKS
    people = {}
    for tag in weeks:
        for k, d in week_stats(office, tag).items():
            p = people.setdefault(k, {"display": "", "weeks": {}})
            if (sum(c.isalpha() for c in d["display"]),
                    len(d["display"])) > (
                    sum(c.isalpha() for c in p["display"]),
                    len(p["display"])):
                p["display"] = d["display"]
            p["weeks"][tag] = d
    return people


# ----------------------------------------------------------- what to fix

def _rate(d, num, den):
    n, t = d.get(num) or 0, d.get(den) or 0
    return (100.0 * n / t) if t else None


def work_on(person, weeks):
    """[(area, now, before, grade, what to do)] worst first.

    Megan 2026-10-06: "The AI should have a report card too". It books
    more than anyone, so it belongs here — but you do not coach it. Every
    instruction below is rewritten for it: a person reads their text back,
    the AI gets its message edited in AppStream."""
    got = [w for w in weeks if w in person["weeks"]]
    if not got:
        return []
    bot = is_ai(person.get("display"))
    now = person["weeks"][got[-1]]
    before = person["weeks"][got[-2]] if len(got) > 1 else None
    items = []

    def add(area, value, grade, text, prev=None):
        if grade and grade not in "AB":
            items.append({"area": area, "now": value, "before": prev,
                          "grade": grade, "do": text})

    show = _rate(now, "shown", "booked")
    if show is not None and (now.get("booked") or 0) >= 5:
        prev = _rate(before, "shown", "booked") if before else None
        add("Show rate", "{:.0f}%".format(show),
            GC._band(show, 55, 48, 40),
            "Offer sooner interview times." if bot
            else "Book nearer the slot.",
            "{:.0f}%".format(prev) if prev is not None else None)

    if (now.get("texts") or 0) >= MIN_TEXTS:
        per100 = 100.0 * (now.get("typing") or 0) / now["texts"]
        prevp = (100.0 * (before.get("typing") or 0) / before["texts"]
                 if before and before.get("texts") else None)
        add("Typing", "{} in {} texts".format(now.get("typing"), now["texts"]),
            GC._band(per100, 0.5, 2, 5, higher_is_better=False),
            "Fix the wording in AppStream." if bot
            else "Read it back before sending.",
            "{} in {}".format(before.get("typing"), before.get("texts"))
            if before else None)

    house = now.get("house") or 0
    if house:
        worst = now["issues"].most_common(1)[0][0]
        add("House rules", "{} text{}".format(house, "" if house == 1 else "s"),
            GC._band(house, 0, 2, 6, higher_is_better=False),
            "{}. {}".format(worst, "Edit it in AI Settings." if bot
                            else "Use the approved wording."),
            "{}".format((before or {}).get("house")) if before else None)

    sp = now.get("replies") or {}
    if sp and sp.get("n", 0) >= 10:
        med = sp.get("median")
        prevmed = (before.get("replies") or {}).get("median") if before else None
        add("Reply speed", A_mins(med),
            GC._band(med, 5, 15, 45, higher_is_better=False),
            "Already instant." if bot else "Answer inside 5 minutes.",
            A_mins(prevmed) if prevmed is not None else None)

    dodged = now.get("dodged") or 0
    if dodged:
        add("Questions not answered", str(dodged),
            GC._band(dodged, 0, 2, 6, higher_is_better=False),
            "Give it a real answer in AI Settings, Escalations." if bot
            else "Answer the question, then book.",
            str((before or {}).get("dodged")) if before else None)

    items.sort(key=lambda i: "FDCBA".index(i["grade"]))
    return items


def A_mins(m):
    if m is None:
        return "—"
    m = float(m)
    if m < 60:
        return "{:.0f} min".format(m)
    return "{:.0f} hr {:.0f} min".format(m // 60, m % 60)


# -------------------------------------------------------------- rendering

CSS = """
body{font-family:Georgia,'Times New Roman',serif;color:#111;max-width:46em;
     margin:2em auto;padding:0 1.1em;line-height:1.5}
h1{font-size:1.5em;margin:0 0 .1em}
h2{font-size:1.1em;margin:1.8em 0 .5em;border-bottom:2px solid #111;
   padding-bottom:.2em}
.date{color:#666;margin:0 0 1.4em}
table{border-collapse:collapse;font-size:.95em;width:100%}
th,td{border:1px solid #ccc;padding:.3em .6em;text-align:left}
th{background:#f2f2f2}
td.n{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto;margin:.6em 0 1em}
.fix{border:2px solid #111;border-radius:6px;padding:.8em 1em;margin:1.2em 0}
.fix h2{margin-top:0;border:0}
tr.F td,tr.D td{background:#fdeaea}
tr.C td{background:#fff4e5}
.up{color:#156E46;font-weight:bold}
.down{color:#A8322A;font-weight:bold}
blockquote{margin:.4em 0 .4em 1em;padding:.3em .7em;border-left:3px solid #bbb;
           background:#f7f7f7;font-size:.95em}
.none{color:#666;font-style:italic}
@media (max-width:640px){body{margin:1em auto;font-size:15px}}
"""


def esc(t):
    return (str(t).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def render(person, office, weeks, path):
    d = person["weeks"]
    got = [w for w in weeks if w in d]
    L = ["<!doctype html><html><head><meta charset='utf-8'>",
         "<title>Scorecard — {}</title>".format(esc(person["display"])),
         "<style>{}</style></head><body>".format(CSS),
         "<h1>{}</h1>".format(esc(person["display"])),
         "<p class='date'>Account {} · week ending {}</p>".format(
             esc(office), esc(R.week_label(got[-1]) if got else "—"))]
    add = L.append

    fixes = work_on(person, weeks)
    add("<div class='fix'><h2>Work on this</h2>")
    if not fixes:
        add("<p>Nothing above the line this week.</p>")
    else:
        add("<div class='scroll'><table><tr><th>What</th><th>This week</th>"
            "<th>Last week</th><th>Do this</th></tr>")
        for f in fixes:
            add("<tr class='{}'><td>{}</td><td>{}</td><td>{}</td>"
                "<td>{}</td></tr>".format(
                    f["grade"], esc(f["area"]), esc(f["now"]),
                    esc(f["before"] or "—"), esc(f["do"])))
        add("</table></div>")
    add("</div>")

    add("<h2>Week over week</h2>")
    rows = [
        ("Interviews booked", lambda w: "{}".format(w.get("booked") or 0)),
        ("Showed up", lambda w: ("{:.0f}%".format(_rate(w, "shown", "booked"))
                                 if _rate(w, "shown", "booked") is not None
                                 else "—")),
        ("Texts sent", lambda w: "{:,}".format(w.get("texts") or 0)),
        ("Usual reply", lambda w: A_mins((w.get("replies") or {}).get("median"))),
        ("Typing mistakes", lambda w: "{}".format(w.get("typing") or 0)),
        ("House rules broken", lambda w: "{}".format(w.get("house") or 0)),
        ("Questions not answered", lambda w: "{}".format(w.get("dodged") or 0)),
    ]
    add("<div class='scroll'><table><tr><th></th>" + "".join(
        "<th>{}</th>".format(esc(R.week_label(t))) for t in got) + "</tr>")
    for label, fn in rows:
        add("<tr><td>{}</td>{}</tr>".format(
            esc(label),
            "".join("<td class='n'>{}</td>".format(esc(fn(d[t])))
                    for t in got)))
    add("</table></div>")

    last = d[got[-1]] if got else {}
    if last.get("examples"):
        add("<h2>The messages behind it</h2>")
        for issue, body in last["examples"][:8]:
            add("<blockquote><b>{}</b><br>{}</blockquote>".format(
                esc(issue), esc(body)))
    add("</body></html>")
    path.write_text("\n".join(L), encoding="utf-8")
    return path


def office_summary_html(people, weeks, include_ai=True):
    """The ICD's own breakdown: one row per recruiter, worst first.

    Megan 2026-10-06: "the ICD gets an email breakdown weekly and then each
    recruiter on their market has an attachment to it that is their
    scorecard". So this is the body, and the scorecards ride along as
    files — the ICD reads one table and forwards one attachment."""
    rows = []
    for _k, p in people.items():
        got = [w for w in weeks if w in p["weeks"]]
        if not got:
            continue
        if is_ai(p["display"]) and not include_ai:
            continue
        now = p["weeks"][got[-1]]
        if (now.get("texts") or 0) < MIN_TEXTS:
            continue
        fixes = work_on(p, weeks)
        rows.append((p["display"], now, fixes))
    rows.sort(key=lambda r: (-len(r[2]),
                             -(r[2][0]["grade"] == "F" if r[2] else 0)))

    out = ["<table role='presentation' cellpadding='6' cellspacing='0' "
           "style=\"border-collapse:collapse;font-family:Georgia,serif;"
           "font-size:14px\">",
           "<tr>" + "".join(
               "<th align='left' style=\"border-bottom:2px solid #111\">"
               "{}</th>".format(h)
               for h in ("Recruiter", "Booked", "Showed", "Texts",
                         "Usual reply", "To work on")) + "</tr>"]
    for name, now, fixes in rows:
        show = _rate(now, "shown", "booked")
        top = fixes[0]["area"] if fixes else "nothing"
        out.append(
            "<tr>"
            "<td style=\"border-bottom:1px solid #ddd\">{}</td>"
            "<td align='right' style=\"border-bottom:1px solid #ddd\">{}</td>"
            "<td align='right' style=\"border-bottom:1px solid #ddd\">{}</td>"
            "<td align='right' style=\"border-bottom:1px solid #ddd\">{:,}</td>"
            "<td align='right' style=\"border-bottom:1px solid #ddd\">{}</td>"
            "<td style=\"border-bottom:1px solid #ddd\">{}</td></tr>".format(
                esc(name), now.get("booked") or 0,
                "{:.0f}%".format(show) if show is not None else "—",
                now.get("texts") or 0,
                A_mins((now.get("replies") or {}).get("median")),
                esc(top)))
    out.append("</table>")
    return "\n".join(out), rows


def email_icd(office, people, weeks, paths, to, dry_run=True, logfn=print):
    """One email to the ICD: the table in the body, scorecards attached."""
    from automations.shared import report_email
    got = [w for w in weeks if any(w in p["weeks"] for p in people.values())]
    week = R.week_label(got[-1]) if got else "—"
    body, rows = office_summary_html(people, weeks)
    intro = ("<p>Here is the recruiting week for account {}, ending {}. "
             "Each person's own scorecard is attached — it shows the same "
             "numbers week over week and what to work on.</p>{}".format(
                 esc(office), esc(week), body))
    files = [(name, paths[name]) for name, _n, _f in rows if name in paths]
    return report_email.send_boards(
        subject="Recruiting scorecards — account {} — week ending {}".format(
            office, week),
        to=to, title="RECRUITING SCORECARDS — ACCOUNT {}".format(office),
        blocks=[], intro_html=intro, files=files,
        dry_run=dry_run, logfn=logfn)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="11280")
    ap.add_argument("--email", action="store_true",
                    help="build the ICD email; writes a preview and sends "
                         "NOTHING unless --send is given too")
    ap.add_argument("--send", action="store_true",
                    help="actually send it. Never set this without asking.")
    ap.add_argument("--to", default="", help="comma list, else the office's "
                                             "email from the config tab")
    ap.add_argument("--weeks", default="", help="comma list, default last 6")
    ap.add_argument("--no-ai", action="store_true",
                    help="leave the AI out; by default it gets a card like "
                         "anyone else, because it books more than anyone")
    a = ap.parse_args(argv)

    weeks = [w.strip() for w in a.weeks.split(",") if w.strip()] or R.WEEKS
    people = collect(a.office, weeks)
    if not people:
        print("[scorecard] nothing pulled for {} in {}".format(
            a.office, ", ".join(weeks)))
        return 1
    OUTPUT.mkdir(exist_ok=True)
    made = 0
    paths = {}
    for key, person in sorted(people.items(),
                              key=lambda kv: -sum(
                                  w.get("texts", 0)
                                  for w in kv[1]["weeks"].values())):
        if is_ai(person["display"]) and a.no_ai:
            continue
        total = sum(w.get("texts", 0) for w in person["weeks"].values())
        if total < MIN_TEXTS:
            continue
        path = OUTPUT / "scorecard-{}-{}.html".format(
            a.office, re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-"))
        render(person, a.office, weeks, path)
        paths[person["display"]] = path
        fixes = work_on(person, weeks)
        print("   {:<24} {:>6,} texts · {} to work on -> {}".format(
            person["display"][:24], total, len(fixes), path.name), flush=True)
        made += 1
    print("[scorecard] {} scorecard(s) for {}".format(made, a.office))

    if not a.email:
        return 0
    to = [x.strip() for x in a.to.split(",") if x.strip()]
    if not to:
        cfg = [o for o in (O.load()[0] or []) if o.get("office") == a.office]
        to = [x.strip() for x in ((cfg[0].get("email") if cfg else "") or "")
              .replace(";", ",").split(",") if x.strip()]
    if not to:
        print("[scorecard] no ICD email on file for {} — add one to the "
              "office tab or pass --to. Nothing sent.".format(a.office))
        return 1
    # Standing rule: ask before ANY send. --send is the only way through,
    # and without it this writes the preview and sends nothing.
    res = email_icd(a.office, people, weeks, paths, to, dry_run=not a.send)
    print("[scorecard] {} -> {}".format(
        "SENT" if a.send and res.get("ok") else "preview only", ", ".join(to)))
    if res.get("preview"):
        print("[scorecard] preview: {}".format(res["preview"]))
    return 0 if res.get("ok") or not a.send else 1


if __name__ == "__main__":
    sys.exit(main())
