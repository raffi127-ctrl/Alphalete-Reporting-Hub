"""Inspect the office switcher (id=searchMC) on the attached AppStream page.

Tries to figure out how to enumerate all offices the user has access to:
  1. Look at the searchMC element, its surrounding form, data-* attributes
  2. Look for any embedded JSON / select / hidden datalist with office IDs
  3. Click the input and capture any AJAX requests it triggers
  4. Type a single space and see what autocomplete returns
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from patchright.sync_api import sync_playwright

CDP_URL = "http://localhost:9222"
OUT_PATH = Path(__file__).resolve().parent / "office-switcher-probe.json"


def main() -> int:
    network_log: list = []
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        target = None
        for ctx in browser.contexts:
            for page in ctx.pages:
                if "applicantstream" in page.url:
                    target = page
                    break
            if target:
                break
        if not target:
            print("No applicantstream tab open")
            return 1

        # 1. Inspect the searchMC element
        element_info = target.evaluate(
            """
            () => {
              const el = document.getElementById('searchMC');
              if (!el) return {error: 'not found'};
              const result = {
                tag: el.tagName,
                attrs: {},
                outerHTML_truncated: el.outerHTML.slice(0, 1000),
                parent_form_action: el.closest('form')?.action || null,
                parent_form_html_truncated: el.closest('form')?.outerHTML.slice(0, 1500) || null,
              };
              for (const a of el.attributes) result.attrs[a.name] = a.value;
              // Look for nearby datalist or hidden select with options
              const nearby_lists = [];
              document.querySelectorAll('datalist, select').forEach(l => {
                if (l.options && l.options.length > 5) {
                  nearby_lists.push({
                    tag: l.tagName,
                    id: l.id,
                    name: l.name,
                    option_count: l.options.length,
                    first_5: Array.from(l.options).slice(0,5).map(o => ({value: o.value, text: o.text || o.textContent})),
                  });
                }
              });
              result.candidate_lists = nearby_lists;
              return result;
            }
            """
        )

        # 2. Look for global JS variables that may hold the office list
        globals_check = target.evaluate(
            """
            () => {
              const found = {};
              for (const k of Object.keys(window)) {
                if (/office|mc|location|account/i.test(k)) {
                  try {
                    const v = window[k];
                    if (Array.isArray(v) && v.length > 5) {
                      found[k] = {type: 'array', length: v.length, sample: v.slice(0,3)};
                    } else if (typeof v === 'object' && v !== null && Object.keys(v).length > 5) {
                      found[k] = {type: 'object', keys: Object.keys(v).slice(0,10)};
                    }
                  } catch(e) {}
                }
              }
              return found;
            }
            """
        )

        # 3. Watch network for autocomplete request when we type into searchMC
        target.on("request", lambda req: network_log.append({
            "method": req.method,
            "url": req.url,
            "type": req.resource_type,
        }) if "applicantstream" in req.url else None)

        # Click the search box and type one character to trigger autocomplete
        try:
            target.locator("#searchMC").click(timeout=3000)
            target.locator("#searchMC").fill("a")
            target.wait_for_timeout(2000)  # let any AJAX fire
        except Exception as e:
            element_info["click_error"] = str(e)

        # Capture any visible dropdown contents AFTER typing
        dropdown_after_type = target.evaluate(
            """
            () => {
              // Common autocomplete library DOM patterns
              const candidates = [
                '.ui-autocomplete',
                '.ui-menu',
                '.autocomplete-results',
                '.dropdown-menu.show',
                '.select2-results',
                'ul[role=listbox]',
                '[role=listbox]',
              ];
              const results = [];
              for (const sel of candidates) {
                const els = document.querySelectorAll(sel);
                els.forEach(el => {
                  const items = Array.from(el.querySelectorAll('li, .item, [role=option]'))
                    .map(i => (i.innerText || '').trim())
                    .filter(t => t.length > 0)
                    .slice(0, 60);
                  if (items.length > 0) results.push({selector: sel, items: items});
                });
              }
              return results;
            }
            """
        )

        # Clear what we typed so we don't disturb the user's session
        try:
            target.locator("#searchMC").fill("")
            target.locator("body").click(position={"x": 50, "y": 50})
        except Exception:
            pass

        out = {
            "element_info": element_info,
            "candidate_globals": globals_check,
            "dropdown_after_type": dropdown_after_type,
            "network_after_type": [n for n in network_log if "applicantstream" in n["url"]],
        }
        OUT_PATH.write_text(json.dumps(out, indent=2, default=str))
        print(f"✓ Wrote probe to {OUT_PATH}")
        print(f"  - Dropdown candidates found: {len(dropdown_after_type)}")
        print(f"  - Network requests captured: {len(out['network_after_type'])}")
        if dropdown_after_type:
            for d in dropdown_after_type:
                print(f"    {d['selector']}: {len(d['items'])} items, first = {d['items'][:3]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
