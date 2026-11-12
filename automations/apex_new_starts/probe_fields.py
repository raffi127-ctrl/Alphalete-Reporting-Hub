"""Dump every field on one Apex record's three tabs. READ ONLY.

Apex was rewritten (no Angular anywhere, "Beta" in the nav, every tab a full
page load). The engine's label->box lookup finds none of the employment
fields any more, so the field map has to be rebuilt from what the page
actually holds rather than guessed at over four-minute live runs.

Types nothing, saves nothing. It opens one person's record and reads it.

    PYTHONPATH=. .venv/bin/python -m automations.apex_new_starts.probe_fields --person "Victoria Newsom"
"""
from __future__ import annotations

import argparse
import json
import pathlib

from automations.apex_new_starts import apex as AX
from automations.apex_new_starts import drive

TABS = (("employment", "edit/employment-record"),
        ("profile", "edit/user-profile"),
        ("tax", "edit/bank-info"))

DUMP = r"""() => {
  const txt = e => (e ? (e.textContent || '') : '').replace(/\\s+/g, ' ').trim();
  const out = [];
  for (const el of document.querySelectorAll('input,select,textarea')) {
    // A type=hidden input has display:none from the UA stylesheet, so the
    // visibility check below skipped every Kendo dropdown's real input.
    // Decide hidden-ness FIRST, then only apply the style check to the rest.
    const isHidden = el.type === 'hidden';
    const style = window.getComputedStyle(el);
    if (!isHidden && (style.display === 'none' || style.visibility === 'hidden')) continue;
    // KEEP THE HIDDEN ONES. A Kendo dropdown is a visible span over a
    // hidden input, so skipping type=hidden hid Position, Basis of Pay, Pay
    // Frequency, Department and State Working In -- the exact five that read
    // as missing from the employment tab (2026-11-12).

    let label = '';
    if (el.id) label = txt(document.querySelector('label[for="' + el.id + '"]'));
    if (!label) {
      let w = el.closest('div,td,li,fieldset,span');
      for (let i = 0; i < 5 && w && !label; i++) {
        label = txt(w.querySelector('label'));
        w = w.parentElement;
      }
    }
    if (!label) label = el.getAttribute('placeholder') || '';
    out.push({
      label: label.slice(0, 48),
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type') || '',
      name: el.getAttribute('name') || '',
      id: el.id || '',
      model: el.getAttribute('ng-model') || el.getAttribute('data-bind') || '',
      options: el.tagName.toLowerCase() === 'select'
        ? [...el.options].slice(0, 6).map(o => txt(o)).filter(Boolean) : [],
      value: (el.value || '').slice(0, 30),
      hidden: isHidden,
    });
  }
  return out;
}"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Read one Apex record's fields.")
    ap.add_argument("--person", default="Victoria Newsom")
    a = ap.parse_args()
    who = {"name": a.person, "find": a.person.split()[-1], "pages": {}}
    found = {}

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
            print("%s is not on Pending" % a.person)
            return 1
        print("id: %s" % pid)

        for name, path in TABS:
            want = "/employees/%s/%s" % (pid, path)
            if want not in (page.url or ""):
                drive.keep_loaded(page, [who], log=lambda *x: None)
                page.evaluate("async (p) => await window.__ansGoSpa(p)", want)
                page.wait_for_timeout(2000)
            if want not in (page.url or ""):
                print("\n=== %s === could not open (%s)" % (name, page.url))
                continue
            # WAIT FOR THE DATA, NOT THE SHELL. The employment tab renders
            # its heading and then fetches -- "Loading Employment Record
            # data..." -- and the page already has inputs (the nav, filters),
            # so any-input was no wait at all and read an empty form.
            for _ in range(60):
                busy = page.evaluate(
                    "() => /loading .*data/i.test(document.body.innerText || '')")
                if not busy:
                    break
                page.wait_for_timeout(500)
            page.wait_for_timeout(1200)
            if name == "employment":
                shape = page.evaluate(r"""() => {
                  const t = e => (e.textContent || '').replace(/\s+/g, ' ').trim();
                  return {
                    headings: [...document.querySelectorAll('h1,h2,h3,h4,legend,th')]
                      .filter(e => e.offsetParent).map(t).filter(Boolean).slice(0, 20),
                    buttons: [...document.querySelectorAll('button,a.btn,[role=button]')]
                      .filter(e => e.offsetParent).map(t).filter(Boolean).slice(0, 20),
                    frames: document.querySelectorAll('iframe').length,
                    body: t(document.querySelector('main') || document.body).slice(0, 400),
                  };
                }""")
                print("  headings:", " | ".join(shape["headings"]))
                print("  buttons :", " | ".join(shape["buttons"]))
                print("  iframes :", shape["frames"])
                print("  text    :", shape["body"][:300])
            fields = page.evaluate(DUMP)
            found[name] = fields
            print("\n=== %s === %d field(s)" % (name, len(fields)))
            for f in fields:
                extra = ""
                if f["options"]:
                    extra = "  opts: %s" % ", ".join(f["options"][:4])
                print("  %-40s %-8s name=%-26s%s"
                      % (f["label"] or "(no label)", f["tag"], f["name"], extra))

    out = pathlib.Path("output/apex-fields.json")
    out.write_text(json.dumps(found, indent=1))
    print("\nwrote %s" % out)
    print("Nothing was typed or saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
