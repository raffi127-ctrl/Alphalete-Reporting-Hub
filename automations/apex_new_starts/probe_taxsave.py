"""Why does the tax tab save for one person and not the next? READ ONLY-ISH.

Alexandria's tax tab saved and she went Active. Gerardo's did not and he is
still Pending -- same code, same log, both reported "pressed 'Save' and
nothing was posted" (2026-11-15). So the press is unreliable AND the
detector cannot tell success from failure.

This opens one person's tax tab, reports what the Save control actually is,
what the page says before and after pressing it, and every non-GET request
that leaves the page while it does. It presses Save ONCE -- that is the thing
being measured -- on a tab it has not changed, so the only write is the one
Apex would have made anyway.

    PYTHONPATH=. .venv/bin/python -m automations.apex_new_starts.probe_taxsave --person "First Last"
"""
from __future__ import annotations

import argparse

from automations.apex_new_starts import apex as AX
from automations.apex_new_starts import drive

SAVES = r"""() => [...document.querySelectorAll('button, a, input[type=submit]')]
  .filter(e => e.offsetParent)
  .map(e => ({tag: e.tagName.toLowerCase(),
              text: ((e.innerText || e.value || '')
                .replace(/\s+/g, ' ').trim()).slice(0, 24),
              type: e.getAttribute('type') || '',
              click: (e.getAttribute('ng-click') || '').slice(0, 70),
              disabled: !!e.disabled}))
  .filter(e => /save/i.test(e.text) || /save/i.test(e.click))"""

STATE = r"""() => ({
  errors: [...document.querySelectorAll(
    '.validation-summary-errors, .field-validation-error, .alert-danger, '
    + '.text-danger, .ng-invalid')]
    .map(e => (e.innerText || e.className || '').replace(/\s+/g, ' ').trim())
    .filter(Boolean).slice(0, 8),
  banner: ((document.body.innerText || '').match(
    /Please fill in all required fields[^.]*\./) || [''])[0],
  url: location.href,
})"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure the tax tab's Save.")
    ap.add_argument("--person", required=True)
    a = ap.parse_args()
    who = [{"name": a.person, "find": a.person.split()[-1], "pages": {}}]
    seen = []

    with AX.ApexSession(log=print, login_timeout_s=10 * 60) as s:
        page = s.page
        drive.guard_unsaved(page, log=print)
        page.on("response", lambda r: seen.append(
            "%s %s %s" % ((r.request.method or "?"), r.status, r.url[:90]))
            if (r.request.method or "GET").upper() != "GET" else None)
        s.require_login()
        page.wait_for_timeout(1500)
        for _ in range(4):
            if drive.to_roster(page, log=print):
                break
            page.wait_for_timeout(2500)
        drive.keep_loaded(page, who, log=lambda *x: None)
        pid = page.evaluate(
            "async (p) => { const id = await window.__ansOpen(p);"
            " return id ? String(id) : ''; }", who[0])
        if not pid:
            print("%s is not on Pending right now" % a.person)
            return 1
        page.wait_for_timeout(2000)
        if not drive.go_tab(page, pid, "bank-info", people=who, log=print):
            print("could not open the tax tab")
            return 1
        drive.wait_for_all_named(page, ["MaritalStatus_input", "SSN"], log=print)

        print("\n--- what the page says BEFORE ---")
        before = page.evaluate(STATE)
        print("    banner: %r" % before["banner"])
        for e in before["errors"]:
            print("    error/invalid: %s" % e[:110])

        print("\n--- what looks like Save ---")
        for e in page.evaluate(SAVES):
            print("    <%s> %-16r type=%-7r disabled=%-5s ng-click=%r"
                  % (e["tag"], e["text"], e["type"], e["disabled"], e["click"]))

        print("\n--- pressing it once ---")
        seen.clear()
        hit = page.evaluate(
            r"""() => {
                 document.querySelectorAll('[data-ans-apply]')
                   .forEach(e => e.removeAttribute('data-ans-apply'));
                 const b = [...document.querySelectorAll(
                   'button, a, input[type=submit]')].find(e => {
                     if (!e.offsetParent || e.disabled) return false;
                     const t = ((e.innerText || e.value || '')
                       .replace(/\s+/g, ' ').trim()).toLowerCase();
                     return t === 'save';
                   });
                 if (!b) return '';
                 b.setAttribute('data-ans-apply', '1');
                 return 'ok'; }""")
        if not hit:
            print("    no plain 'Save' control found")
            return 0
        try:
            page.click("[data-ans-apply]", timeout=6000)
        except Exception as e:      # noqa: BLE001
            print("    the click raised %s" % type(e).__name__)
        page.wait_for_timeout(4000)

        print("\n--- requests that left the page ---")
        for r in seen[-12:] or ["(none at all)"]:
            print("    %s" % r)

        print("\n--- what the page says AFTER ---")
        after = page.evaluate(STATE)
        print("    url: %s" % after["url"])
        print("    banner: %r" % after["banner"])
        for e in after["errors"]:
            print("    error/invalid: %s" % e[:110])
        print("\nNothing was typed. The only press was the Save being measured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
