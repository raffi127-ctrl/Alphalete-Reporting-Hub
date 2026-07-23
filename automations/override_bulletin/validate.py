"""Lucy-1 final validation (ONE run):
  A. Regular overrides — download 'ORG Override Summary' (Period 2026-7), dump the
     available week-header columns, parse per candidate week (# owners + sample).
  B. Full assemble — run the whole pull→assemble for the target week on the
     SANDBOX tab (dry-run), dump section-1 / section-2 / unmatched so the numbers
     can be eyeballed before any write.
Writes to `_validate_out`. RUN ON LUCY 1.
"""
from __future__ import annotations

import sys
from pathlib import Path

WORKBOOK_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
OUT = Path("output/override_bulletin/validate")
TAB = "_validate_out"
TARGETS = ["7.12.26"]        # best source coverage today (ORG latest = 07/12)


def main(argv=None) -> int:
    from automations.shared.tableau_patchright import (
        tableau_session, download_crosstab_patchright)
    from automations.override_bulletin import pulls as P
    from automations.override_bulletin import fill as F
    from automations.override_bulletin import run as R
    from automations.recruiting_report import fill as _fill
    OUT.mkdir(parents=True, exist_ok=True)
    dump = []

    def row(*c):
        dump.append([str(x) for x in c])

    wb = _fill._client().open_by_key(WORKBOOK_ID)
    ws = wb.worksheet(F.SANDBOX_TAB)
    roster = F.read_roster(ws)
    captains = F.read_captains(ws)

    with tableau_session(headless=True, verbose=True) as page:
        # A) regular override summary — structure + parse per week
        row("=A: ORG Override Summary (Period 2026-7)=")
        try:
            url = P._with_filter(P.ORG_SUMMARY_VIEW, "Period", "Period 2026-7")
            download_crosstab_patchright(url, P.ORG_SUMMARY_SHEET, OUT / "org.csv",
                                         page=page, verbose=True)
            rows = P.read_crosstab(OUT / "org.csv")
            row(f"{len(rows)} rows; header rows 0-2:")
            for i in range(min(3, len(rows))):
                row(f"  r{i}", *[str(c) for c in rows[i][:14]])
            for wk in TARGETS:
                m, d, y = wk.split(".")
                hdr = f"{int(m)}/{int(d)}/20{y[-2:]}"
                reg = P.parse_override_summary(rows, hdr)
                top = sorted(reg.items(), key=lambda kv: -kv[1])[:5]
                row(f"  parse {hdr}", f"{len(reg)} owners",
                    *[f"{k}={v}" for k, v in top])
        except Exception as e:  # noqa: BLE001
            row("REGULAR FAILED", type(e).__name__, str(e)[:200])

        # B) full assemble for each target week (dry)
        for wk in TARGETS:
            row(f"=B: FULL ASSEMBLE {wk} (sandbox, dry)=")
            try:
                m, d, y = wk.split(".")
                week_header = f"{int(m)}/{int(d)}/20{y[-2:]}"
                regular, captain, special = R.pull_all(
                    wk, week_header, period_num=int(m), period_year=f"20{y[-2:]}",
                    page=page, verbose=True)
                s1, s2, un = F.assemble(wk, roster, captains, regular=regular,
                                        captain=captain, special=special, ws=ws)
                row(f"  regular={len(regular)} captain={len(captain)} special={len(special)}")
                row(f"  section1={len(s1)} cells  section2={len(s2)} cells")
                # show captain/special section-2 values (small, checkable)
                for key, rws in captains.items():
                    parts = []
                    if rws.get("captain") and rws["captain"] in s2:
                        parts.append(f"cap={s2[rws['captain']]}")
                    if rws.get("special") and rws["special"] in s2:
                        parts.append(f"spc={s2[rws['special']]}")
                    if parts:
                        row(f"    {key}", *parts)
                row(f"  UNMATCHED ({len(un)})", *un)
            except Exception as e:  # noqa: BLE001
                import traceback
                row(f"ASSEMBLE {wk} FAILED", type(e).__name__, str(e)[:150])
                print(traceback.format_exc(), flush=True)

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
    print("validate done.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
