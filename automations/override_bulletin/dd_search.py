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

    header = rows[0] if rows else []
    # Columns found BY HEADER LABEL, never index (CLAUDE.md) — the layout,
    # decoded from the first structure dump 2026-07-24:
    #   cl.ICD Owner Name  = the owner        (name we match on)
    #   cl.DD Week         = the DD week      (M/D/YYYY)
    #   Total $ to ICD     = the dollar line  (NOT cl.Account ID, a huge ID that
    #                                          the first pass mistook for money)
    oc = P._hdr_col(header, "cl.ICD Owner Name")
    wc = P._hdr_col(header, "cl.DD Week")
    ac = P._hdr_col(header, "Total $ to ICD")

    per = {}          # target name -> {dd_week: summed Total $ to ICD}
    rc = {}           # target name -> row count
    for r in rows[1:]:
        nm = r[oc].strip() if oc is not None and oc < len(r) else ""
        hit = keys.get(P._norm_name(nm))
        if not hit:
            continue
        wk = r[wc].strip() if wc is not None and wc < len(r) else "(no week)"
        amt = P._num_locale(r[ac]) if ac is not None and ac < len(r) else None
        d = per.setdefault(hit, {})
        d[wk] = round(d.get(wk, 0.0) + (amt or 0.0), 2)
        rc[hit] = rc.get(hit, 0) + 1

    out = [["TARGET", "IN TABLEAU?", "DD WEEK", "TOTAL $ TO ICD", "ROWS"]]
    for name in TARGETS:
        weeks = per.get(name)
        if not weeks:
            near = sorted(n for n in all_names
                          if name.split()[0].lower() in n.lower()
                          or name.split()[-1].lower() in n.lower())
            out.append([name, "NO", "", "",
                        ("near: " + ", ".join(near[:5])) if near else "no match"])
            continue
        first = True
        for wk, amt in sorted(weeks.items()):
            out.append([name if first else "", "YES" if first else "",
                        wk, f"${amt:,.2f}", str(rc[name]) if first else ""])
            first = False
    # The columns used, so the mapping is auditable on the tab.
    out.append([""])
    out.append(["columns used", f"owner=col {oc} · week=col {wc} · amount=col {ac}",
                "(by header label)", "", ""])
    if verbose:
        for r in out:
            print(" | ".join(str(c) for c in r))

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
