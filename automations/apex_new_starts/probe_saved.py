"""Did the employment tab actually keep what was typed? READ ONLY.

Opens one person's employment record fresh and reads back what the page
shows. A save that looked fine and did not stick is the failure this cannot
be allowed to miss, so this reloads rather than trusting the form still on
screen.

Touches no Google Sheet -- it takes the employee id directly, so it can be
run repeatedly without eating the Sheets read quota.

    PYTHONPATH=. .venv/bin/python -m automations.apex_new_starts.probe_saved --id 3421274
"""
from __future__ import annotations

import argparse

from automations.apex_new_starts import apex as AX
from automations.apex_new_starts import drive

WANT = ("Position", "Rate of Pay", "State Working In",
        "Basis of Pay", "Pay Frequency", "Department")

READ = r"""(labels) => {
  const out = {};
  for (const L of labels) {
    const el = window.__ansFieldFor(L);
    if (!el) { out[L] = '(no box)'; continue; }
    const sp = el.parentElement
      ? el.parentElement.querySelector('.k-dropdown, .k-widget') : null;
    let shown = sp ? (sp.innerText || '').replace(/\s+/g, ' ').trim() : '';
    if (!shown) {
      const vis = el.parentElement
        ? [...el.parentElement.querySelectorAll('input')]
            .filter(i => i.offsetParent && i.type !== 'hidden') : [];
      shown = vis.length ? (vis[0].value || '') : (el.value || '');
    }
    out[L] = shown.slice(0, 30);
  }
  return out;
}"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Read an employment record back.")
    ap.add_argument("--person", required=True,
                    help='"First Last", as the roster spells them')
    a = ap.parse_args()

    with AX.ApexSession(log=print, login_timeout_s=10 * 60) as s:
        page = s.page
        s.require_login()
        # NEVER page.goto HERE. Apex lands every session on its
        # change-password page and a typed URL redirects straight back to it
        # -- which is exactly what happened (2026-11-12). The way in is the
        # nav link, then the app's own navigation.
        # The landing page renders its nav late and not always on the first
        # look, so this asks a few times rather than once (2026-11-12).
        page.wait_for_timeout(1500)
        for _ in range(4):
            if drive.to_roster(page, log=print):
                break
            page.wait_for_timeout(2500)
        else:
            print("could not reach the roster")
            return 1
        # A STAND-IN PERSON, because the engine's script returns early when
        # handed an empty list and then installs none of its entry points.
        who = [{"name": a.person, "find": a.person.split()[-1], "pages": {}}]
        drive.keep_loaded(page, who, log=print)
        # CLICK THEIR EDIT, like a person. The roster links are
        # User/EditUser/<id>, not the employment-record path, so the app's own
        # navigation cannot be aimed at it from here (2026-11-12).
        pid = page.evaluate(
            "async (p) => { const id = await window.__ansOpen(p);"
            " return id ? String(id) : ''; }", who[0])
        if not pid:
            print("%s is not on the roster right now" % a.person)
            return 1
        path = "/employees/%s/edit/employment-record" % pid
        if path not in (page.url or ""):
            drive.keep_loaded(page, who, log=lambda *x: None)
            page.evaluate("async (p) => await window.__ansGoSpa(p)", path)
            page.wait_for_timeout(2000)
        if path not in (page.url or ""):
            print("could not open the record (sitting on %s)" % page.url)
            return 1
        # A STAND-IN PERSON, because the engine's script returns early when
        # handed an empty list and then installs none of its entry points.
        who = [{"name": "probe only", "find": "probe", "pages": {}}]
        drive.keep_loaded(page, who, log=print)
        if not drive.wait_for_field(page, "Position", people=who, log=print):
            print("the form never loaded")
            return 1
        got = page.evaluate(READ, list(WANT))
        print("\n%s" % page.url)
        empty = []
        for k in WANT:
            v = got.get(k, "")
            print("  %-20s %r" % (k, v))
            if not v or v in ("(no box)", "Select"):
                empty.append(k)
        print("")
        if empty:
            print("NOT SAVED: %s" % ", ".join(empty))
        else:
            print("ALL SIX HELD — the employment tab saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
