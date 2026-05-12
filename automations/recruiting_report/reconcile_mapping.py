"""Reconcile the auto-generated office-mapping.json with user feedback.

Produces a clean office-mapping.json with three categories:
  - confirmed:    sheet_tab + office_id pairs we'll write data for
  - needs_review: sheet_tab pairs we'll mark red+bold; user fixes office_id later
  - skip:         admin/template tabs to ignore entirely

Edit the FLAGGED_BAD and ADMIN_TABS sets as the user corrects mappings.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MAPPING_PATH = Path(__file__).resolve().parent / "office-mapping.json"

# Auto-matches we don't trust; route to needs_review until manually mapped.
FLAGGED_BAD: set = set()

# Hardcoded sheet-tab -> office_id mappings. These take precedence over
# auto-match. Use this for offices that exist in some AS accounts but not
# others — the script will try the office_id and skip cleanly if not visible.
# Source IDs were discovered via the rcaptain account.
HARDCODED_OFFICE_IDS = {
    "Chan Park":          "19588",
    "DMari Longmire":     "22989",
    "Francisco Castillo": "22532",
    "JC Pascual":         "22976",
    "Milly Villagrana":   "22001",
    "Natalia Gwarda":     "23431",
    "Nigel Gilbert":      "22435",
    "Oren Shezaf":        "22536",
    "Preppie Olison":     "21373",
    "Starr Rodenhurst":   "17573",
}

# Tabs whose data should sum across MULTIPLE AS offices (e.g. an ICD with
# two locations). The primary office_id is in HARDCODED_OFFICE_IDS or auto-
# matched; this dict adds extra office_ids whose counts get summed in.
HARDCODED_SIBLINGS = {
    "Chan Park": ["22057"],  # Nola Management Group, Inc. 2nd
}

# Admin / template / aggregate tabs that aren't ICD offices.
# Raf Hidalgo is INTENTIONALLY excluded — her tab is both the master view AND
# her own office data, so we treat it as a regular office.
ADMIN_TABS = {
    "Template 1",
    "Template Fiber",
    "Country Sales Board (backup copy)",
    "Country Sales Board ",  # trailing space, exact tab title
    "Country Stats",
    "Country Metrics",
    "Country Metrics pilot",
    "Copy of Country Sales Board ",
    "Copy of Country Stats",
    "Daily Focus Report",
    "Focus Office - Sales",
    "ATT owners list",
    "Rafs",
    # Discontinued offices — preserved in Sheet but no longer pulling data
    "Zach Hogue",
    "Eric Zech",
    "Wayne Rude",
    "Sharon Stephen",   # no longer in business
    "Salik Mallick",    # not actively recruiting
    "Rason Williams",   # no longer in business; Megan will delete tab
}


def main() -> int:
    data = json.loads(MAPPING_PATH.read_text())
    raw_matched = data.get("matched", [])
    raw_unmatched = data.get("unmatched_sheet_tabs", [])

    confirmed = []
    needs_review = []
    skip = []

    seen_office_ids = set()

    # First pass: matched entries
    for m in raw_matched:
        tab = m["sheet_tab"]
        if tab in ADMIN_TABS:
            skip.append({"sheet_tab": tab, "reason": "admin tab"})
            continue
        if tab in FLAGGED_BAD:
            needs_review.append({
                "sheet_tab": tab,
                "reason": "auto-match flagged bad",
                "auto_match": {
                    "office_id": m["office_id"],
                    "as_owner": m["as_owner"],
                    "confidence": m["confidence"],
                },
            })
            continue
        if m["office_id"] in seen_office_ids:
            needs_review.append({
                "sheet_tab": tab,
                "reason": "office_id already claimed by another tab",
                "auto_match": {
                    "office_id": m["office_id"],
                    "as_owner": m["as_owner"],
                    "confidence": m["confidence"],
                },
            })
            continue
        confirmed.append({
            "sheet_tab": tab,
            "office_id": m["office_id"],
            "as_owner": m["as_owner"],
            "as_company": m["as_company"],
            "confidence": m["confidence"],
        })
        seen_office_ids.add(m["office_id"])

    # Second pass: unmatched entries
    for u in raw_unmatched:
        tab = u["sheet_tab"]
        if tab in ADMIN_TABS:
            skip.append({"sheet_tab": tab, "reason": "admin tab"})
        else:
            needs_review.append({
                "sheet_tab": tab,
                "reason": "no auto-match",
                "top_candidates": u.get("top_candidates", []),
            })

    # Third pass: ensure every tab in ADMIN_TABS is in skip, even if it never
    # showed up in the sync output (e.g., tabs without spaces).
    skip_seen = {s["sheet_tab"] for s in skip}
    for admin_tab in ADMIN_TABS:
        if admin_tab not in skip_seen:
            skip.append({"sheet_tab": admin_tab, "reason": "admin tab (filtered before sync)"})

    # Fourth pass: apply hardcoded overrides. Move tabs from needs_review to
    # confirmed using the manual office_id mapping. The script will try this
    # ID and skip cleanly if not visible in the current AS account (preserves
    # existing data).
    confirmed_tabs = {c["sheet_tab"] for c in confirmed}
    for tab, office_id in HARDCODED_OFFICE_IDS.items():
        if tab in confirmed_tabs:
            continue  # auto-match already exists; leave it alone
        needs_review[:] = [n for n in needs_review if n["sheet_tab"] != tab]
        confirmed.append({
            "sheet_tab": tab,
            "office_id": office_id,
            "as_owner": tab,
            "as_company": "(hardcoded — may not be visible in all AS accounts)",
            "confidence": 1.0,
            "hardcoded": True,
        })

    # Fifth pass: attach sibling office_ids to tabs with multiple AS offices.
    # The script will iterate primary + siblings, writing each to its own
    # section on the tab.
    for c in confirmed:
        siblings = HARDCODED_SIBLINGS.get(c["sheet_tab"])
        if siblings:
            c["siblings"] = siblings

    out = {
        "confirmed_count": len(confirmed),
        "needs_review_count": len(needs_review),
        "skip_count": len(skip),
        "confirmed": confirmed,
        "needs_review": needs_review,
        "skip": skip,
    }
    MAPPING_PATH.write_text(json.dumps(out, indent=2))
    print(f"Reconciled mapping → {MAPPING_PATH}")
    print(f"  confirmed:    {len(confirmed)} (will write data)")
    print(f"  needs_review: {len(needs_review)} (red+bold tab name; no data write)")
    print(f"  skip:         {len(skip)} (admin tabs; ignored)")

    print("\nNeeds review:")
    for n in needs_review:
        extra = ""
        if "auto_match" in n:
            am = n["auto_match"]
            extra = f"  [had: {am['as_owner']!r} id={am['office_id']} {am['confidence']}]"
        print(f"  - {n['sheet_tab']!r:35s} {n['reason']}{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
