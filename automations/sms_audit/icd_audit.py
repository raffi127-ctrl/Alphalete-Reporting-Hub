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
output/icd-audit-<office>.md and prints a summary.
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
            "people": len(convos)}


def write_report(office, tmpl, msgs, moved, tab, path):
    o = office
    L = []
    add = L.append
    add("# Recruiting audit — {} ({})".format(o["label"], o["office"]))
    add("")
    add("_{:%d %b %Y}_".format(dt.date.today()))
    add("")

    gaps = O.missing_fields(o)
    if gaps:
        add("## Checks NOT run")
        add("")
        add("Nobody has told the auditor what is correct for this office, so "
            "these are skipped rather than passed:")
        add("")
        for g in gaps:
            add("- {}".format(g))
        add("")
        add("Fill the row in the **Recruiting Audit Offices** tab and they "
            "start running.")
        add("")

    add("## Templates")
    add("")
    if tmpl is None:
        add("_No templates pulled for this office yet._")
    else:
        findings, personas = tmpl
        if not findings:
            add("Nothing flagged.")
        else:
            by = collections.Counter(k for k, _m in findings)
            add("| What | How many |")
            add("|---|---|")
            for k, n in by.most_common():
                add("| {} | {} |".format(k, n))
            add("")
            for kind, msg in findings:
                add("- **{}** — {}".format(kind, msg))
        if personas and len(personas) > 1:
            add("")
            add("**{} different names front this office:** {}. Applicants "
                "get a different person each message.".format(
                    len(personas),
                    ", ".join("{} ({})".format(n, c)
                              for n, c in personas.most_common())))
    add("")

    add("## Recruiter texts")
    add("")
    if msgs is None:
        add("_No message pull on disk for this office._")
    else:
        add("Across {:,} conversations in the last pull:".format(msgs["people"]))
        add("")
        ek = collections.Counter(e["kind"] for e in msgs["errors"])
        dk = collections.Counter(e["kind"] for e in msgs["dodged"])
        add("| | |")
        add("|---|---|")
        for k, n in ek.most_common():
            add("| {} | {} |".format(k, n))
        for k, n in dk.most_common():
            add("| questions {} | {} |".format(k, n))
        add("")
        if msgs["coaching"]:
            add("### Who to talk to")
            add("")
            by = collections.defaultdict(list)
            for e in msgs["coaching"]:
                by[e["sender"]].append(e)
            for who, es in sorted(by.items(),
                                  key=lambda kv: -sum(e["count"] for e in kv[1])):
                add("- **{}** — {}".format(who, "; ".join(
                    "{} ({}x)".format(e["issue"], e["count"]) for e in es)))
            add("")

    add("## Retention — who booked them")
    add("")
    if not tab:
        add("_Not enough weeks pulled._")
    else:
        periods = list(tab)
        add("| Booker | " + " | ".join(str(p) for p in periods) + " |")
        add("|---" * (len(periods) + 1) + "|")
        bookers = sorted({b for p in tab for (b, k) in tab[p] if k == "n"},
                         key=lambda b: -sum(tab[p][(b, "n")] for p in tab))
        for b in bookers[:12]:
            cells = []
            for p in periods:
                n = tab[p][(b, "n")]
                cells.append("{:.0f}% / {}".format(
                    100.0 * tab[p][(b, "s")] / n, n) if n else "—")
            add("| {} | {} |".format(b, " | ".join(cells)))
        add("")
        if moved:
            add("### What moved in the latest week")
            add("")
            add("Each booker against their OWN trailing average — bookers "
                "differ permanently, so only a change is news.")
            add("")
            for b, rate, trail, n in moved:
                d = rate - trail
                mark = " **— down {:.0f} points**".format(-d) if d <= -R.DROP else ""
                add("- {}: {:.0f}% (was {:.0f}%) on {} bookings{}".format(
                    b, rate, trail, n, mark))
    add("")
    path.write_text("\n".join(L), encoding="utf-8")
    return path


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
        path = OUTPUT / "icd-audit-{}.md".format(o["office"])
        write_report(o, tmpl, msgs, moved, tab, path)
        nt = len(tmpl[0]) if tmpl else 0
        nm = (len(msgs["errors"]) + len(msgs["dodged"])) if msgs else 0
        big = [m for m in moved if m[1] - m[2] <= -R.DROP]
        print("   {:<7} {:<22} templates {:>3} · texts {:>3} · dropped {:>2}"
              "  -> {}".format(o["office"], o["label"][:22], nt, nm, len(big),
                               path.name), flush=True)
        if big:
            rc = 0  # a drop is a finding to read, not a run failure
    return rc


if __name__ == "__main__":
    sys.exit(main())
