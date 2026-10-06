"""The recruiting auditor, per office — templates, recruiter texts, retention.

Megan 2026-10-01: "We need to build an auditor to run on app stream for the
iCDs, using the framework we have now", then the three things it has to do:
check the office's own address/phone/links, point out anything weird in the
AppStream templates, audit recruiter grammar and deflection, and show what
is changing in retention between the AI and people.

It is office-agnostic on purpose — point it at accounts later. Every office
it audits comes from the "Recruiting Audit Offices" tab, and an office with
a blank field gets that check SKIPPED AND SAID, never passed quietly.

  python -m automations.sms_audit.icd_audit                 # every active office
  ... icd_audit.py --office 11280                           # one
  ... icd_audit.py --skip-templates                         # messages only

Reads only files already pulled; it starts nothing on AppStream. Writes
output/icd-audit-<office>.html (HTML so the per-person
examples actually expand) and prints a summary.
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import argparse
import collections
import datetime as dt
import statistics
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.sms_audit import analyze as A
from automations.sms_audit import ai_settings as AIS
from automations.sms_audit import call_list as CL
from automations.sms_audit import escalations as ESC
from automations.sms_audit import gradecard as GC
from automations.sms_audit import leadtime as LT
from automations.sms_audit import offices as O
from automations.sms_audit import retention as R
from automations.sms_audit import rebuttals as RB
from automations.sms_audit import templates as T

OUTPUT = Path(__file__).resolve().parents[2] / "output"


def template_findings(office):
    """Lint whatever templates have been pulled for this office."""
    try:
        text, _src = T.load_text(office=office["office"])
    except Exception as e:  # noqa: BLE001 — not pulled yet is not a failure
        return None, "no templates pulled yet ({})".format(
            type(e).__name__)
    bodies = T.parse_bodies(text)
    states = T.parse_activation(text)
    findings, personas = T.lint(bodies, states, office)
    return (findings, personas), None


def apply_address_history(office):
    """Tell the address checks when this office moved, before anything
    reads a message.

    Without this, the day an office types its new address in, every
    correct message it sent from the old one reads as sending people to
    the wrong building — and a message still naming the old address after
    the move passes quietly. Megan's move to Frisco is 2026-10-02."""
    prev = (office.get("address_prev") or "").strip()
    when = (office.get("address_changed") or "").strip()
    cur = (office.get("address") or "").strip()
    if not cur:
        return None
    changed = None
    if prev and when:
        for fmt in ("%m-%d-%Y", "%Y-%m-%d", "%m/%d/%Y"):
            try:
                changed = dt.datetime.strptime(when, fmt).date()
                break
            except ValueError:
                continue
    RB.set_address_history(office["office"], cur,
                           prev if changed else None, changed)
    return changed


def message_findings(office):
    """Grammar, deflection and the house rules, from the week already on
    disk. Returns None when nothing has been pulled."""
    oid = office["office"]
    recs, _s = A.load_office(oid)
    log, _s2 = A.load_log(oid)
    if not recs or not log:
        return None
    convos = A.log_conversations(log, A.booked_index(recs))
    errs = A.text_errors(convos)
    dodged = A.dodged_questions(convos)
    coaching = A.who_to_talk_to(convos, oid)
    return {"errors": errs, "dodged": dodged, "coaching": coaching,
            "people": len(convos),
            # Megan 2026-10-01, the four things the document has to show
            # besides the counts: "best times and worst times", "what common
            # complaints from applicants are", "when texts aren't delivered
            # and why", and the real messages behind each person's row.
            "best_hours": A.best_hours_label(convos),
            "worst_hours": A.worst_hours_label(convos),
            "hours": A.hourly_reply(convos),
            "complaints": A.complaints(convos),
            "speed": A.reply_speed_by_sender(convos),
            "median_reply": (statistics.median(A.applicant_reply_speed(convos))
                             if A.applicant_reply_speed(convos) else None),
            "human_senders": sorted({
                (m.get("sent_by") or "").strip()
                for c in convos.values() for m in c["msgs"]
                if (m.get("sent_by") or "").strip()
                and not A.is_ai(m)}),
            "delivery": A.delivery_reasons(log)}


CSS = """
body{font-family:Georgia,'Times New Roman',serif;color:#111;max-width:52em;
     margin:2.2em auto;padding:0 1.2em;line-height:1.5}
h1{font-size:1.6em;margin:0 0 .1em}
h2{font-size:1.15em;margin:2em 0 .5em;border-bottom:2px solid #111;
   padding-bottom:.2em}
h3{font-size:1em;margin:1.4em 0 .4em}
.date{color:#666;margin:0 0 1.5em}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:.6em 0 1em}
table{border-collapse:collapse;font-size:.95em}
ul{padding-left:1.4em;margin:.4em 0}
li{margin:.25em 0}
@media (max-width:640px){body{margin:1.2em auto;font-size:15px}
  table{font-size:.88em}th,td{padding:.25em .45em}}
th,td{border:1px solid #ccc;padding:.3em .7em;text-align:left}
th{background:#f2f2f2}
td.n{text-align:right}
details{margin:.35em 0;border:1px solid #ddd;border-radius:4px;padding:.4em .7em;
        background:#fafafa}
details[open]{background:#fff}
summary{cursor:pointer;font-weight:bold}
summary::marker{color:#888}
blockquote{margin:.5em 0 .5em 1em;padding:.35em .8em;border-left:3px solid #bbb;
           background:#f7f7f7;font-size:.95em;color:#222}
blockquote .hit{display:block;color:#a00;font-size:.85em;margin-bottom:.2em}
.gap{background:#fff8e1;border:1px solid #e6c200;padding:.8em 1em;border-radius:4px}
.none{color:#666;font-style:italic}
.big{font-size:3.1em;font-weight:bold;margin:.1em 0 0;line-height:1}
.big.ok{color:#156E46}
.big.miss{color:#A8322A}
.lede{margin:.2em 0 .8em}
b.down{color:#A8322A}
b.up{color:#156E46}
.byai{color:#666;font-size:.85em;font-style:normal}
""" + GC.CSS


def _mins(m):
    """4.0 -> '4 min', 95 -> '1 hr 35 min'. No bare decimals in a document
    somebody reads out loud."""
    m = int(round(m))
    if m < 60:
        return "{} min".format(m)
    return "{} hr {} min".format(m // 60, m % 60) if m % 60 else \
        "{} hr".format(m // 60)


def esc(t):
    """No template engine on the Lucys — escape by hand."""
    return (str(t).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def settings_findings(office, median_reply=None, template_names=None,
                      human_senders=None):
    """The AI Settings page and the AI's own canned answers, which is
    where most of what the message audit sees downstream is decided."""
    oid = office["office"]
    info, prefs = AIS.load(oid)
    setting = AIS.lint(info, prefs, office, median_reply, template_names,
                       human_senders)
    rows, src = ESC.load(oid)
    esc = ESC.lint(rows, office) if src else [
        ("NOT PULLED", "no escalation rows pulled for this office")]
    return {"settings": setting, "escalations": esc, "rows": len(rows),
            "window": AIS.window(prefs or {})}


def write_report(office, tmpl, msgs, moved, tab, path,
                 wlabels=None, conv=None, window=None, ai=None,
                 rows=None, lead=None):
    o = office
    L = []
    add = L.append
    name = o.get("icd_name", "") or o["office"]
    add("<!doctype html><html><head><meta charset='utf-8'>")
    add("<title>Recruiting audit — {}</title>".format(esc(name)))
    add("<style>{}</style></head><body>".format(CSS))
    add("<h1>Recruiting audit — {}</h1>".format(esc(name)))
    add("<p class='date'>Account {} · {:%d %b %Y}</p>".format(
        esc(o["office"]), dt.date.today()))

    # Megan 2026-10-06: "the top should breakdown what the most important
    # things to address are". Everything below is already measured; the card
    # only ranks it, so the first thing read is the thing to fix.
    add(GC.render(GC.build(o, conv=conv, msgs=msgs, ai=ai, rows=rows,
                           moved=moved, tmpl=tmpl, lead=lead,
                           gaps=O.missing_fields(o)), esc))

    # ---------------- templates ----------------
    # Megan 2026-10-01: "This is the MAIN thing we need to get as high as
    # possible - goal at 80%+". So it opens the document, above everything
    # else the auditor found.
    add("<h2>Call list retention</h2>")
    add("<p class='lede'>Of the people whose resume came in, how many "
        "we booked an interview with.</p>")
    if not conv or not conv.get("ok"):
        add("<p class='none'>Not measured: {}.</p>".format(
            esc((conv or {}).get("why", "no data"))))
        add("<p class='none'>It needs the Call List export "
            "(Call Hub &rarr; Export, saved as callList_{}.xls) and the "
            "Activity Report pull.</p>".format(esc(o["office"])))
    else:
        hit = conv["rate"] >= conv["goal"]
        add("<p class='big {}'>{:.0f}%</p>".format(
            "ok" if hit else "miss", conv["rate"]))
        add("<p class='lede'><b>{:,} of the {:,} people whose resume came in "
            "got booked into a 1st round.</b> The goal is {:.0f}%.</p>".format(
                conv["booked"], conv["applied"], conv["goal"]))
        if hit:
            add("<p>Above goal.</p>")
        else:
            add("<p><b>{:,} more bookings that week would have hit "
                "{:.0f}%.</b></p>".format(conv["short_by"], conv["goal"]))
        st = CL.stuck(o["office"], window[0], window[1]) if window else []
        if st:
            add("<p class='lede'>The {:,} who were not booked are sitting "
                "here:</p>".format(conv["waiting"]))
            add("<div class='scroll'><table><tr><th>Where they are</th>"
                "<th>How many</th><th>Share</th></tr>")
            for r in st:
                add("<tr><td>{}</td><td class='n'>{:,}</td>"
                    "<td class='n'>{:.0f}%</td></tr>".format(
                        esc(r["status"]), r["n"], r["share"]))
            add("</table></div>")
        # Megan 2026-10-06: "remove". The source trail and the caveat that
        # went with it are out of the document at her instruction. Keeping
        # them here so the next reader of this code still knows: booked is
        # First Interview Date rows on p=704, resumes received is the Call
        # List export (p=4000) plus the booked, and that second part
        # ASSUMES people come off the list once booked \u2014 an office that
        # also clears it by hand reads higher than it is.
        pass
    add("")

    # The AI's own settings and canned answers come before the templates:
    # one row here is what a thousand conversations end up saying.
    add("<h2>The AI&rsquo;s settings</h2>")
    if not ai:
        add("<p class='none'>Not pulled for this office yet.</p>")
    else:
        for label, items, why in (("Settings", ai["settings"], AIS.WHY),
                                  ("What it replies to applicants",
                                   ai["escalations"],
                                   ESC.WHY)):
            add("<h3>{}</h3>".format(esc(label)))
            if not items:
                add("<p>Nothing flagged.</p>")
                continue
            bykind = collections.defaultdict(list)
            for kind, text in items:
                bykind[kind].append(text)
            for kind, texts in sorted(bykind.items(),
                                      key=lambda kv: -len(kv[1])):
                title, reason = why.get(kind, (kind, ""))
                add("<h4 style='margin:14px 0 4px;font-size:14.5px'>{}{}</h4>"
                    .format(esc(title),
                            "" if len(texts) == 1
                            else " &mdash; {}".format(len(texts))))
                if reason:
                    add("<p>{}</p>".format(esc(reason)))
                add("<ul>")
                for t in texts:
                    add("<li>{}</li>".format(esc(t)))
                add("</ul>")
        if ai.get("window") is not None:
            add("<p class='none'>Applicants get {} minutes to accept a time "
                "(the first buffer minus the second).</p>".format(ai["window"]))
    add("")

    add("<h2>Templates</h2>")
    if tmpl is None:
        add("<p class='none'>No templates pulled for this office yet.</p>")
    else:
        findings, personas = tmpl
        if not findings:
            add("<p>Nothing flagged.</p>")
        else:
            bykind = collections.defaultdict(list)
            for kind, msg in findings:
                bykind[kind].append(msg)
            # One block per problem: what it is in plain words, why it
            # matters said ONCE, then which templates. The old version
            # repeated its own boilerplate on all seven lines.
            for kind, msgs_ in sorted(bykind.items(),
                                      key=lambda kv: -len(kv[1])):
                title, why = T.WHY.get(kind, (kind, ""))
                add("<h3>{} &mdash; {} template{}</h3>".format(
                    esc(title), len(msgs_), "" if len(msgs_) == 1 else "s"))
                if why:
                    add("<p>{}</p>".format(esc(why)))
                add("<ul>")
                for m in msgs_:
                    add("<li>{}</li>".format(esc(m)))
                add("</ul>")
        if personas and len(personas) > 1:
            add("<p><b>Applicants hear from {} different names.</b> The live "
                "templates sign {} \u2014 so the same applicant can get two "
                "messages from two people.</p>".format(
                    len(personas),
                    esc(", ".join("{} ({} template{})".format(
                        n, c, "" if c == 1 else "s")
                        for n, c in personas.most_common()))))
        elif personas:
            who, c = personas.most_common(1)[0]
            add("<p>All {} live template{} sign <b>{}</b>. Only switched-on "
                "templates are counted \u2014 a name sitting in a "
                "deactivated one is nobody\u2019s experience of this "
                "office.</p>".format(c, "" if c == 1 else "s", esc(who)))

    # ---------------- recruiter texts ----------------
    add("<h2>Recruiter texts</h2>")
    if msgs is None:
        add("<p class='none'>No message pull on disk for this office.</p>")
    else:
        add("<p class='lede'>Across {:,} conversations in the last pull:</p>"
            .format(msgs["people"]))
        ek = collections.Counter(e["kind"] for e in msgs["errors"])
        dk = collections.Counter(e["kind"] for e in msgs["dodged"])
        if ek or dk:
            # Megan 2026-10-06: "this should be able to be expanded to see
            # these questions. We need to know if it's a person or AI so
            # that we can get it corrected" — a count alone cannot be acted
            # on, and the fix is a different one for each: a person gets
            # coached, the AI gets its message edited in AppStream.
            humans = set(msgs.get("human_senders") or [])

            def who_sent(sender):
                sender = (sender or "").strip()
                if not sender:
                    return "unknown", "unknown"
                return sender, ("a person" if sender in humans else "the AI")

            def fault_block(label, entries):
                people = collections.Counter()
                for e in entries:
                    people[who_sent(e.get("sender"))[1]] += 1
                mix = ", ".join("{} by {}".format(c, w)
                                for w, c in people.most_common())
                add("<details><summary>{} &mdash; {} ({})</summary>".format
                    (esc(label), len(entries), esc(mix)))
                for e in entries[:12]:
                    sender, kind = who_sent(e.get("sender"))
                    add("<blockquote><span class='hit'>{}</span>"
                        "<span class='byai'>{} &middot; {}</span><br>".format(
                            esc(e.get("detail") or e.get("bucket") or ""),
                            esc(sender), esc(kind)))
                    if e.get("question"):
                        # A dodge is only legible as the pair: what they
                        # asked, and what they got back instead.
                        add("<b>They asked:</b> {}<br>"
                            "<b>We replied:</b> {}".format(
                                esc(e["question"]), esc(e.get("reply") or "")))
                    else:
                        add(esc(e.get("body") or ""))
                    add("</blockquote>")
                if len(entries) > 12:
                    add("<p class='none'>&hellip; and {} more.</p>".format(
                        len(entries) - 12))
                add("</details>")

            by_kind = collections.defaultdict(list)
            for e in msgs["errors"]:
                by_kind[e["kind"]].append(e)
            for e in msgs["dodged"]:
                by_kind["questions " + e["kind"]].append(e)
            for label, _n in (ek + dk).most_common():
                key = label if label in by_kind else "questions " + label
                if by_kind.get(key):
                    fault_block(key, by_kind[key])
        else:
            add("<p>Nothing flagged.</p>")

        if msgs["coaching"]:
            add("<h3>Who to talk to</h3>")
            add("<p class='lede'>Open a name to read the messages themselves "
                "&mdash; a count is something to argue with, the message is "
                "not.</p>")
            by = collections.defaultdict(list)
            for e in msgs["coaching"]:
                by[e["sender"]].append(e)
            for who, es in sorted(
                    by.items(), key=lambda kv: -sum(e["count"] for e in kv[1])):
                add("<details><summary>{} &mdash; {}</summary>".format(
                    esc(who), esc("; ".join(
                        "{} ({}x)".format(e["issue"], e["count"]) for e in es))))
                for e in sorted(es, key=lambda e: -e["count"]):
                    add("<p><b>{}</b> &mdash; {} time{}</p>".format(
                        esc(e["issue"]), e["count"],
                        "" if e["count"] == 1 else "s"))
                    for ex in e.get("examples", []):
                        add("<blockquote><span class='hit'>{}</span>{}"
                            "</blockquote>".format(
                                esc(ex["hit"]), esc(ex["body"])))
                    if e["count"] > len(e.get("examples", [])):
                        add("<p class='none'>&hellip; and {} more like it.</p>"
                            .format(e["count"] - len(e.get("examples", []))))
                add("</details>")

        # ---------------- best / worst times ----------------
        add("<h2>When to text</h2>")
        hours = msgs.get("hours") or []
        if not hours:
            add("<p class='none'>Not enough sends in any single hour to rank "
                "them. An hour needs {} delivered texts before it counts "
                "&mdash; otherwise a 4-send hour at 100% takes the top slot "
                "every week.</p>".format(A.MIN_HOUR_SAMPLE))
        else:
            add("<p class='lede'><b>Best:</b> {}<br><b>Worst:</b> {}</p>"
                .format(esc(msgs["best_hours"]), esc(msgs["worst_hours"])))
            add("<p class='none'>Reply rate is the share of delivered texts "
                "that got an answer within two hours. Hours with under {} "
                "delivered texts are left out.</p>".format(A.MIN_HOUR_SAMPLE))
            add("<details><summary>Every hour, ranked</summary>")
            add("<div class='scroll'><table><tr><th>Hour sent</th><th>Delivered</th>"
                "<th>Replied</th><th>Rate</th></tr>")
            for r in hours:
                add("<tr><td>{}</td><td class='n'>{:,}</td><td class='n'>{:,}"
                    "</td><td class='n'>{:.0f}%</td></tr>".format(
                        esc(A.clock(r["hour"])), r["sent"], r["replied"],
                        r["rate"]))
            add("</table></div></details>")

        # ---------------- how fast they reply ----------------
        add("<h2>How fast recruiters reply</h2>")
        sp = msgs.get("speed") or []
        if not sp:
            add("<p class='none'>Nobody has enough replies on record to time "
                "them.</p>")
        else:
            add("<p class='lede'>From an applicant\u2019s message to that "
                "person\u2019s next text back. Fastest first. Anyone with "
                "fewer than 10 replies is left out.</p>")
            add("<div class='scroll'><table><tr><th>Who</th>"
                "<th>Replies</th><th>Usual wait</th><th>Within 5 min</th>"
                "<th>Within 1 hr</th><th>Within 2 hrs</th>"
                "<th>Within 3 hrs</th><th>Over 4 hours</th></tr>")
            for r in sp:
                add("<tr><td>{}</td><td class='n'>{:,}</td>"
                    "<td class='n'>{}</td><td class='n'>{:.0f}%</td>"
                    "<td class='n'>{:.0f}%</td><td class='n'>{:.0f}%</td>"
                    "<td class='n'>{:.0f}%</td>"
                    "<td class='n'>{:.0f}%</td></tr>".format(
                        esc(r["who"]), r["n"], _mins(r["median"]),
                        r["within_5"], r.get("within_60", 0),
                        r.get("within_120", 0), r.get("within_180", 0),
                        r["over_4h"]))
            add("</table></div>")
            slow = [r for r in sp if r["over_4h"] >= 10]
            if slow:
                add("<p>{} leave more than one reply in ten over four "
                    "hours: {}. An applicant who has moved on by then is "
                    "not coming back.</p>".format(
                        "One person leaves" if len(slow) == 1
                        else "{} people leave".format(len(slow)),
                        esc(", ".join("{} ({:.0f}%)".format(
                            r["who"], r["over_4h"]) for r in slow))))

        # ---------------- complaints ----------------
        add("<h2>What applicants complained about</h2>")
        comp = msgs.get("complaints") or {}
        total_c = sum(len(v) for v in comp.values())
        if not total_c:
            add("<p>Nobody complained about us in this pull.</p>")
        else:
            add("<p class='lede'>{} message{} from applicants, by what went "
                "wrong. One message counts once, under the first thing it "
                "names.</p>".format(total_c, "" if total_c == 1 else "s"))
            for label, items in sorted(comp.items(), key=lambda kv: -len(kv[1])):
                add("<details><summary>{} ({})</summary>".format(
                    esc(label), len(items)))
                for it in items[:12]:
                    who = it.get("name") or ""
                    when = it.get("when")
                    tag = " &mdash; {:%d %b}".format(when) if when else ""
                    add("<blockquote><span class='hit'>{}{}</span>{}"
                        "</blockquote>".format(esc(who), tag, esc(it["body"])))
                if len(items) > 12:
                    add("<p class='none'>&hellip; and {} more.</p>".format(
                        len(items) - 12))
                add("</details>")

        # ---------------- undelivered ----------------
        add("<h2>Texts that never arrived</h2>")
        d = msgs.get("delivery") or {}
        if not d.get("sent"):
            add("<p class='none'>No outbound texts in the pull.</p>")
        else:
            rate = 100.0 * d["undelivered"] / d["sent"]
            add("<p class='lede'><b>{:,} of {:,} texts never arrived "
                "({:.1f}%).</b></p>".format(d["undelivered"], d["sent"], rate))
            bad = [(k, v) for k, v in d["by_status"].most_common()
                   if k.lower() != "delivered"]
            if bad:
                add("<div class='scroll'><table>"
                    "<tr><th>What AppStream recorded</th>"
                    "<th>How many</th></tr>")
                for k, v in bad:
                    add("<tr><td>{}</td><td class='n'>{:,}</td></tr>".format(
                        esc(k), v))
                add("</table></div>")
            fr, lr = d.get("first_rate"), d.get("later_rate")
            if fr is not None and lr is not None:
                add("<p><b>Why:</b> {:.0f}% of first texts to a person fail, "
                    "but {:.0f}% of the later ones do.".format(fr, lr))
                if lr > fr + 2:
                    add(" The failure rate climbing with each extra text is "
                        "the carrier flagging the number, not a bad phone "
                        "number &mdash; the undelivered texts and the "
                        "\"texted 4+ times, no reply\" people are the same "
                        "problem.")
                add("</p>")

    # ---------------- retention ----------------
    add("<h2>Did the people they booked show up?</h2>")
    if not tab:
        add("<p class='none'>Not enough weeks pulled.</p>")
    else:
        periods = list(tab)
        wl = wlabels or {}
        names = R.known_names(o["office"])
        bookers = sorted({b for p in tab for (b, k) in tab[p] if k == "n"},
                         key=lambda b: -sum(tab[p][(b, "n")] for p in tab))[:12]

        def pct(p, b):
            n = tab[p][(b, "n")]
            return "{:.0f}%".format(100.0 * tab[p][(b, "s")] / n) if n else "&mdash;"

        # Megan 2026-10-06: "remove". For the next reader of this code:
        # every number is the share of that booker's 1st rounds where the
        # applicant turned up; columns are recruiting weeks Mon-Fri; an
        # interview counts as attended unless AppStream says No Show.
        add("<div class='scroll'><table><tr><th>Who booked it</th>" +
            "".join("<th>{}</th>".format(esc(wl.get(p) or R.week_label(p)))
                    for p in periods) + "</tr>")
        for b in bookers:
            add("<tr><td>{}</td>{}</tr>".format(
                esc(R.expand_name(b, names)),
                "".join("<td class='n'>{}</td>".format(pct(p, b))
                        for p in periods)))
        add("</table></div>")

        add("<details><summary>How many interviews each percentage is based "
            "on</summary><div class='scroll'><table><tr><th>Who booked it</th>"
            + "".join("<th>{}</th>".format(esc(wl.get(p) or R.week_label(p)))
                      for p in periods) + "</tr>")
        for b in bookers:
            add("<tr><td>{}</td>{}</tr>".format(
                esc(R.expand_name(b, names)),
                "".join("<td class='n'>{}</td>".format(
                    tab[p][(b, "n")] or "&mdash;") for p in periods)))
        add("</table></div><p class='none'>A week under {} bookings is left "
            "out of the comparison below &mdash; five bookings at 20% is one "
            "bad morning, not a trend.</p></details>".format(R.MIN_N))

        # Only actual movement. The old list printed every booker including
        # "33% (was 33%)", which is the opposite of news (Megan 2026-10-01).
        real = [m for m in (moved or []) if abs(m[1] - m[2]) >= R.DROP]
        add("<h3>What changed in the latest week</h3>")
        if not real:
            add("<p>Nobody moved more than {:.0f}% against their own "
                "usual rate.</p>".format(R.DROP))
        else:
            # Megan 2026-10-06: "remove". Still true, and still what the
            # numbers below mean: each person is scored against their OWN
            # trailing rate, never against each other.
            add("<ul>")
            for b, rate, trail, n in real:
                dd = rate - trail
                add("<li><b>{}</b> &mdash; {:.0f}% this week against a usual "
                    "{:.0f}%. <b class='{}'>{} {:.0f}%</b>, on {} "
                    "booking{}.</li>"
                    .format(esc(R.expand_name(b, names)), rate, trail,
                            "down" if dd < 0 else "up",
                            "Down" if dd < 0 else "Up", abs(dd), n,
                            "" if n == 1 else "s"))
            add("</ul>")
            steady = len(moved or []) - len(real)
            if steady:
                add("<p class='none'>{} other booker{} stayed within "
                    "{:.0f}% of their usual.</p>".format(
                        steady, "" if steady == 1 else "s", R.DROP))

    add("</body></html>")
    path.write_text("\n".join(x for x in L if x), encoding="utf-8")
    return path


def latest_window(rows):
    """(first, last) interview date of the most recent week pulled, so the
    conversion is measured over the same days the rest of the report is."""
    spans = R.week_spans(rows or [])
    if not spans:
        return None
    return spans[list(R.table(rows, "week"))[-1]]


def report_path(office_id):
    """One place that knows the filename, so the bot and the runner agree."""
    return OUTPUT / "icd-audit-{}.html".format(office_id)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="", help="one id; default every active")
    ap.add_argument("--skip-templates", action="store_true")
    a = ap.parse_args(argv)

    offs, src = O.load()
    if a.office:
        offs = [o for o in offs if o["office"] == a.office]
        if not offs:
            print("[icd_audit] {} is not in the office tab".format(a.office))
            return 1
    print("[icd_audit] {} office(s), config from {}".format(len(offs), src),
          flush=True)

    OUTPUT.mkdir(exist_ok=True)
    rc = 0
    for o in offs:
        tmpl = None
        if not a.skip_templates:
            tmpl, why = template_findings(o)
            if why:
                print("   {}: {}".format(o["office"], why), flush=True)
        moved_on = apply_address_history(o)
        if moved_on:
            print("   {}: address history applied, moved {:%d %b}".format(
                o["office"], moved_on), flush=True)
        msgs = message_findings(o)
        rows = R.load(o["office"])
        tab = R.table(rows, "week") if rows else {}
        moved = R.changes(tab) if tab else []
        path = report_path(o["office"])
        window = latest_window(rows)
        conv = CL.conversion(o["office"], window[0], window[1]) if window \
            else None
        median = None
        senders = None
        if msgs is not None:
            median = msgs.get("median_reply")
            senders = msgs.get("human_senders")
        signs = None
        if tmpl and tmpl[1]:
            signs = list(tmpl[1])
        ai = settings_findings(o, median, signs, senders)
        lead = LT.measure(o)
        write_report(o, tmpl, msgs, moved, tab, path,
                     R.week_labels(rows) if rows else {}, conv, window, ai,
                     rows=rows, lead=lead)
        nt = len(tmpl[0]) if tmpl else 0
        nm = (len(msgs["errors"]) + len(msgs["dodged"])) if msgs else 0
        big = [m for m in moved if m[1] - m[2] <= -R.DROP]
        print("   {:<7} {:<22} templates {:>3} · texts {:>3} · dropped {:>2}"
              "  -> {}".format(o["office"], o.get("icd_name", "")[:22], nt, nm, len(big),
                               path.name), flush=True)
        if big:
            rc = 0  # a drop is a finding to read, not a run failure
    return rc


if __name__ == "__main__":
    sys.exit(main())
