"""Which ARS tab is each office's (card step 3.2: "everyone should have one").

Owner -> tab uses the Below the Mark board's own lookup
(first_to_second_below_mark.ars_reports.find_tab: exact, its alias file, a
narrow fuzzy pass), then the shared ICD Aliases sheet for a spelling the tab
uses (CLAUDE.md: name mismatches go on that sheet, never a per-report patch).
'Roshan Amin' -> 'Roshan Ahmad' went on it 2026-11-27 after 22 of 22 people
who showed up in office 19833 on 11/24 were found on that tab.

    python -m automations.interviewer_retention.offices
"""
from __future__ import annotations

import sys
from typing import Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

EXTRA = [("Colten Wright", "14733")]          # South Shore; the org roster has no id


def org_offices() -> List[Tuple[str, str]]:
    """[(owner, AppStream office id)] for every org office with an id."""
    from automations.funnel_board.roster import ORG
    out = [(name, oid) for name, oid, _ in ORG if oid]
    have = {oid for _, oid in out}
    return out + [o for o in EXTRA if o[1] not in have]


def ars_tab(owner: str, index=None, raw_aliases=None) -> Optional[Tuple[str, str, str]]:
    """(workbook title, workbook id, tab) or None."""
    from automations.first_to_second_below_mark import ars_reports as ar
    from automations.focus_office_att import aliases as al
    index = index if index is not None else ar._index(logfn=lambda *a: None)
    hit = ar.find_tab(owner, index)
    if not hit:            # the alias sheet takes ~30s to load: only on a miss
        raw = raw_aliases if raw_aliases is not None else al.load_aliases()
        names = list(raw.get(owner, [])) + [c for c, al_ in raw.items() if owner in al_]
        for cand in names:
            hit = ar.find_tab(cand, index)
            if hit:
                break
    if not hit:
        return None
    wb, tab = hit
    return wb, ar.ARS_WORKBOOKS.get(wb, ""), tab


def owner_of(office: str) -> str:
    for owner, oid in org_offices():
        if oid == office:
            return owner
    raise LookupError(f"office {office} is not on the org roster")


def main() -> int:
    from automations.first_to_second_below_mark import ars_reports as ar
    from automations.focus_office_att import aliases as al
    index = ar._index(logfn=lambda *a: None)
    rows = [(o, oid, ars_tab(o, index)) for o, oid in org_offices()]
    have = [r for r in rows if r[2]]
    print(f"{len(rows)} offices with an AppStream id: {len(have)} have an ARS tab")
    for o, oid, hit in rows:
        print(f"  {oid:6} {o:24} -> {hit[0] + ' / ' + hit[2] if hit else 'NO ARS TAB'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
