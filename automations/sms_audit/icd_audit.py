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
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.sms_audit import analyze as A
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
            "delivery": A.delivery_reasons(log)}


CSS = """
body{font-family:Georgia,'Times New Roman',serif;color:#111;max-width:52em;
     margin:2.2em auto;padding:0 1.2em;line-height:1.5}
h1{font-size:1.6em;margin:0 0 .1em}
h2{font-size:1.15em;margin:2em 0 .5em;border-bottom:2px solid #111;
   padding-bottom:.2em}
h3{font-size:1em;margin:1.4em 0 .4em}
.date{color:#666;margin:0 0 1.5em}
table{border-collapse:collapse;margin:.6em 0 1em;font-size:.95em}
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
.lede{margin:.2em 0 .8em}
"""


def esc(t):
    """No template engine on the Lucys — escape by hand."""
    return (str(t).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def write_report(office, tmpl, msgs, moved, tab, path):
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

    gaps = O.missing_fields(o)
    if gaps:
        add("<h2>Checks NOT run</h2>")
        add("<div class='gap'><p class='lede'>Nobody has told the auditor "
            "what is correct for this office, so these are skipped rather "
            "than passed:</p><ul>")
        for g in gaps:
            add("<li>{}</li>".format(esc(g)))
        add("</ul><p>Run the command again and fill these in, and they start "
            "running.</p></div>")

    # ---------------- templates ----------------
    add("<h2>Templates</h2>")
    if tmpl is None:
        add("<p class='none'>No templates pulled for this office yet.</p>")
    else:
        findings, personas = tmpl
        if not findings:
            add("<p>Nothing flagged.</p>")
        else:
            by = collections.Counter(k for k, _m in findings)
            add("<table><tr><th>What</th><th>How many</th></tr>")
            for k, n in by.most_common():
                add("<tr><td>{}</td><td class='n'>{}</td></tr>".format(
                    esc(k), n))
            add("</table>")
            bykind = collections.defaultdict(list)
            for kind, msg in findings:
                bykind[kind].append(msg)
            for kind, msgs_ in sorted(bykind.items(), key=lambda kv: -len(kv[1])):
                add("<details><summary>{} ({})</summary><ul>".format(
                    esc(kind), len(msgs_)))
                for m in msgs_:
                    add("<li>{}</li>".format(esc(m)))
                add("</ul></details>")
        if personas and len(personas) > 1:
            add("<p><b>{} different names front this office:</b> {}. "
                "Applicants get a different person each message.</p>".format(
                    len(personas),
                    esc(", ".join("{} ({})".format(n, c)
                                  for n, c in personas.most_common()))))

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
            add("<table><tr><th>What</th><th>How many</th></tr>")
            for k, n in ek.most_common():
                add("<tr><td>{}</td><td class='n'>{}</td></tr>".format(esc(k), n))
            for k, n in dk.most_common():
                add("<tr><td>questions {}</td><td class='n'>{}</td></tr>".format(
                    esc(k), n))
            add("</table>")
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
            add("<table><tr><th>Hour sent</th><th>Delivered</th>"
                "<th>Replied</th><th>Rate</th></tr>")
            for r in hours:
                add("<tr><td>{}</td><td class='n'>{:,}</td><td class='n'>{:,}"
                    "</td><td class='n'>{:.0f}%</td></tr>".format(
                        esc(A.clock(r["hour"])), r["sent"], r["replied"],
                        r["rate"]))
            add("</table></details>")

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
                add("<table><tr><th>What AppStream recorded</th>"
                    "<th>How many</th></tr>")
                for k, v in bad:
                    add("<tr><td>{}</td><td class='n'>{:,}</td></tr>".format(
                        esc(k), v))
                add("</table>")
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
    add("<h2>Retention &mdash; who booked them</h2>")
    if not tab:
        add("<p class='none'>Not enough weeks pulled.</p>")
    else:
        periods = list(tab)
        add("<p class='none'>Show rate, then how many bookings it is off.</p>")
        add("<table><tr><th>Booker</th>" +
            "".join("<th>{}</th>".format(esc(p)) for p in periods) + "</tr>")
        bookers = sorted({b for p in tab for (b, k) in tab[p] if k == "n"},
                         key=lambda b: -sum(tab[p][(b, "n")] for p in tab))
        for b in bookers[:12]:
            cells = []
            for p in periods:
                n = tab[p][(b, "n")]
                cells.append("<td class='n'>{}</td>".format(
                    "{:.0f}% / {}".format(100.0 * tab[p][(b, "s")] / n, n)
                    if n else "&mdash;"))
            add("<tr><td>{}</td>{}</tr>".format(esc(b), "".join(cells)))
        add("</table>")
        if moved:
            add("<h3>What moved in the latest week</h3>")
            add("<p class='lede'>Each booker against their OWN trailing "
                "average &mdash; bookers differ permanently, so only a change "
                "is news.</p><ul>")
            for b, rate, trail, n in moved:
                dd = rate - trail
                mark = (" <b>&mdash; down {:.0f} points</b>".format(-dd)
                        if dd <= -R.DROP else "")
                add("<li>{}: {:.0f}% (was {:.0f}%) on {} bookings{}</li>".format(
                    esc(b), rate, trail, n, mark))
            add("</ul>")

    add("</body></html>")
    path.write_text("\n".join(x for x in L if x), encoding="utf-8")
    return path


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
        msgs = message_findings(o)
        rows = R.load(o["office"])
        tab = R.table(rows, "week") if rows else {}
        moved = R.changes(tab) if tab else []
        path = report_path(o["office"])
        write_report(o, tmpl, msgs, moved, tab, path)
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
