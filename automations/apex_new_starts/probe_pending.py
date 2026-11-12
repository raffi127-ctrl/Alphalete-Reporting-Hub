"""Who is sitting on Apex's Pending tab, and how long. READ ONLY.

Everybody in OwnerVille lands in Apex on Pending by themselves, as a partial
profile, and stays there until the three tabs are completed and saved (Megan,
2026-11-12: "they get added almost always automatically if they are in OV and
would always then be a partial profile in pending until we complete it").

So a partial record proves nothing. A BACKLOG does: if the completion run has
been broken since Apex's Beta rewrite, nobody has moved off Pending since, and
the tab grows week on week instead of draining.

Clicks the Pending tab and CLEARS THE FILTER BOXES first -- they are sticky,
and a stale "victori" left in one makes a 40-person backlog read as 1 (caught
2026-11-12). Those boxes are a view control, not anybody's record: nothing
here types into a field that is saved.

    PYTHONPATH=. .venv/bin/python -m automations.apex_new_starts.probe_pending
"""
from __future__ import annotations

import pathlib

from automations.apex_new_starts import apex as AX
from automations.apex_new_starts import drive

READ = r"""() => {
  const t = e => (e ? (e.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const tab = [...document.querySelectorAll('a,button,li')]
    .find(e => e.offsetParent && t(e).toLowerCase() === 'pending');
  if (!tab) return {error: 'no Pending tab on this page'};
  tab.click();
  // The filter row is sticky between visits. Empty every box and re-apply,
  // or the count is of whatever somebody last searched for.
  let cleared = 0;
  for (const el of document.querySelectorAll('thead input, tr input')) {
    if (!el.offsetParent) continue;
    if (el.value) {
      el.value = '';
      el.dispatchEvent(new Event('input', {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
      cleared++;
    }
  }
  const apply = [...document.querySelectorAll('button,a')]
    .find(e => e.offsetParent && /apply filters/i.test(t(e)));
  if (apply) apply.click();
  return {clicked: true, cleared: cleared, applied: !!apply};
}"""

# THE PAGE'S OWN COUNT. Apex keeps Active, Pending and Terminated in the DOM
# together, so walking tbody rows reads three tabs at once and paginates at 15
# -- a count built that way was out by a factor of three (2026-11-12). The
# roster states its own total: "Showing 1 to 25 of 46 entries".
# JUST THE TEXT. Three attempts to read this out of the DOM gave three wrong
# answers -- Apex keeps Active, Pending and Terminated in the page together
# and paginates each at 15, so row-walking counts three tabs at once. The page
# states its own total in plain words; take that and parse it in Python.
TEXT = r"""() => (document.body.innerText || '')"""


def main() -> int:
    with AX.ApexSession(log=print, login_timeout_s=10 * 60) as s:
        s.require_login()
        page = s.page
        if not drive.to_roster(page, log=print):
            print("could not reach the roster")
            return 1
        got = page.evaluate(READ)
        if got.get("error"):
            print(got["error"])
            return 1
        print("cleared %d stale filter box(es); Apply Filters: %s"
              % (got.get("cleared", 0), got.get("applied")))
        page.wait_for_timeout(2500)
        for _ in range(40):
            busy = page.evaluate(
                "() => /loading .*data/i.test(document.body.innerText || '')")
            if not busy:
                break
            page.wait_for_timeout(500)
        page.wait_for_timeout(1200)

        import re
        body = page.evaluate(TEXT)
        lines = [l.strip() for l in body.splitlines() if "showing" in l.lower()]
        print("\ncount line(s) on the page:")
        for l in lines or ["(none found)"]:
            print("   %s" % l)
        m = re.search(r"of\s+([\d,]+)\s+entries", " ".join(lines), re.I)
        if m:
            print("\nPENDING: %s" % m.group(1))
        else:
            print("\nCould not read a count. Saving the page text to "
                  "output/apex-pending-page.txt so it can be read by eye.")
            pathlib.Path("output/apex-pending-page.txt").write_text(body)
        print("\nNothing was typed or saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
