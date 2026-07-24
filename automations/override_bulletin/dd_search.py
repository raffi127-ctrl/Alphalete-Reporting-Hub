"""Search the raw Tableau ORG DD Detail crosstab for specific ICD names. LUCY 1.

One question this answers: do the bulletin-only names — Justin Fermin, Marcos
Barbosa, Karrington Moody, Milan Godbolt — have weekly DD data in the Tableau
source, or do they exist ONLY as the single manual figure the VA types onto the
podium list? (DD_SOURCES.md, "Still open on the podium".) If Tableau has them,
they can be wired in as excluded-but-tracked rows and get full four-week history
like Jacob Dover. If it does not, the single manual number is all that exists and
the '—' in Tracked Separately is the honest thing to show.

READ-ONLY. Downloads the `ORG DD Detail` crosstab (the same view the override
fill already uses) and searches every cell for the target names. Writes nothing
to any report tab — results land on a throwaway `_dd_search` tab of the override
workbook, readable from any machine, plus output/override_bulletin/dd_search.csv.

    lucy rerun dd_name_search          # on Lucy 1 (needs Raf's Tableau login)

The crosstab is HIERARCHICAL (empty dimensions collapse per row), so a name and
its amount are not in fixed columns — we match by CONTENT, exactly as
pulls.parse_dd_captain does: any cell equal to a target name marks the row, and
the amount is read from that row's money cells with their dated descriptions.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from automations.override_bulletin import pulls as P
from automations.override_bulletin import fill as F

WORKBOOK_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
DUMP_TAB = "_dd_search"
OUT = Path(__file__).resolve().parents[2] / "output" / "override_bulletin"

# The four whose history is in question. Aliases are resolved too, so a Tableau
# spelling still matches the name the bulletin uses.
TARGETS = ["Justin Fermin", "Marcos Barbosa", "Karrington Moody", "Milan Godbolt"]

_WK_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})")


def _keys(names, aliases):
    """Every name folded to a match key, plus its alias-canonical key — so a
    Tableau spelling that differs only by alias still lands."""
    out = {}
    for n in names:
        out[P._norm_name(n)] = n
        out[P._norm_name(F.canon(n, aliases))] = n
    return out


def search(page=None, verbose=True):
    aliases = F.load_alias_map()
    keys = _keys(TARGETS, aliases)
    OUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUT / "dd_search.csv"

    own = page is None
    ctx = None
    if own:
        from automations.shared.tableau_patchright import tableau_session
        ctx = tableau_session(headless=True, verbose=verbose)
        page = ctx.__enter__()
    try:
        from automations.shared.tableau_patchright import download_crosstab_patchright
        download_crosstab_patchright(P.DD_DETAIL_VIEW, P.DD_DETAIL_SHEET,
                                     csv_path, page=page, verbose=verbose)
    finally:
        if own and ctx is not None:
            ctx.__exit__(None, None, None)

    rows = P.read_crosstab(csv_path)
    if verbose:
        print(f"-> ORG DD Detail: {len(rows)} row(s)")

    # Every distinct owner-ish cell, so a name that is present under an unexpected
    # spelling can still be eyeballed on the dump tab.
    all_names = set()
    for r in rows[1:]:
        for c in r:
            s = (c or "").strip()
            if s and re.search(r"[A-Za-z]", s) and not P._num_locale(s) \
               and len(s.split()) <= 4 and "$" not in s:
                all_names.add(s)

    found = {}                       # target display name -> [(week, amount, desc)]
    for r in rows[1:]:
        hit = next((keys[P._norm_name(c)] for c in r
                    if P._norm_name(c) in keys), None)
        if not hit:
            continue
        amt = max((P._num_locale(c) or 0) for c in r)
        desc = next((str(c) for c in r if _WK_RE.search(str(c))), "")
        m = _WK_RE.search(desc)
        wk = f"{int(m.group(1))}.{int(m.group(2))}.{m.group(3)[-2:]}" if m else "(no week)"
        found.setdefault(hit, []).append((wk, amt, desc.strip()[:80]))

    out = [["TARGET", "IN TABLEAU?", "WEEK", "AMOUNT", "DESCRIPTION"]]
    for name in TARGETS:
        hits = found.get(name)
        if not hits:
            # Not in the crosstab under this name or its alias — check whether a
            # near-spelling exists among the owner cells, so a miss is not just a
            # spelling gap masquerading as "genuinely absent".
            near = sorted(n for n in all_names
                          if name.split()[0].lower() in n.lower()
                          or name.split()[-1].lower() in n.lower())
            out.append([name, "NO — not found",
                        "", "", ("near spellings: " + ", ".join(near[:6])) if near
                        else "no similar name in the crosstab either"])
        else:
            for wk, amt, desc in sorted(hits):
                out.append([name, "YES", wk, f"${amt:,.2f}", desc])
    if verbose:
        for r in out:
            print(" | ".join(str(c)[:70] for c in r))

    _dump(out)
    print(f"\n✓ {len(out)} row(s) → '{DUMP_TAB}' tab + {csv_path}")
    return found


def _dump(rows):
    """Mirror the result to a throwaway tab so it is readable from any machine
    (same pattern as credico.report._dump_to_sheet). Never touches a report tab."""
    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(WORKBOOK_ID)
    try:
        ws = sh.worksheet(DUMP_TAB)
        ws.clear()
    except Exception:  # noqa: BLE001
        ws = sh.add_worksheet(title=DUMP_TAB, rows=max(100, len(rows) + 20), cols=5)
    if len(rows) > ws.row_count:
        ws.add_rows(len(rows) - ws.row_count + 10)
    ws.update(values=[[str(c) for c in r] for r in rows],
              range_name=f"A1:E{len(rows)}", value_input_option="RAW")


def main(argv=None):
    try:
        search()
    except Exception as e:  # noqa: BLE001
        print(f"✗ {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
