"""Can you leave a tab you have filled but not saved? READ ONLY-ISH.

probe_nav settled that a driver click on the tab link navigates fine on a
clean record, and that a direct navigation is refused by the server (302 to
the change-password page). Yet during a real run the same click did nothing
-- and in the one run where it DID work, a person had just pressed Save.

That points at an unsaved-changes guard: the form is dirty, so Apex (or the
browser's own beforeunload) holds the page. If that is it, then "fill all
three tabs, then let somebody press Save three times" is not a thing Apex
allows, and the walk has to be built the other way round.

This types into ONE box (Rate of Pay, with the value already on the record)
and then tries to leave. It presses no Save and changes no data: a field
typed and never saved is exactly as it was.

    PYTHONPATH=. .venv/bin/python -m automations.apex_new_starts.probe_dirty --person "First Last"
"""
from __future__ import annotations

import argparse

from automations.apex_new_starts import apex as AX
from automations.apex_new_starts import drive


def main() -> int:
    ap = argparse.ArgumentParser(description="Does a dirty form hold the page?")
    ap.add_argument("--person", required=True)
    a = ap.parse_args()
    who = [{"name": a.person, "find": a.person.split()[-1], "pages": {}}]
    dialogs = []

    with AX.ApexSession(log=print, login_timeout_s=10 * 60) as s:
        page = s.page
        # A beforeunload prompt is a DIALOG. Playwright dismisses dialogs by
        # default, and dismissing a beforeunload means staying put -- which
        # would look exactly like a click that did nothing.
        page.on("dialog", lambda d: (dialogs.append(d.type), d.dismiss()))
        s.require_login()
        page.wait_for_timeout(1500)
        for _ in range(4):
            if drive.to_roster(page, log=print):
                break
            page.wait_for_timeout(2500)
        else:
            print("could not reach the roster")
            return 1
        drive.keep_loaded(page, who, log=lambda *x: None)
        pid = page.evaluate(
            "async (p) => { const id = await window.__ansOpen(p);"
            " return id ? String(id) : ''; }", who[0])
        if not pid:
            print("%s is not on the roster right now" % a.person)
            return 1
        page.wait_for_timeout(2500)
        want = "/employees/%s/edit/user-profile" % pid

        def click_tab(note: str) -> None:
            before = page.url
            marked = page.evaluate(
                """(w) => { document.querySelectorAll('[data-ans-d]')
                     .forEach(e => e.removeAttribute('data-ans-d'));
                   const x = [...document.querySelectorAll('a[href]')]
                     .find(e => (e.getAttribute('href') || '').indexOf(w) >= 0);
                   if (!x) return ''; x.setAttribute('data-ans-d', '1');
                   return 'ok'; }""", w_want)
            if not marked:
                print("  %-22s no link on this page" % note)
                return
            try:
                page.click("[data-ans-d]", timeout=6000)
                page.wait_for_timeout(3000)
            except Exception as e:      # noqa: BLE001
                print("  %-22s click raised %s" % (note, type(e).__name__))
                return
            moved = want in (page.url or "")
            print("  %-22s %s   (dialogs: %s)"
                  % (note, "MOVED" if moved else "STAYED on %s" % before.rsplit("/", 1)[-1],
                     dialogs or "none"))

        w_want = want
        if not drive.wait_for_field(page, "Position", people=who, log=print):
            print("the form never loaded")
            return 1

        print("\n--- clean form: does the tab link work ---")
        click_tab("clean")

        # back, then dirty ONE box and try again
        page.go_back()
        page.wait_for_timeout(2500)
        drive.keep_loaded(page, who, log=lambda *x: None)
        if not drive.wait_for_field(page, "Position", people=who, log=print):
            print("the form never came back")
            return 1
        print("\n--- after typing in Rate of Pay, unsaved ---")
        drive.type_into(page, "Rate of Pay", "10.00", log=print)
        dirty = page.evaluate(
            """() => { const f = document.querySelector('form');
                 return {dirty: f ? /ng-dirty|is-dirty/.test(f.className || '') : null,
                         cls: f ? (f.className || '').slice(0, 80) : ''}; }""")
        print("  form says: %s" % dirty)
        click_tab("dirty, unsaved")

        print("\nNo Save was pressed. A typed, unsaved box is unchanged data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
