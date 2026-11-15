"""What does the roster page actually look like? READ ONLY.

`on_roster` refuses to judge anybody from a page it cannot recognise -- which
is right, because "not found" on an unreadable page routes to the CREATE form
and a second payroll record for a real employee. But it does not recognise
the live roster either: the URL is /roster and the check still says no, even
after waiting 25 seconds (2026-11-15).

So this prints what is really there -- the headings, the tab labels, the row
counts under each selector worth trying -- instead of another guess at a
selector.

Types nothing, clicks nothing, saves nothing.

    PYTHONPATH=. .venv/bin/python -m automations.apex_new_starts.probe_roster
"""
from __future__ import annotations

from automations.apex_new_starts import apex as AX
from automations.apex_new_starts import drive

LOOK = r"""() => {
  const t = (document.body.innerText || '');
  const counts = {};
  for (const sel of ['table tbody tr', '.k-grid-content tr', 'table tr',
                     'tbody tr', '[role=row]', '.k-grid tr', 'tr']) {
    counts[sel] = document.querySelectorAll(sel).length;
  }
  return {
    url: location.href,
    words: t.replace(/\s+/g, ' ').trim().slice(0, 600),
    hasPending: /pending/i.test(t),
    hasAllEmployees: /all employees/i.test(t),
    hasChangePassword: /change your password/i.test(t),
    counts: counts,
    tabs: [...document.querySelectorAll('a, button, li, [role=tab]')]
      .map(e => (e.innerText || '').replace(/\s+/g, ' ').trim())
      .filter(x => x && x.length < 30 && /pending|employee|active|all/i.test(x))
      .slice(0, 14),
  };
}"""


def main() -> int:
    with AX.ApexSession(log=print, login_timeout_s=10 * 60) as s:
        page = s.page
        drive.guard_unsaved(page, log=print)
        s.require_login()
        page.wait_for_timeout(1500)
        got_there = False
        for _ in range(4):
            if drive.to_roster(page, log=print):
                got_there = True
                break
            page.wait_for_timeout(2500)
        print("\nto_roster said: %s" % got_there)
        page.wait_for_timeout(4000)

        got = page.evaluate(LOOK)
        print("\non %s" % got["url"])
        print("  'Pending' on the page        : %s" % got["hasPending"])
        print("  'All Employees' on the page  : %s" % got["hasAllEmployees"])
        print("  'change your password'       : %s" % got["hasChangePassword"])
        says = drive.on_roster(page)
        print("  on_roster() says             : %s" % says)
        print("  on_roster last error         : %r"
              % getattr(drive.on_roster, "last_error", ""))
        print("  the same JS, run here        : %s" % page.evaluate(
            r"""() => {
                 const t = (document.body.innerText || '');
                 return {active: /Active/i.test(t), pending: /Pending/i.test(t),
                         all: /All Employees/i.test(t),
                         pw: /change your password/i.test(t),
                         len: t.length}; }"""))
        print("\n  row counts by selector:")
        for sel, n in got["counts"].items():
            print("      %-24s %d" % (sel, n))
        print("\n  tab-ish labels: %s" % got["tabs"])
        print("\n  the page says:\n    %s" % got["words"][:500])
        print("\nNothing was typed or saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
