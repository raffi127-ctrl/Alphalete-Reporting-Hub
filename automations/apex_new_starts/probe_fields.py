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
            if name == "employment":
                # WHY fieldFor cannot reach them. The engine ships its own
                # describer; ask it rather than guessing at the markup.
                why = page.evaluate(r"""(labels) => {
                  const out = {};
                  for (const L of labels) {
                    let el = null;
                    try { el = window.__ansFieldFor ? window.__ansFieldFor(L) : null; } catch (e) {}
                    const labs = [...document.querySelectorAll('label')]
                      .filter(x => (x.innerText || '').replace(/\s+/g, ' ').trim()
                                   .toLowerCase().includes(L.toLowerCase()));
                    const seen = labs.map(x => {
                      const sib = x.nextElementSibling;
                      const inner = x.querySelector('input,select,textarea');
                      const sibIn = sib ? sib.querySelector('input,select,textarea') : null;
                      return {
                        text: (x.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 30),
                        htmlFor: x.htmlFor || '',
                        inner: inner ? inner.name || inner.type : '',
                        sibTag: sib ? sib.tagName.toLowerCase() : '',
                        sibClass: sib ? (sib.className || '').slice(0, 40) : '',
                        sibInput: sibIn ? (sibIn.name || sibIn.type) : '',
                      };
                    });
                    out[L] = {found: !!el, labels: seen};
                  }
                  return out;
                }""", ["Position", "Rate of Pay", "State Working In",
                       "Basis of Pay", "Pay Frequency", "Department"])
                widget = page.evaluate(r"""(pairs) => {
                  const out = {};
                  for (const [L, want] of pairs) {
                    const el = window.__ansFieldFor(L);
                    if (!el) { out[L] = {found: false}; continue; }
                    const span = el.parentElement
                      ? el.parentElement.querySelector('.k-widget, .k-dropdown, .k-numerictextbox')
                      : null;
                    let api = null, items = [];
                    try {
                      const $ = window.jQuery;
                      if ($ && $(el).data) {
                        const w = $(el).data('kendoDropDownList') || $(el).data('kendoComboBox')
                               || $(el).data('kendoNumericTextBox');
                        if (w) {
                          api = w.options && w.options.name || 'kendo';
                          if (w.dataSource && w.dataSource.view)
                            items = w.dataSource.view().slice(0, 6)
                              .map(x => (x.Text || x.text || x.Name || JSON.stringify(x)).toString().slice(0, 28));
                        }
                      }
                    } catch (e) { api = 'err:' + e.message.slice(0, 30); }
                    out[L] = {found: true, tag: el.tagName.toLowerCase(),
                              type: el.type || '', name: el.name || '',
                              span: span ? (span.className || '').slice(0, 34) : '',
                              api: api, want: want, items: items};
                  }
                  return out;
                }""", [["Position", "Sales Rep"], ["Basis of Pay", "Commissions"],
                       ["Pay Frequency", "Weekly"], ["Department", "400 Sales"],
                       ["State Working In", "Texas"], ["Rate of Pay", "10.00"]])
                print("\n  -- the widget behind each label --")
                for k, v in widget.items():
                    if not v.get("found"):
                        print("   %-18s NOT FOUND" % k)
                        continue
                    print("   %-18s %s[%s] name=%-26s span=%-22s api=%s"
                          % (k, v["tag"], v["type"], v["name"], v["span"], v["api"]))
                    if v.get("items"):
                        print("      options: %s" % ", ".join(v["items"]))

                opened = page.evaluate(r"""() => {
                  const el = window.__ansFieldFor('Position');
                  if (!el) return {error: 'no Position box'};
                  const span = el.parentElement.querySelector('.k-widget, .k-dropdown');
                  if (!span) return {error: 'no widget span'};
                  const uls = () => [...document.querySelectorAll('ul,[role=listbox]')]
                    .filter(u => u.offsetParent && u.querySelectorAll('li,[role=option]').length);
                  const before = uls().length;
                  for (const type of ['mousedown', 'mouseup', 'click']) {
                    span.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true}));
                  }
                  return {before: before, span: (span.className || '').slice(0, 40),
                          clicked: true};
                }""")
                page.wait_for_timeout(1500)
                after = page.evaluate(r"""() => {
                  const uls = [...document.querySelectorAll('ul,[role=listbox]')]
                    .filter(u => u.offsetParent && u.querySelectorAll('li,[role=option]').length);
                  return uls.slice(-3).map(u => ({
                    cls: (u.className || '').slice(0, 40),
                    n: u.querySelectorAll('li,[role=option]').length,
                    items: [...u.querySelectorAll('li,[role=option]')].slice(0, 6)
                      .map(li => (li.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 24)),
                  }));
                }""")
                print("\n  -- does clicking Position open a list? --")
                print("   click: %s" % opened)
                for u in after:
                    print("   list %-28s %d item(s): %s"
                          % (u["cls"], u["n"], ", ".join(u["items"])))
                if not after:
                    print("   NO LIST OPENED")

                li = page.evaluate(r"""() => {
                  const el = window.__ansFieldFor('Position');
                  const span = el.parentElement.querySelector('.k-widget, .k-dropdown');
                  for (const type of ['mousedown', 'mouseup', 'click'])
                    span.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window}));
                  return true;
                }""")
                page.wait_for_timeout(1200)
                shape = page.evaluate(r"""() => {
                  const lists = [...document.querySelectorAll('ul.k-list, ul.k-reset, [role=listbox]')]
                    .filter(u => u.offsetParent && u.querySelectorAll('li,[role=option]').length);
                  const u = lists[lists.length - 1];
                  if (!u) return {error: 'no list open'};
                  const items = [...u.querySelectorAll('li,[role=option]')].slice(0, 4).map(li => {
                    const at = {};
                    for (const a of li.attributes) at[a.name] = String(a.value).slice(0, 30);
                    return {text: (li.textContent || '').trim().slice(0, 20), attrs: at};
                  });
                  // is there a plain <select> behind it anywhere?
                  const sel = [...document.querySelectorAll('select')]
                    .map(s => ({name: s.name || s.id, opts: s.options.length}));
                  return {items: items, selects: sel.slice(0, 6)};
                }""")
                print("\n  -- what the option rows carry --")
                if shape.get("error"):
                    print("   %s" % shape["error"])
                else:
                    for it in shape["items"]:
                        print("   %-20s %s" % (it["text"], it["attrs"]))
                    print("   selects on page: %s" % shape["selects"])

                print("\n  -- what setVal actually does --")
                for lab, val in (("Position", "Sales Rep"),
                                 ("Rate of Pay", "10.00"),
                                 ("Department", "400 Sales")):
                    r = page.evaluate(r"""async (a) => {
                      const el = window.__ansFieldFor(a.label);
                      if (!el) return {ok: null, trace: ['no box']};
                      let ok = null, err = '';
                      try { ok = await window.__ansSetVal(el, a.value); }
                      catch (e) { err = String(e && e.message || e).slice(0, 80); }
                      return {ok: ok, err: err,
                              trace: (window.__ansTrace ? window.__ansTrace() : []),
                              now: (el.value || '').slice(0, 24)};
                    }""", {"label": lab, "value": val})
                    print("   %-14s -> %s%s  value=%r"
                          % (lab, r.get("ok"),
                             ("  ERR " + r["err"]) if r.get("err") else "",
                             r.get("now")))
                    for t in (r.get("trace") or [])[:6]:
                        print("        %s" % t)
                    page.wait_for_timeout(600)

                print("\n  -- why fieldFor misses them --")
                for k, v in why.items():
                    print("   %-18s fieldFor=%s" % (k, v["found"]))
                    for L in v["labels"][:2]:
                        print("      label %-22s for=%-14s inner=%-10s sib=%s.%s -> %s"
                              % (L["text"], L["htmlFor"], L["inner"],
                                 L["sibTag"], L["sibClass"][:18], L["sibInput"]))
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
