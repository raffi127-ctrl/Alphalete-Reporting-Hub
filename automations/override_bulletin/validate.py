"""Lucy-1 diagnostic: are the 8 unmatched actives NAME MISMATCHES or genuinely
absent from the source?

Dumps the ORG Override Summary's owner names next to the sheet's active roster,
and for every unmatched active shows its closest source names (difflib). A close
near-miss => an ICD Aliases entry (canonical, alias) — never a per-report patch.
Writes to `_validate_out`. RUN ON LUCY 1.
"""
from __future__ import annotations

import difflib
import sys
from pathlib import Path

WORKBOOK_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
OUT = Path("output/override_bulletin/validate")
TAB = "_validate_out"
WEEK_HDR = "7/12/2026"


def main(argv=None) -> int:
    from automations.shared.tableau_patchright import (
        tableau_session, download_crosstab_patchright)
    from automations.override_bulletin import pulls as P
    from automations.override_bulletin import fill as F
    from automations.recruiting_report import fill as _fill
    OUT.mkdir(parents=True, exist_ok=True)
    dump = []

    def row(*c):
        dump.append([str(x) for x in c])

    wb = _fill._client().open_by_key(WORKBOOK_ID)
    ws = wb.worksheet(F.SANDBOX_TAB)
    roster = F.read_roster(ws)
    active = {k: disp for k, (_, a, disp) in roster.items() if a}

    with tableau_session(headless=True, verbose=True) as page:
        url = P._with_filter(P.ORG_SUMMARY_VIEW, "Period", "Period 2026-7")
        download_crosstab_patchright(url, P.ORG_SUMMARY_SHEET, OUT / "org.csv",
                                     page=page, verbose=True)
        rows = P.read_crosstab(OUT / "org.csv")

    # raw owner names as they appear in the source (col 0, non-blank, non-total)
    raw = []
    for r in rows[3:]:
        n = (r[0] if r else "").strip()
        if n and n.lower() not in ("grand total", "total", "total general"):
            raw.append(n)
    src = {P._norm_name(n): n for n in raw}
    reg = P.parse_override_summary(rows, WEEK_HDR)

    row(f"=SOURCE owners ({len(src)}) vs ACTIVE roster ({len(active)})=")
    row("--- source names (normalized -> raw) ---")
    for k in sorted(src):
        row(f"  {k}", src[k], f"wk={reg.get(k, '')}")
    row("--- active roster ---")
    for k in sorted(active):
        row(f"  {k}", active[k], "MATCHED" if k in src else "** UNMATCHED **")

    row("=UNMATCHED actives -> closest source names=")
    for k in sorted(active):
        if k in src:
            continue
        near = difflib.get_close_matches(k, list(src), n=3, cutoff=0.5)
        row(f"  {active[k]!r}", f"norm={k}",
            *[f"~{n} ({src[n]}) score={difflib.SequenceMatcher(None, k, n).ratio():.2f}"
              for n in near] or ["no near match -> likely genuinely absent"])

    try:
        try:
            out_ws = wb.worksheet(TAB)
            out_ws.clear()
        except Exception:  # noqa: BLE001
            out_ws = wb.add_worksheet(title=TAB, rows=300, cols=40)
        out_ws.update([[str(c)[:90] for c in r] for r in dump], "A1",
                      value_input_option="RAW")
        print(f"wrote {len(dump)} rows to {TAB!r}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"couldn't write {TAB}: {type(e).__name__}: {e}", flush=True)
    print("name diagnostic done.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
