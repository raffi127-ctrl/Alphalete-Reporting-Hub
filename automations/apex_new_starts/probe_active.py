"""Is each of this week's new starts ACTIVE in Apex? READ ONLY.

Megan, 2026-11-12: "They might have two profiles... They don't get deleted.
It's just a roster of incomplete profiles that are there. So as long as
they're in active, that's what we're looking for."

So the Pending tab is NOT a backlog, and its size proves nothing -- a person
can sit on Pending and Active at once, and the Pending entry is never tidied
away. The finished state is ACTIVE. That is the only thing worth counting.

Pages through the Active tab, collects every name, and says which of the
week's board rows are missing from it.

Types nothing, saves nothing. It clears the roster's own filter boxes, which
are a view control, and clicks through the pager.

    PYTHONPATH=. .venv/bin/python -m automations.apex_new_starts.probe_active
"""
from __future__ import annotations

import argparse
import datetime as dt

from automations.apex_new_starts import apex as AX
from automations.apex_new_starts import drive

# ONE SEARCH PER PERSON, on All Employees. Paging the tab was unreliable --
# the Next control did not advance and the same page came back fourteen times,
# which would have reported everybody as missing (2026-11-12). A filtered
# lookup is how a person checks this, and it answers the two-profile case
# directly: the search returns every row for that name, with its status.
LOOK = r"""(p) => {
  const t = e => (e ? (e.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const tab = [...document.querySelectorAll('a,button,li')]
    .find(e => e.offsetParent && t(e).toLowerCase() === 'all employees');
  if (tab) tab.click();
  const boxes = [...document.querySelectorAll('thead input, tr input')]
    .filter(e => e.offsetParent);
  if (boxes.length < 2) return {error: 'no filter row'};
  const set = (el, v) => {
    el.value = v;
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    el.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true, key: 'Enter'}));
  };
  set(boxes[0], p.first);
  set(boxes[1], p.last);
  const apply = [...document.querySelectorAll('button,a')]
    .find(e => e.offsetParent && /apply filters/i.test(t(e)));
  if (apply) apply.click();
  return {ok: true};
}"""

READ_ROWS = r"""(p) => {
  const out = [];
  for (const line of (document.body.innerText || '').split('\n')) {
    const c = line.split('\t').map(x => x.trim());
    if (c.length < 5) continue;
    const st = c.find(x => /^(active|pending|terminated)$/i.test(x));
    if (!st) continue;
    out.push({first: c[0], last: c[1], status: st.toLowerCase()});
  }
  return out;
}"""


def _fold(s):
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def main() -> int:
    ap = argparse.ArgumentParser(description="Who on the board is Active in Apex?")
    ap.add_argument("--office", default="raf")
    ap.add_argument("--week", default=None)
    a = ap.parse_args()

    from automations.icd_onboarding import board as B
    from automations.icd_onboarding import fillers as F
    from automations.icd_onboarding import sheet as S

    day = dt.date.fromisoformat(a.week) if a.week else dt.date.today()
    monday = B.week_start_of(day)
    ws = S.open_board(F.workbook_for(a.office), create=False)
    want = []
    for r in B.for_week(S.rows_of(S._values(ws)), monday):
        if str(r.get(B.TERMINATED_AT) or "").strip():
            continue
        nm = ("%s %s" % (r.get("Name", ""), r.get("Last Name", ""))).strip()
        if nm:
            want.append(nm)
    print("board week of %s: %d people" % (B.week_label(monday), len(want)))

    rows = []
    with AX.ApexSession(log=print, login_timeout_s=10 * 60) as s:
        s.require_login()
        if not drive.to_roster(s.page, log=print):
            print("could not reach the roster")
            return 1
        print("")
        for nm in want:
            parts = nm.split()
            first, last = parts[0], " ".join(parts[1:]) or parts[0]
            got = s.page.evaluate(LOOK, {"first": first, "last": last})
            if got.get("error"):
                print("  %-26s ? (%s)" % (nm, got["error"]))
                rows.append((nm, []))
                continue
            s.page.wait_for_timeout(1400)
            for _ in range(20):
                if not s.page.evaluate(
                        "() => /loading .*data/i.test(document.body.innerText || '')"):
                    break
                s.page.wait_for_timeout(400)
            hits = s.page.evaluate(READ_ROWS, {"first": first, "last": last})
            mine = [h for h in hits
                    if _fold(h["first"]) == _fold(first)
                    and _fold(h["last"]) == _fold(last)]
            states = sorted({h["status"] for h in mine})
            rows.append((nm, states))
            print("  %-26s %s" % (nm, ", ".join(states) or "NOT IN APEX"))

    done = [n for n, st in rows if "active" in st]
    pend = [n for n, st in rows if "active" not in st and "pending" in st]
    none = [n for n, st in rows if not st]
    print("")
    print("ACTIVE (finished)      : %d of %d" % (len(done), len(rows)))
    print("pending only (to do)   : %d" % len(pend))
    print("not in Apex at all     : %d" % len(none))
    if pend:
        print("\nstill to complete:")
        for n in pend:
            print("   %s" % n)
    if none:
        print("\nnot in Apex:")
        for n in none:
            print("   %s" % n)
    print("\nNothing was typed or saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
