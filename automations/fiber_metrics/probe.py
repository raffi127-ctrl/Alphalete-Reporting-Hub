"""Fiber Metrics — Phase 0 probe (READ-ONLY, posts nothing).

Carlos 2026-10-08: he now sells under Raf's codes ("Fiber"), not B2B logins —
the B2B Metrics reports get remade for his crew from Raf's side. Before any
board is built, this probe proves the three data legs from one run:

  1. D2D ORDER LOG (ATTTRACKER2_1-D2D / 'A.Order Log', the same pull the
     commission sheet uses): header, Rafael-Hidalgo row count, the CREW's
     per-rep row counts (total_knocks.guests GUEST_REPS matcher — the same
     16-name list that drives FIB-1/3 and SAL-7/8), and the live status +
     product vocabularies.
  2. RAF'S DD (pay_structure.dd_pull ORG DD Detail): header + latest week
     label + row count — the source the per-unit Fiber payouts will be
     derived from (Carlos: "go through Raf's direct deposit to find out what
     the payout is on every unit").
  3. Whether the DD's Production Lookup joins to the order log (sample match
     rate) — the join the payout derivation stands on.

    lucy rerun fiber_metrics_probe        (Lucy 2)
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path


def main(argv=None) -> int:
    from automations.commission_sheet import sources as S
    from automations.total_knocks import guests

    # ---- leg 1: the D2D order log + crew match -------------------------
    ol_path = S.fetch_order_log()
    rows = S.read_crosstab(ol_path)
    hdr_i = next(i for i, r in enumerate(rows)
                 if any("rep" in str(c).strip().lower() for c in r))
    header = [str(c).strip() for c in rows[hdr_i]]
    data = rows[hdr_i + 1:]
    for i in range(0, len(header), 6):
        print(f"OLH{i // 6}: " + " | ".join(header[i:i + 6]))
    norm = [h.lower() for h in header]

    def col(*cands):
        for c in cands:
            for i, h in enumerate(norm):
                if c in h:
                    return i
        return None

    i_owner = col("owner")
    i_rep = col("rep")
    i_status = col("dtr status", "status")
    i_prod = col("product type (broken out)", "product")
    raf = [r for r in data if i_owner is not None and len(r) > i_owner
           and "RAFAEL" in str(r[i_owner]).upper()
           and "HIDALGO" in str(r[i_owner]).upper()]
    print(f"OL rows total={len(data)}  rafael-office={len(raf)}")

    crew = guests.roster("Rafael Hidalgo", "Carlos Hidalgo")
    print(f"CREW list ({len(crew)}): {', '.join(crew)}")

    # guests.match_rows wants OWNERVILLE dict rows; these are csv lists —
    # match the Rep cell with the same token tolerance (middle names etc.).
    crew_toks = [guests._tokens(n) for n in crew]

    def _is_crew(name: str) -> bool:
        t = guests._tokens(name)
        return any(guests._subseq(ct, t) or guests._subseq(t, ct)
                   for ct in crew_toks)

    mine, rest = [], []
    for r in raf:
        nm = str(r[i_rep]).strip() if i_rep is not None and len(r) > i_rep \
            else ""
        (mine if nm and _is_crew(nm) else rest).append(r)
    per = collections.Counter(str(r[i_rep]).strip() for r in mine
                              if i_rep is not None and len(r) > i_rep)
    print(f"CREW rows={len(mine)} (other rafael rows={len(rest)})")
    for rep, n in per.most_common():
        print(f"  CREW {rep}: {n}")
    if i_status is not None:
        st = collections.Counter(str(r[i_status]).strip() or "(blank)"
                                 for r in mine)
        print("CREW statuses: " + ", ".join(f"{k}={v}"
                                            for k, v in st.most_common()))
    if i_prod is not None:
        pr = collections.Counter(str(r[i_prod]).strip() or "(blank)"
                                 for r in mine)
        print("CREW products: " + ", ".join(f"{k}={v}"
                                            for k, v in pr.most_common()))

    # ---- leg 2: Raf's DD ------------------------------------------------
    dd_path = S.fetch_dd()
    dd_rows = S.read_crosstab(dd_path)
    dd_hdr_i = next(i for i, r in enumerate(dd_rows)
                    if any("total $" in str(c).lower() for c in r))
    dd_header = [str(c).strip() for c in dd_rows[dd_hdr_i]]
    dd_data = dd_rows[dd_hdr_i + 1:]
    for i in range(0, len(dd_header), 6):
        print(f"DDH{i // 6}: " + " | ".join(dd_header[i:i + 6]))
    print(f"DD rows={len(dd_data)}")

    # ---- leg 3: Production Lookup join ---------------------------------
    dnorm = [h.lower() for h in dd_header]
    i_pl = next((i for i, h in enumerate(dnorm) if "production lookup" in h),
                None)
    i_spm = col("spm")
    if i_pl is not None and i_spm is not None:
        ol_spm = {str(r[i_spm]).strip().upper().replace("SPE-", "")
                  for r in data if len(r) > i_spm and str(r[i_spm]).strip()}
        dd_pl = [str(r[i_pl]).strip().upper().replace("SPE-", "")
                 for r in dd_data if len(r) > i_pl and str(r[i_pl]).strip()]
        hit = sum(1 for v in dd_pl if v in ol_spm)
        print(f"JOIN: {hit}/{len(dd_pl)} DD rows match an order-log SPM")
        print("JOINSAMPLE dd_pl: " + " ; ".join(sorted(dd_pl)[:4]))
        print("JOINSAMPLE ol_spm: " + " ; ".join(sorted(ol_spm)[:4]))
    else:
        print(f"JOIN: columns missing (Production Lookup={i_pl}, SPM={i_spm})")
    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
