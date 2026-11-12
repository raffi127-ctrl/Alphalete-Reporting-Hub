"""Does a REAL click fill an Apex dropdown where a synthetic one does not?

The engine does everything with in-page JavaScript, because that is all a
bookmarklet can do. On the rewritten Apex that stopped working for the
employment tab's dropdowns: the list opens, the right option is clicked, and
the hidden ...ID input stays empty (2026-11-12). Kendo's own API is
unreachable there too, so there is nothing to call instead.

Browsers mark events made by JavaScript as untrusted, and some frameworks
ignore them. Playwright clicks through the browser itself, so its events are
trusted. If that is the difference, the driven path is the ONLY one that can
fill these fields -- a bookmarklet cannot send a trusted event, ever.

This fills ONE dropdown, reads the hidden id back, and stops. It never saves.

    PYTHONPATH=. .venv/bin/python -m automations.apex_new_starts.probe_trusted
"""
from __future__ import annotations

import argparse
import datetime as dt

from automations.apex_new_starts import apex as AX
from automations.apex_new_starts import drive

FIELDS = (("Position", "Sales Rep"),
          ("Basis of Pay", "Commissions"),
          ("Pay Frequency", "Weekly"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Trusted vs synthetic click.")
    ap.add_argument("--person", default="Victoria Newsom")
    a = ap.parse_args()
    who = {"name": a.person, "find": a.person.split()[-1], "pages": {}}

    with AX.ApexSession(log=print, login_timeout_s=10 * 60) as s:
        page = s.page
        s.require_login()
        if not drive.to_roster(page, log=print):
            print("could not reach the roster")
            return 1
        drive.keep_loaded(page, [who], log=print)
        pid = page.evaluate(
            "async (p) => { const id = await window.__ansOpen(p);"
            " return id ? String(id) : ''; }", who)
        if not pid:
            print("%s is not on Pending right now" % a.person)
            return 1
        want = "/employees/%s/edit/employment-record" % pid
        if want not in (page.url or ""):
            drive.keep_loaded(page, [who], log=lambda *x: None)
            page.evaluate("async (p) => await window.__ansGoSpa(p)", want)
        for _ in range(60):
            if not page.evaluate(
                    "() => /loading .*data/i.test(document.body.innerText || '')"):
                break
            page.wait_for_timeout(500)
        page.wait_for_timeout(1500)
        print("on %s" % page.url)

        for label, value in FIELDS:
            # The id of the hidden input the <label> points at.
            name = page.evaluate(
                """(L) => { const el = window.__ansFieldFor(L);
                     return el ? (el.id || el.name || '') : ''; }""", label)
            if not name:
                print("  %-14s no box" % label)
                continue
            before = page.evaluate("(n) => (document.getElementById(n) || {}).value || ''", name)

            # A REAL click, through the browser: open the list, pick the row.
            try:
                page.click("span.k-dropdown:near(label:text('%s'))" % label, timeout=4000)
            except Exception:
                # fall back to the span sitting beside that input
                page.evaluate("""(n) => { const el = document.getElementById(n);
                      const sp = el.parentElement.querySelector('.k-dropdown');
                      if (sp) sp.setAttribute('data-probe', '1'); }""", name)
                try:
                    page.click("[data-probe='1']", timeout=4000)
                except Exception as e:  # noqa: BLE001
                    print("  %-14s could not open (%s)" % (label, type(e).__name__))
                    continue
            page.wait_for_timeout(900)
            try:
                page.click("ul.k-list li:text-is('%s')" % value, timeout=4000)
            except Exception:
                try:
                    page.click("li:text-is('%s')" % value, timeout=3000)
                except Exception as e:  # noqa: BLE001
                    print("  %-14s list open, could not click %r (%s)"
                          % (label, value, type(e).__name__))
                    continue
            page.wait_for_timeout(1200)
            # WHAT THE PERSON SEES, as well as the hidden id. Apex copies the
            # chosen item into the ...ID on ng-blur, so reading the id straight
            # after the click may be reading it before the page has written it.
            page.evaluate("""(n) => { const el = document.getElementById(n);
                  if (el) el.dispatchEvent(new Event('blur', {bubbles: true})); }""", name)
            page.wait_for_timeout(900)
            after = page.evaluate("(n) => (document.getElementById(n) || {}).value || ''", name)
            shown = page.evaluate("""(n) => {
                  const el = document.getElementById(n);
                  if (!el) return '';
                  const sp = el.parentElement.querySelector('.k-dropdown, .k-widget');
                  return sp ? (sp.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 30) : '';
                }""", name)
            print("  %-14s %-22s id %r -> %r   shows %r   %s"
                  % (label, name, before, after, shown,
                     "FILLED" if (after and after != before) else
                     ("SHOWS THE VALUE, id empty" if shown and value.lower() in shown.lower()
                      else "still empty")))

        print("\nNothing was saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
