"""What is actually in the Country dropdown? READ ONLY.

Gender and State both get picked fine by the same code, and Country times
out looking for 'United States' (2026-11-12). The option matcher is an EXACT
text match, so a list that spells it differently -- or one that renders its
rows only as you scroll -- fails exactly like this.

Opens the profile tab, opens that one dropdown, and prints what is in it. It
types nothing into a saved field and presses no Save.

    PYTHONPATH=. .venv/bin/python -m automations.apex_new_starts.probe_country --person "First Last"
"""
from __future__ import annotations

import argparse

from automations.apex_new_starts import apex as AX
from automations.apex_new_starts import drive

LIST = r"""() => {
  const uls = [...document.querySelectorAll('ul.k-list, ul[role=listbox], ul')]
    .filter(u => u.offsetParent && u.querySelectorAll('li').length > 1);
  const out = [];
  for (const u of uls) {
    const items = [...u.querySelectorAll('li')]
      .map(li => (li.innerText || '').replace(/\s+/g, ' ').trim());
    out.push({cls: (u.className || '').slice(0, 50), n: items.length,
              first: items.slice(0, 6),
              us: items.filter(t => /united|u\.?s\.?a?\b/i.test(t)).slice(0, 6)});
  }
  return out;
}"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Read the Country dropdown.")
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
        page.wait_for_timeout(2500)
        if not drive.go_tab(page, pid, "user-profile", people=who, log=print):
            print("could not open the profile tab")
            return 1
        if not drive.wait_for_field_named(page, "CountryID", people=who, log=print):
            print("the profile tab never loaded")
            return 1

        print("\n--- the CountryID box itself ---")
        print("  %s" % page.evaluate(
            """() => { const el = document.querySelector('[name="CountryID"]')
                   || document.getElementById('CountryID');
                 if (!el) return 'absent';
                 const w = el.parentElement;
                 const sp = w ? w.querySelector('.k-dropdown, .k-widget, .k-combobox') : null;
                 return {type: el.type, value: el.value || '',
                         widget: sp ? (sp.className || '').slice(0, 60) : 'none',
                         shows: sp ? (sp.innerText || '').replace(/\\s+/g,' ').trim() : '',
                         hasInput: !!(w && w.querySelector('input:not([type=hidden])'))}; }"""))

        print("\n--- opening it ---")
        marked = drive._mark_by_name(page, "CountryID")
        print("  marked: %r" % marked)
        try:
            page.click("[%s-widget]" % drive._MARK, timeout=6000)
            page.wait_for_timeout(1200)
        except Exception as e:      # noqa: BLE001
            print("  could not open it: %s" % type(e).__name__)
        for got in page.evaluate(LIST):
            print("  list cls=%-24s n=%-4s first=%s" % (got["cls"], got["n"],
                                                        got["first"]))
            if got["us"]:
                print("      LOOKS LIKE THE ONE WE WANT: %s" % got["us"])

        print("\nNothing was typed into a saved field and nothing was saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
