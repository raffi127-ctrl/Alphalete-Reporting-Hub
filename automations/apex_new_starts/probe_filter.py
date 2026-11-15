"""Why does the roster filter find nobody? READ ONLY.

Four attempts at the roster lookup have failed in a row, each fixing a real
bug and revealing another: the rows check, a comment inside the injected
script, an ambiguous tab selector, and now the search itself. Every one cost
a live run, so this measures instead.

It reports, step by step: which boxes it found and what they are called, what
they hold after typing, what the Apply control is, and how many rows the page
shows at each stage. It types a surname into a FILTER box -- nothing that
belongs to a person's record -- clicks only Apply, and saves nothing.

    PYTHONPATH=. .venv/bin/python -m automations.apex_new_starts.probe_filter --last Mccrobie
"""
from __future__ import annotations

import argparse

from automations.apex_new_starts import apex as AX
from automations.apex_new_starts import drive

BOXES = r"""() => {
  const ins = [...document.querySelectorAll('input')];
  return ins.map(i => ({
    name: i.getAttribute('name') || '',
    id: i.id || '',
    ph: i.getAttribute('placeholder') || '',
    model: i.getAttribute('ng-model') || '',
    type: i.type || '',
    shown: !!i.offsetParent,
    value: String(i.value || ''),
  })).filter(b => b.shown && b.type !== 'hidden');
}"""

APPLY = r"""() => {
  const words = /apply|search|filter|go\b/i;
  return [...document.querySelectorAll('button, a, input[type=submit], [ng-click]')]
    .filter(e => e.offsetParent)
    .map(e => ({
      tag: e.tagName.toLowerCase(),
      text: ((e.innerText || e.value || '').replace(/\s+/g, ' ').trim()).slice(0, 30),
      click: (e.getAttribute('ng-click') || '').slice(0, 60),
      type: e.getAttribute('type') || '',
    }))
    .filter(e => words.test(e.text) || words.test(e.click))
    .slice(0, 10);
}"""

ROWS = r"""() => ({
  tr: document.querySelectorAll('table tr').length,
  tbody: document.querySelectorAll('table tbody tr').length,
  text: (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 260),
})"""


def show_rows(page, note: str) -> None:
    got = page.evaluate(ROWS)
    print("    %-28s tr=%-4s tbody=%-4s" % (note, got["tr"], got["tbody"]))


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure the roster filter.")
    ap.add_argument("--last", default="Mccrobie")
    ap.add_argument("--first", default="Alexandria")
    a = ap.parse_args()

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
        page.wait_for_timeout(2500)
        print("\non %s" % page.url)

        print("\n--- 1. opening the Pending tab ---")
        print("    open_roster_tab said: %s"
              % drive.open_roster_tab(page, "Pending", log=print))
        show_rows(page, "after the tab click")

        print("\n--- 2. every visible input on the page ---")
        for b in page.evaluate(BOXES):
            print("    name=%-22s id=%-18s ph=%-16s model=%-28s value=%r"
                  % (b["name"][:22], b["id"][:18], b["ph"][:16],
                     b["model"][:28], b["value"]))

        print("\n--- 3. what looks like the Apply control ---")
        for e in page.evaluate(APPLY):
            print("    <%s> %-22r ng-click=%r" % (e["tag"], e["text"], e["click"]))

        print("\n--- 4. what search_roster does, step by step ---")
        marked = page.evaluate(
            r"""() => {
                 document.querySelectorAll('[data-ans-f]')
                   .forEach(e => e.removeAttribute('data-ans-f'));
                 const ins = [...document.querySelectorAll('input')]
                   .filter(i => i.offsetParent && i.type !== 'hidden');
                 const by = w => ins.find(i => (
                   (i.getAttribute('placeholder') || '') + ' ' +
                   (i.getAttribute('name') || '') + ' ' +
                   (i.getAttribute('ng-model') || '')).toLowerCase().includes(w));
                 const last = by('last'), first = by('first');
                 if (last) last.setAttribute('data-ans-f', 'last');
                 if (first) first.setAttribute('data-ans-f', 'first');
                 return {last: !!last, first: !!first,
                         lastName: last ? (last.getAttribute('name')
                                        || last.getAttribute('ng-model') || '?') : '',
                         firstName: first ? (first.getAttribute('name')
                                        || first.getAttribute('ng-model') || '?') : ''}; }""")
        print("    marked: %s" % marked)
        if not marked.get("last"):
            print("    NO LAST-NAME BOX -- that alone explains the empty search.")
            return 0

        page.fill("[data-ans-f='last']", "")
        page.type("[data-ans-f='last']", a.last, delay=25)
        print("    last box now holds: %r" % page.evaluate(
            "() => (document.querySelector('[data-ans-f=\"last\"]') || {}).value"))
        show_rows(page, "typed, before Apply")

        clicked = ""
        for sel in ("button:text-is('Apply Filters')",
                    "a:text-is('Apply Filters')",
                    "input[value='Apply Filters']"):
            try:
                page.locator(sel).first.click(timeout=2500)
                clicked = sel
                break
            except Exception:      # noqa: BLE001
                continue
        if not clicked:
            print("    no Apply control clicked -- pressing Enter instead")
            page.press("[data-ans-f='last']", "Enter")
        else:
            print("    clicked %s" % clicked)
        page.wait_for_timeout(2500)
        show_rows(page, "after Apply")

        hits = page.evaluate(
            r"""(s) => {
                 const want = String(s || '').toLowerCase();
                 return [...document.querySelectorAll('table tr')]
                   .filter(r => (r.innerText || '').toLowerCase().includes(want))
                   .length; }""", a.last)
        print("    rows mentioning %r: %d" % (a.last, hits))
        print("\n    the page now says:\n      %s"
              % page.evaluate(ROWS)["text"][:260])

        print("\nNothing was saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
