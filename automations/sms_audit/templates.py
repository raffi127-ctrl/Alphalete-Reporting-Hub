"""Template lint — read the saved SMS templates an `as_templates_probe` run
parked in the control sheet and flag the ones that are broken before a single
applicant is texted.

The thread audit (analyze.py) reads what WAS sent. This reads what WILL be
sent, which catches a class of problem the threads can only show you one
applicant at a time — a bad link in an activated template reaches everybody.

  python -m automations.sms_audit.templates --office 11280   # that office's tab
  python -m automations.sms_audit.templates --file x.txt     # a saved copy

READ-ONLY. Prints findings and exits 1 if any are found, so it can gate.

Checks:
  * a URL whose host holds a look-alike letter (Cyrillic о in "zоom.us") —
    the link is dead and no one reading it can see why;
  * a merge field that will not fill (a bare name with no marker around it is
    normal in this system, so only known-broken spellings are flagged);
  * an activated template with no "Reply STOP to opt out" — AppStream's own
    deliverability checklist, item 3;
  * which persona each template signs, so four different names fronting one
    office shows up as the one fact it is.
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
import unicodedata
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
PROBE_TAB = "AS Templates Probe"          # legacy single-office tab
PROBE_TAB_PREFIX = "AS Templates"         # per-office: "AS Templates 11280"

# phase 2 of the probe prints one header line then the body:
#   [Section / Template Name] textarea 0:
BODY_HEAD = re.compile(r"^\[(?P<section>[^/\]]+?)\s*/\s*(?P<name>[^\]]+?)\]\s+textarea\s+(\d+):\s*$")
# phase 1 prints the section list with its activation state
ACTIVATION = re.compile(r"^(?P<name>.+?Template #\d+|\S.*?)\s*\t?\s*(?P<state>Not Activated|Activated)\b")
PERSONA = re.compile(r"\b(?:this is|it'?s)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)")


def load_text(path=None, office=None):
    if path:
        return Path(path).read_text(encoding="utf-8"), str(path)
    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(CONTROL_SHEET_ID)
    tab = "{} {}".format(PROBE_TAB_PREFIX, office) if office else PROBE_TAB
    ws = sh.worksheet(tab)
    return "\n".join(r[0] for r in ws.get_all_values() if r), "tab '{}'".format(tab)


def parse_bodies(text):
    """[(section, template_name, body)] from the probe's phase-2 output."""
    out, cur, buf = [], None, []
    for line in text.splitlines():
        m = BODY_HEAD.match(line.strip())
        if m:
            if cur:
                out.append((cur[0], cur[1], "\n".join(buf).strip()))
            cur, buf = (m.group("section").strip(), m.group("name").strip()), []
            continue
        if cur is not None:
            if line.startswith("opening Edit #") or line.startswith("====="):
                out.append((cur[0], cur[1], "\n".join(buf).strip()))
                cur, buf = None, []
            else:
                buf.append(line)
    if cur:
        out.append((cur[0], cur[1], "\n".join(buf).strip()))
    return [t for t in out if t[2]]


def parse_activation(text):
    """{section: state} off the phase-1 listing — 'Activated' or 'Not Activated'."""
    states, section = {}, None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.endswith(":") and len(stripped) < 60 and not stripped.startswith("["):
            section = stripped[:-1]
            continue
        if section and ("Activated" in stripped or "None Created" in stripped):
            if "None Created" in stripped:
                states[section] = "None Created"
            elif stripped.startswith("Not Activated") or "\tNot Activated" in stripped:
                states.setdefault(section, "Not Activated")
            else:
                states[section] = "Activated"
            section = None
    return states


def lint(bodies, states):
    findings = []
    personas = collections.Counter()

    for section, name, body in bodies:
        where = "{} / {}".format(section, name)

        for url in re.findall(r"https?://\S+", body):
            host = url.split("/")[2] if "://" in url else ""
            odd = [c for c in host if ord(c) > 127]
            if odd:
                findings.append((
                    "DEAD LINK",
                    "{}: {} — the host is spelled with {}. It does not resolve; "
                    "every applicant who taps it gets nothing.".format(
                        where, url,
                        ", ".join("{!r} ({})".format(c, unicodedata.name(c, "?"))
                                  for c in odd))))

        if re.search(r"\{\{|\}\}|\bnull\b|%%", body):
            findings.append(("MERGE", "{}: leftover merge markup in the body — "
                                      "“{}”".format(where, body[:90])))

        if states.get(section) == "Activated" and not re.search(
                r"\bstop\b", body, re.I):
            findings.append(("NO OPT-OUT",
                             "{}: activated, no “Reply STOP to opt out”. "
                             "AppStream's own deliverability checklist, item 3."
                             .format(where)))

        for p in PERSONA.findall(body):
            personas[p.strip()] += 1

    return findings, personas


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="", help="a saved probe dump instead of the tab")
    ap.add_argument("--office", default="", help="read tab 'AS Templates <office>'")
    a = ap.parse_args(argv)

    text, src = load_text(a.file or None, a.office or None)
    bodies = parse_bodies(text)
    states = parse_activation(text)
    print("[templates] {} template bodies, {} sections with a state, from {}"
          .format(len(bodies), len(states), src), flush=True)
    if not bodies:
        print("[templates] no bodies captured — re-run as_templates_probe with "
              "its phase-2 Edit walk before linting", flush=True)
        return 1

    findings, personas = lint(bodies, states)
    for kind, msg in findings:
        print("  [{}] {}".format(kind, msg), flush=True)

    if personas:
        print("\n[templates] who the templates say they are:", flush=True)
        for who, n in personas.most_common():
            print("    {} — {} template(s)".format(who, n), flush=True)

    dead = [f for f in findings if f[0] == "DEAD LINK"]
    print("\n[templates] {} finding(s){}".format(
        len(findings), " — {} DEAD LINK".format(len(dead)) if dead else ""), flush=True)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
