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


NOT_OWNER_TABS = ("ad groups", "template", "copy of")      # tabs in the ARS files that aren't an office
ROSTER_FILE = __import__("pathlib").Path(__file__).with_name("ars_offices.json")


def _known_ids() -> Dict[str, Tuple[str, str]]:
    """{normalised name: (office id, where it came from)} from every office-id
    list the Hub already keeps. First one wins, in the order below."""
    import json
    from pathlib import Path
    from automations.interviewer_retention.from_calendar import _key
    rr = Path(__file__).resolve().parents[1] / "recruiting_report"
    out: Dict[str, Tuple[str, str]] = {}

    def add(name, oid, src):
        k = _key(name or "")
        if k and oid and k not in out:
            out[k] = (str(oid), src)

    for name, oid in org_offices():
        add(name, oid, "org roster")
    for r in json.loads((rr / "office-mapping.json").read_text())["confirmed"]:
        add(r.get("as_owner"), r.get("office_id"), "focus office mapping")
        add(r.get("sheet_tab"), r.get("office_id"), "focus office mapping")
    for name, oid in json.loads((rr / "icd_office_mappings.json").read_text()).items():
        add(name, oid, "icd office mappings")
    from automations.daily_eod_appstream.run import EXTRA_OFFICES
    for name, oid in EXTRA_OFFICES.items():
        add(name, oid, "daily eod appstream")
    from automations.raf_daily_update.offices import OFFICES as DU
    for o in DU.values():
        add(o.owner, o.office_id, "daily update offices")
    import re
    for o in json.loads((rr / "all-offices.json").read_text())["offices"]:
        m = re.match(r"(\d{4,6})\n([^\n]+)\n", o.get("raw", ""))
        if m:
            add(m.group(2), m.group(1), "appstream office list (saved)")
    return out


def ars_offices(logfn=print) -> List[Dict]:
    """Card step 4.7.5: every owner tab on Camila's six ARS files, with its
    AppStream office id where a list proves it. Megan 11/27: only ICDs on those
    sheets get this; nobody else is added."""
    from automations.first_to_second_below_mark import ars_reports as ar
    import re
    from automations.interviewer_retention.from_calendar import _key
    ids = _known_ids()
    rows = []
    for (wb, tab) in sorted(set(ar.build_index(logfn=lambda *a: None).values())):
        name = tab.strip()
        if any(x in name.lower() for x in NOT_OWNER_TABS):
            continue
        k = _key(name)
        hit = ids.get(k)
        if not hit and not re.search(r"\d|funnel|test", k):   # 'Drew Tepper New' -> 'Drew Tepper'
            words = k.split()               # ('Raf Hidalgo 2nd funnel' is its own office: no loose match)
            cands = [v for n, v in ids.items()
                     if n.split()[:1] == words[:1] and (set(n.split()) <= set(words) or set(words) <= set(n.split()))]
            hit = cands[0] if len({c[0] for c in cands}) == 1 else None
        rows.append({"workbook": wb, "tab": tab, "office_id": hit[0] if hit else "",
                     "source": hit[1] if hit else ""})
    return rows


def main() -> int:
    import json
    from automations.first_to_second_below_mark import ars_reports as ar
    if "--ars" in sys.argv:
        rows = ars_offices()
        ROSTER_FILE.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        have = [r for r in rows if r["office_id"]]
        print(f"{len(rows)} owner tabs on the six ARS files: {len(have)} with an AppStream office id "
              f"-> {ROSTER_FILE.name}")
        for r in rows:
            print(f"  {r['office_id'] or '  ?   ':6} {r['tab'].strip()[:28]:28} {r['workbook'][:22]:22} {r['source']}")
        return 0
    index = ar._index(logfn=lambda *a: None)
    rows = [(o, oid, ars_tab(o, index)) for o, oid in org_offices()]
    have = [r for r in rows if r[2]]
    print(f"{len(rows)} offices with an AppStream id: {len(have)} have an ARS tab")
    for o, oid, hit in rows:
        print(f"  {oid:6} {o:24} -> {hit[0] + ' / ' + hit[2] if hit else 'NO ARS TAB'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
