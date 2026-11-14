"""What does Rate of Pay actually contain while it is being typed? READ ONLY.

$10.10 has landed on a real payroll record twice now for somebody whose rate
is $10.00 (Kyle Wojtylewski Durbin, 2026-11-13). A fix on 2026-11-12 --
click, select all, delete, then type -- appeared to work on one run and then
failed on a box that already held 10.00, so the cause was never found. This
measures it instead of guessing a fourth time.

It reports, keystroke by keystroke, what the visible box holds and what the
widget behind it thinks its value is, for several ways of clearing and
typing. It NEVER presses Save, so nothing it does reaches the record: the box
is left holding whatever the last attempt put there and the page is closed
without saving.

    PYTHONPATH=. .venv/bin/python -m automations.apex_new_starts.probe_rate --person "First Last"
"""
from __future__ import annotations

import argparse

from automations.apex_new_starts import apex as AX
from automations.apex_new_starts import drive

WANT = "10.00"

READ = r"""() => {
  const el = window.__ansFieldFor('Rate of Pay');
  if (!el) return {box: '(no box)', widget: '(none)'};
  const w = el.parentElement;
  const vis = w ? [...w.querySelectorAll('input')]
    .filter(i => i.offsetParent && i.type !== 'hidden') : [];
  const box = vis.length ? vis[0] : el;
  let widget = '(no api)';
  try {
    if (window.jQuery) {
      const k = window.jQuery(box).data('kendoNumericTextBox');
      if (k && k.value) widget = String(k.value());
    }
  } catch (e) { widget = '(threw)'; }
  return {box: String(box.value || ''), hidden: String(el.value || ''),
          widget: widget, readOnly: !!box.readOnly,
          cls: (box.className || '').slice(0, 40)};
}"""


def show(page, note: str) -> None:
    got = page.evaluate(READ)
    print("    %-26s box=%-12r hidden=%-10r widget=%-10r"
          % (note, got.get("box"), got.get("hidden"), got.get("widget")))


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure the Rate of Pay box.")
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
        if not drive.wait_for_field(page, "Position", people=who, log=print):
            print("the form never loaded")
            return 1

        marked = page.evaluate(
            """() => { const el = window.__ansFieldFor('Rate of Pay');
                 if (!el) return '';
                 const w = el.parentElement;
                 const vis = w ? [...w.querySelectorAll('input')]
                   .filter(i => i.offsetParent && i.type !== 'hidden') : [];
                 const box = vis.length ? vis[0] : el;
                 box.setAttribute('data-ans-rate', '1');
                 return box.id || box.name || 'x'; }""")
        if not marked:
            print("no Rate of Pay box on this page")
            return 1
        sel = "[data-ans-rate]"
        print("\n  the box as the page loads:")
        show(page, "on arrival")

        print("\n  --- 1. what the 2026-11-12 fix does ---")
        page.click(sel)
        show(page, "after click")
        page.keyboard.press("Meta+a")
        show(page, "after Meta+a")
        page.keyboard.press("Delete")
        show(page, "after Delete")
        for i, ch in enumerate(WANT, 1):
            page.type(sel, ch, delay=40)
            show(page, "typed %r (%d/%d)" % (ch, i, len(WANT)))
        page.evaluate("() => { const e = document.querySelector('[data-ans-rate]');"
                      " if (e) e.dispatchEvent(new Event('blur', {bubbles: true})); }")
        page.wait_for_timeout(600)
        show(page, "after blur")

        print("\n  --- 2. select-all with ControlOrMeta, then type ---")
        page.click(sel)
        page.keyboard.press("ControlOrMeta+a")
        page.keyboard.press("Backspace")
        show(page, "cleared")
        page.type(sel, WANT, delay=40)
        page.keyboard.press("Tab")
        page.wait_for_timeout(600)
        show(page, "typed then Tab")

        print("\n  --- 3. fill() on its own ---")
        page.fill(sel, "")
        show(page, "fill('')")
        page.fill(sel, WANT)
        page.keyboard.press("Tab")
        page.wait_for_timeout(600)
        show(page, "fill(%r) then Tab" % WANT)

        print("\n  --- 4. the widget's own API, if there is one ---")
        got = page.evaluate(
            """(v) => { const box = document.querySelector('[data-ans-rate]');
                 try {
                   const k = window.jQuery
                     && window.jQuery(box).data('kendoNumericTextBox');
                   if (!k) return 'no kendoNumericTextBox';
                   k.value(v); k.trigger('change');
                   return 'set via widget';
                 } catch (e) { return 'threw: ' + e.message.slice(0, 60); } }""",
            WANT)
        print("    %s" % got)
        show(page, "after widget set")

        print("\n  Nothing was saved. Close the window without saving.")
        drive._hold = None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
