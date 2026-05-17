"""Extract the complete office list from AppStream's preloaded autocomplete.

The searchMC input uses jQuery UI autocomplete; its `source` option is either
an array (preloaded) or a function. We probe both. Falls back to
alphabet-iteration if direct extraction fails.

Merges into all-offices.json (dedup by office_id): list of
{office_id, owner, company, raw}. Each AppStream account sees only its
own offices, so run this once per account (rhidalgo, CarlosNLR, …) to
build the full list.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from string import ascii_lowercase, digits

from playwright.sync_api import sync_playwright

CDP_URL = "http://localhost:9222"
OUT_PATH = Path(__file__).resolve().parent / "all-offices.json"


def parse_item(raw: str) -> dict:
    """Parse '11280\\nRafael Hidalgo\\nALPHALETE MARKETING, INC.' into fields."""
    parts = [p.strip() for p in raw.split("\n") if p.strip()]
    return {
        "office_id": parts[0] if len(parts) >= 1 else None,
        "owner": parts[1] if len(parts) >= 2 else None,
        "company": parts[2] if len(parts) >= 3 else None,
        "raw": raw,
    }


def main() -> int:
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

        # Approach 1 — pull the autocomplete source directly.
        source_data = target.evaluate(
            """
            () => {
              if (typeof jQuery === 'undefined') return {error: 'no jQuery'};
              const inst = jQuery('#searchMC').autocomplete('instance');
              if (!inst) return {error: 'no autocomplete instance'};
              const src = inst.options.source;
              if (Array.isArray(src)) {
                return {kind: 'array', length: src.length, sample: src.slice(0,3), data: src};
              }
              if (typeof src === 'function') {
                return {kind: 'function', source_str: src.toString().slice(0, 600)};
              }
              if (typeof src === 'string') {
                return {kind: 'url', url: src};
              }
              return {kind: 'unknown', type: typeof src};
            }
            """
        )

        offices = []

        if isinstance(source_data, dict) and source_data.get("kind") == "array":
            print(f"✓ Found preloaded source array with {source_data['length']} items.")
            for item in source_data["data"]:
                if isinstance(item, dict):
                    offices.append({
                        "office_id": str(item.get("id") or item.get("value") or "").strip(),
                        "owner": item.get("label", "").strip() if isinstance(item.get("label"), str) else "",
                        "company": item.get("company", "") if isinstance(item.get("company"), str) else "",
                        "raw": json.dumps(item),
                    })
                else:
                    offices.append(parse_item(str(item)))
        else:
            # Fallback: iterate alphabet, dedupe by office_id
            print(f"⚠ Direct source not array: {source_data}")
            print("  Falling back to alphabet iteration…")
            seen = set()
            for ch in list(ascii_lowercase) + list(digits):
                target.locator("#searchMC").click()
                target.locator("#searchMC").fill("")
                target.locator("#searchMC").type(ch, delay=50)
                target.wait_for_timeout(700)
                items = target.evaluate(
                    """
                    () => {
                      const found = [];
                      document.querySelectorAll('.ui-autocomplete li, .ui-menu li').forEach(li => {
                        const t = (li.innerText || '').trim();
                        if (t.length > 0) found.push(t);
                      });
                      return found;
                    }
                    """
                )
                added = 0
                for raw in items:
                    parsed = parse_item(raw)
                    key = parsed["office_id"] or raw
                    if key not in seen:
                        seen.add(key)
                        offices.append(parsed)
                        added += 1
                print(f"  '{ch}' → +{added} (total {len(offices)})")
            # Clear input to leave session clean
            target.locator("#searchMC").fill("")
            target.locator("body").click(position={"x": 50, "y": 50})

        # Merge with whatever's already in all-offices.json. Each AppStream
        # account (rhidalgo, CarlosNLR, …) sees only its own offices, so
        # scraping is additive — run this once per account to build the
        # full list. Dedupe by office_id.
        existing = []
        if OUT_PATH.exists():
            try:
                existing = json.loads(OUT_PATH.read_text()).get("offices", [])
            except Exception:
                existing = []
        by_id: dict = {}
        for o in existing + offices:
            oid = str(o.get("office_id") or "").strip()
            if oid:
                by_id[oid] = o
        merged = sorted(by_id.values(), key=lambda o: (o.get("owner") or "").lower())
        OUT_PATH.write_text(json.dumps({"count": len(merged), "offices": merged}, indent=2))
        print(f"\n✓ Merged {len(offices)} scraped + {len(existing)} already on file "
              f"→ {len(merged)} unique offices in {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
