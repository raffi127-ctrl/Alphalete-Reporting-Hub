"""Dump every control on the Add Employee (create) form. READ ONLY.

WHY. The create form is the one page the rewrite probes never covered:
`probe_fields` opens an EXISTING record's three edit tabs, and the field map
was rebuilt from those. `eco_run.FILL_JS` still drives the create form by
`[ng-model="..."]` and jQuery, and on 2026-11-24 that produced a form where
First Name took its value and Last Name, User Name and Email came back
"required" -- so something in that mapping is wrong and guessing at it has
already cost four live runs.

Types nothing, saves nothing, presses no Save.

    PYTHONPATH=. .venv/bin/python -m automations.apex_new_starts.probe_create
"""
from __future__ import annotations

import json

from automations.apex_new_starts import apex as AX
from automations.apex_new_starts import drive

DUMP = r"""() => {
  const txt = e => (e ? (e.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const out = [];
  for (const el of document.querySelectorAll('input,select,textarea')) {
    let label = '';
    if (el.id) {
      const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (l) label = txt(l);
    }
    if (!label) {
      const g = el.closest('.form-group, .mb-3, .col, td');
      const l = g && g.querySelector('label');
      if (l) label = txt(l);
    }
    out.push({
      label: label,
      tag: el.tagName.toLowerCase(),
      type: el.type || '',
      id: el.id || '',
      name: el.getAttribute('name') || '',
      ngModel: el.getAttribute('ng-model') || '',
      formControl: el.getAttribute('formcontrolname') || '',
      placeholder: el.getAttribute('placeholder') || '',
      cls: (el.className || '').toString().slice(0, 80),
      value: el.type === 'password' ? '' : (el.value || '').slice(0, 40),
      /* VALUES, NOT JUST TEXT. The <select> carries no name, so it does not
         post -- the hidden input beside it does, and what has to go in it is
         the option's VALUE. Reading only the text is what left that unknown
         after the first probe (2026-11-24). */
      options: el.tagName.toLowerCase() === 'select'
        ? [...el.options].map(o => ({text: txt(o), value: o.value})) : undefined,
      /* Which hidden input this select feeds: the one in its own group. */
      pairedWith: el.tagName.toLowerCase() === 'select'
        ? (() => { const g = el.closest('.form-group, .mb-3, .col, td');
                   const h = g && g.querySelector('input[type=hidden][id]');
                   return h ? h.id : ''; })() : undefined,
    });
  }
  /* THE DROPDOWN GROUPS, AS MARKUP. The <select> and the hidden input both
     took their value and the screen still said "Select" (Megan, 2026-11-24),
     so the thing a person looks at is a THIRD element and guessing at it has
     cost enough runs already. */
  const groups = [];
  for (const sel of document.querySelectorAll('select')) {
    const g = sel.closest('.form-group, .mb-3, .col, td, .row');
    groups.push({
      selVisible: !!sel.offsetParent,
      selValue: sel.value,
      selShows: sel.selectedOptions[0] ? sel.selectedOptions[0].text : '',
      html: (g ? g.outerHTML : sel.outerHTML).slice(0, 1400),
    });
  }
  return {url: location.href, groups,
          jquery: !!(window.jQuery || window.$),
          kendo: !!window.kendo,
          angular: !!window.angular,
          controls: out};
}"""


def main() -> int:
    with AX.ApexSession(log=print, login_timeout_s=10 * 60) as s:
        s.require_login()
        drive.load(s.page, log=print)
        # Same route the supervised run takes. A page.goto from the
        # change-password page redirects straight back to it.
        if not drive.to_roster(s.page, log=print):
            print("  could not get to Roster -> Employees")
            return 1
        drive.keep_loaded(s.page, log=print)
        if not drive.open_roster_tab(s.page, "All Employees", log=print):
            print("  could not open All Employees")
            return 1
        if not drive.press_add_employee(s.page, log=print):
            print("  could not press Add Employee")
            return 1
        s.page.wait_for_timeout(3000)
        got = s.page.evaluate(DUMP)
    import pathlib; pathlib.Path("/private/tmp/claude-501/-Users-megan-1st-Claude-Folder/df2e961a-220c-4b7a-ac01-2db5d2cde6b0/scratchpad/create-form.json").write_text(json.dumps(got, indent=2)); print("wrote %d controls" % len(got["controls"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
