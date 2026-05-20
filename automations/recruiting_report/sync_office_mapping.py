"""Build the mapping: Sheet tab name <-> AppStream office_id.

Run once after a fresh `list_all_offices.py` so all-offices.json is current.
Output: office-mapping.json with structure
  {
    "matched":  [{"sheet_tab": "Raf Hidalgo", "office_id": "11280", "as_owner": "Rafael Hidalgo", "confidence": 0.85}, ...],
    "unmatched_sheet_tabs": [...names you'll need to map manually...],
    "unmatched_as_offices": [...AS offices not used by Sheet (just informational)...]
  }
"""
from __future__ import annotations

import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

import gspread

from . import fill

ALL_OFFICES_PATH = Path(__file__).resolve().parent / "all-offices.json"
# Honor the captainship config — fill.MAPPING_PATH points at
# office-mapping.json for Raf, office-mapping-carlos.json for Carlos, etc.
MAPPING_PATH = fill.MAPPING_PATH

# Sheet tabs to ignore when building the office list — the template tab for
# whichever captainship is active. The master tab (Raf Hidalgo / Carlos
# Hidalgo) DOES get included as a regular office: it serves double duty
# (master Table 6 + that owner's own funnel data).
SKIP_TABS = {fill.TEMPLATE_TAB}


def name_score(a: str, b: str) -> float:
    """Loose similarity score between two names. Handles nickname/initial cases."""
    a, b = a.lower().strip(), b.lower().strip()
    if not a or not b:
        return 0.0
    # Direct ratio
    base = SequenceMatcher(None, a, b).ratio()
    # Token-based: if last names match exactly, boost
    a_tokens = set(a.split())
    b_tokens = set(b.split())
    if a_tokens & b_tokens:
        # Last token usually surname
        a_last = a.split()[-1]
        b_last = b.split()[-1]
        if a_last == b_last:
            base = max(base, 0.75)
    # Initials: "JR Young" vs "John Richard Young" — first letters
    a_initials = "".join(t[0] for t in a.split() if t)
    b_initials = "".join(t[0] for t in b.split() if t)
    if a_initials and b_initials and a_initials == b_initials:
        base = max(base, 0.7)
    return base


def main() -> int:
    if not ALL_OFFICES_PATH.exists():
        print(f"Run list_all_offices.py first; expected {ALL_OFFICES_PATH}")
        return 1
    all_offices = json.loads(ALL_OFFICES_PATH.read_text())["offices"]
    print(f"Loaded {len(all_offices)} AS offices.")

    # Auth + list actual sheet tabs
    print("Connecting to Google Sheets via OAuth (browser may open)…")
    sh = fill._client().open_by_key(fill.SPREADSHEET_ID)
    all_tabs = [ws.title for ws in sh.worksheets()]
    print(f"Found {len(all_tabs)} tabs in Sheet.")

    office_tabs = [t for t in all_tabs if t not in SKIP_TABS]
    # Heuristic: real office tabs have a space (first + last). Skip pages like "Notes", "TODO".
    office_tabs = [t for t in office_tabs if " " in t and not t.startswith("_")]
    print(f"After filtering, {len(office_tabs)} look like office tabs:")
    for t in office_tabs[:10]:
        print(f"  - {t}")
    if len(office_tabs) > 10:
        print(f"  … and {len(office_tabs) - 10} more")

    matched = []
    unmatched_tabs = []
    used_office_ids = set()
    for tab in office_tabs:
        scored = []
        for off in all_offices:
            owner = off.get("owner") or ""
            scored.append((name_score(tab, owner), off))
        scored.sort(key=lambda x: -x[0])
        best = scored[0] if scored else None
        if best and best[0] >= 0.6:
            matched.append({
                "sheet_tab": tab,
                "office_id": best[1].get("office_id"),
                "as_owner": best[1].get("owner"),
                "as_company": best[1].get("company"),
                "confidence": round(best[0], 2),
            })
            used_office_ids.add(best[1].get("office_id"))
        else:
            top3 = [
                {"office_id": s[1].get("office_id"), "owner": s[1].get("owner"), "score": round(s[0], 2)}
                for s in scored[:3]
            ]
            unmatched_tabs.append({"sheet_tab": tab, "top_candidates": top3})

    unmatched_as = [
        {"office_id": o.get("office_id"), "owner": o.get("owner"), "company": o.get("company")}
        for o in all_offices
        if o.get("office_id") not in used_office_ids
    ]

    out = {
        "matched_count": len(matched),
        "unmatched_tab_count": len(unmatched_tabs),
        "unmatched_as_office_count": len(unmatched_as),
        "matched": matched,
        "unmatched_sheet_tabs": unmatched_tabs,
        "unmatched_as_offices": unmatched_as,
    }
    MAPPING_PATH.write_text(json.dumps(out, indent=2))
    print(f"\n✓ Mapping written to {MAPPING_PATH}")
    print(f"  matched={len(matched)}, unmatched sheet tabs={len(unmatched_tabs)}, AS offices unused={len(unmatched_as)}")

    if matched:
        print("\nLow-confidence matches (review these):")
        low = sorted([m for m in matched if m["confidence"] < 0.85], key=lambda m: m["confidence"])
        for m in low[:15]:
            print(f"  {m['confidence']:.2f}  '{m['sheet_tab']}' -> '{m['as_owner']}' (id {m['office_id']})")

    if unmatched_tabs:
        print("\nUnmatched sheet tabs (need manual mapping):")
        for u in unmatched_tabs[:20]:
            top = u["top_candidates"][0] if u["top_candidates"] else None
            top_str = f"top: '{top['owner']}' ({top['score']})" if top else ""
            print(f"  - {u['sheet_tab']!r}   {top_str}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
