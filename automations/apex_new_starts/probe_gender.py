"""Why will Gender not take? READ ONLY, and it answers rather than guesses.

Five attempts have failed, each from a theory read off a log: a stale popup,
a parent-vs-ancestor lookup, a wrapper click, read-only typing, an unscoped
row click. Every one was wrong, and each cost a live run. The two bugs that
actually got solved today were solved by LOOKING -- a screenshot, and
probe_rate's keystroke dump. So this looks.

It prints the Gender widget's real structure, then tries each way of setting
it IN TURN and reports what the field holds afterwards, so the one that works
is identified by evidence. It presses no Save; the page is closed without
saving, so nothing it does reaches the record.

    PYTHONPATH=. .venv/bin/python -m automations.apex_new_starts.probe_gender --person "First Last"
"""
from __future__ import annotations

import argparse

from automations.apex_new_starts import apex as AX
from automations.apex_new_starts import drive

WANT = "Male"

SHAPE = r"""() => {
  const byName = n => document.querySelector('[name="' + n + '"]')
                   || document.getElementById(n);
  const inp = byName('Gender_input');
  const out = {input: null, ids: [], widget: null, list: null};
  if (inp) {
    out.input = {tag: inp.tagName, type: inp.type, value: inp.value || '',
                 readOnly: !!inp.readOnly, role: inp.getAttribute('role') || '',
                 cls: (inp.className || '').slice(0, 60),
                 owns: inp.getAttribute('aria-owns') || '',
                 controls: inp.getAttribute('aria-controls') || ''};
    const w = inp.closest('.k-widget, .k-dropdown, .k-combobox');
    if (w) out.widget = {cls: (w.className || '').slice(0, 70),
                         text: (w.innerText || '').replace(/\s+/g, ' ').trim(),
                         owns: w.getAttribute('aria-owns') || '',
                         controls: w.getAttribute('aria-controls') || '',
                         html: w.outerHTML.slice(0, 300)};
  }
  /* every element whose name or id mentions Gender -- the id half included */
  for (const e of document.querySelectorAll('[name*=Gender], [id*=Gender]')) {
    out.ids.push({tag: e.tagName, name: e.getAttribute('name') || '',
                  id: e.id || '', type: e.type || '',
                  value: (e.value !== undefined ? String(e.value) : ''),
                  shown: !!e.offsetParent});
  }
  return out;
}"""

VALUES = r"""() => {
  const byName = n => document.querySelector('[name="' + n + '"]')
                   || document.getElementById(n);
  const inp = byName('Gender_input');
  const out = {input: inp ? (inp.value || '') : '(absent)', ids: {}};
  for (const e of document.querySelectorAll('[name*=GenderID], [id*=GenderID]')) {
    out.ids[(e.getAttribute('name') || e.id)] = String(e.value || '');
  }
  return out;
}"""


def show(page, note: str) -> None:
    got = page.evaluate(VALUES)
    print("      %-30s input=%-10r ids=%s" % (note, got["input"], got["ids"]))


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure the Gender control.")
    ap.add_argument("--person", required=True)
    a = ap.parse_args()
    who = [{"name": a.person, "find": a.person.split()[-1], "pages": {}}]

    with AX.ApexSession(log=print, login_timeout_s=10 * 60) as s:
        page = s.page
        drive.guard_unsaved(page, log=print)
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
        page.wait_for_timeout(2000)
        if not drive.go_tab(page, pid, "user-profile", people=who, log=print):
            print("could not open the profile tab")
            return 1
        if not drive.wait_for_field_named(page, "Gender_input", people=who,
                                          log=print):
            print("the profile tab never loaded")
            return 1

        shape = page.evaluate(SHAPE)
        print("\n--- what Gender IS ---")
        print("  input : %s" % shape.get("input"))
        print("  widget: %s" % {k: v for k, v in (shape.get("widget") or {}).items()
                                if k != "html"})
        print("  html  : %s" % (shape.get("widget") or {}).get("html", ""))
        print("  every Gender-ish element:")
        for e in shape.get("ids") or []:
            print("      %s" % e)

        print("\n--- 1. the arrow, then the row in its own list ---")
        show(page, "before")
        drive._mark_by_name(page, "Gender_input")
        try:
            page.click("[%s-widget] .k-select" % drive._MARK, timeout=4000)
            page.wait_for_timeout(900)
        except Exception as e:      # noqa: BLE001
            print("      arrow click: %s" % type(e).__name__)
        lists = page.evaluate(
            r"""() => [...document.querySelectorAll('ul.k-list')]
                 .filter(u => u.offsetParent)
                 .map(u => ({id: u.id || '(none)',
                             items: [...u.querySelectorAll('li')].map(
                               li => (li.innerText || '').trim()).slice(0, 8),
                             itemHtml: u.querySelector('li')
                               ? u.querySelector('li').outerHTML.slice(0, 160) : ''}))""")
        for l in lists:
            print("      open list id=%r items=%s" % (l["id"], l["items"]))
            print("        first item html: %s" % l["itemHtml"])
        for l in lists:
            if WANT in l["items"] and l["id"] != "(none)":
                try:
                    page.click('[id=%s] li:text-is(%r)'
                               % (__import__("json").dumps(l["id"]), WANT),
                               timeout=4000)
                    page.wait_for_timeout(800)
                    show(page, "clicked row in %s" % l["id"])
                except Exception as e:      # noqa: BLE001
                    print("      row click in %s: %s" % (l["id"], type(e).__name__))

        print("\n--- 2. keyboard: open, arrow down, Enter ---")
        drive.settle_popups(page)
        show(page, "before")
        try:
            page.click("[%s]" % drive._MARK, timeout=4000)
            page.keyboard.press("ArrowDown")
            page.wait_for_timeout(400)
            show(page, "ArrowDown")
            page.keyboard.press("Enter")
            page.wait_for_timeout(600)
            show(page, "Enter")
        except Exception as e:      # noqa: BLE001
            print("      %s" % type(e).__name__)

        print("\n--- 3. type the word, then Enter ---")
        drive.settle_popups(page)
        try:
            page.fill("[%s]" % drive._MARK, "")
            page.type("[%s]" % drive._MARK, WANT, delay=60)
            show(page, "typed %r" % WANT)
            page.keyboard.press("Enter")
            page.wait_for_timeout(600)
            show(page, "then Enter")
        except Exception as e:      # noqa: BLE001
            print("      %s" % type(e).__name__)

        print("\nNothing was saved. Close the window without saving.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
