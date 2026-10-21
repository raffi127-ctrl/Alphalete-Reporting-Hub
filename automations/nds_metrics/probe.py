"""NDS Metrics — Phase 0 probe (READ-ONLY, posts nothing).

Carlos 2026-10-21: the Fiber Metrics thread "should have basically been ...
an NDS metrics thread." Since 2026-10-19 the crew sells under CARLOS'S OWN
office 11580, campaign RES AT&T OOF ("NDS"); Raf's login is retired for
them (LOCAL-OFFICE-SALES-CALLOUTS-README). The metrics boards must retarget
before the thread opens. This probe proves the two new data legs:

  1. NDS-SN (RES-ATT-OOF) ORDERLOG — the same view Khalil's activation
     board pulls — filtered to Owner & Office = CARLOS HIDALGO: row count,
     the long-format measure-rows quirk, per-rep counts vs the crew list,
     status + product vocab.
  2. CARLOS'S OWN SaraPlus (sp_order_log.pull_csv — his login already on
     Lucy 2, Customer Type Both): do the crew's RES orders appear, and
     which column separates them from his B2B orders?

    lucy rerun nds_metrics_probe          (Lucy 2)
"""
from __future__ import annotations

import collections
import csv
import datetime as dt
import io
import sys
import tempfile
from pathlib import Path

LOOKBACK_DAYS = 60


def main(argv=None) -> int:
    from automations.office_metrics import nds_orderlog as NO
    from automations.total_knocks import guests

    today = dt.date.today()
    crew = guests.roster("Rafael Hidalgo", "Carlos Hidalgo")
    toks = [guests._tokens(n) for n in crew]

    def is_crew(n):
        t = guests._tokens(n)
        return any(guests._subseq(ct, t) or guests._subseq(t, ct)
                   for ct in toks)

    # ---- leg 1: NDS-SN ORDERLOG, owner Carlos --------------------------
    from automations.shared.tableau_patchright import tableau_session
    url = NO._orderlog_url(today - dt.timedelta(days=LOOKBACK_DAYS), today)
    cache = Path(tempfile.gettempdir()) / f"nds_metrics_ol_{today}.csv"
    if not (cache.exists() and cache.stat().st_size > 500):
        with tableau_session(verbose=False) as page:
            r = page.context.request.get(url, timeout=300_000)
            body = r.body() or b""
            print(f"[ndsm] OL csv status={r.status} bytes={len(body):,}")
            if r.status == 200 and len(body) > 500:
                cache.write_bytes(body)
    rows = NO._read_csv(cache)
    header = rows[0]
    for i in range(0, len(header), 6):
        print(f"NOLH{i // 6}: " + " | ".join(str(c) for c in header[i:i + 6]))
    hdr_n = [NO._norm_h(str(h)) for h in header]
    i_owner = next((i for i, h in enumerate(hdr_n) if h.startswith("owner")),
                   None)
    i_rep = next((i for i, h in enumerate(hdr_n) if h == "rep"), None)
    i_mn = next((i for i, h in enumerate(hdr_n) if "measure names" in h),
                None)
    data = rows[1:]
    carlos = [r for r in data if i_owner is not None and len(r) > i_owner
              and "CARLOS" in str(r[i_owner]).upper()
              and "HIDALGO" in str(r[i_owner]).upper()]
    print(f"[ndsm] OL rows={len(data)} carlos-owner={len(carlos)}")
    if i_mn is not None:
        ms = collections.Counter(str(r[i_mn]).strip() for r in carlos
                                 if len(r) > i_mn)
        print(f"[ndsm] OL measures: {dict(ms)}")
    per = collections.Counter(str(r[i_rep]).strip() for r in carlos
                              if i_rep is not None and len(r) > i_rep)
    for rep, n in per.most_common(20):
        print(f"  NDSREP {rep}: {n}" + ("" if is_crew(rep) else "  (NOT in crew list)"))
    for col in ("dtr status", "product type", "churn buckets"):
        i = next((j for j, h in enumerate(hdr_n) if col in h), None)
        if i is not None:
            c = collections.Counter(str(r[i]).strip() or "(blank)"
                                    for r in carlos if len(r) > i)
            print(f"[ndsm] OL {col}: "
                  + ", ".join(f"{k}={v}" for k, v in c.most_common(8)))

    # ---- leg 2: Carlos's own SaraPlus ----------------------------------
    try:
        from automations.sp_order_log.run import pull_csv
        data_b, _wl = pull_csv(today - dt.timedelta(days=31), today)
        soh = list(csv.reader(io.StringIO(
            data_b.decode("utf-8-sig", errors="replace"))))
        hdr = [str(h).strip() for h in soh[0]]
        ix = {h: i for i, h in enumerate(hdr)}
        i_un = ix.get("User Name")
        crew_rows = [r for r in soh[1:] if i_un is not None and len(r) > i_un
                     and is_crew(str(r[i_un]).strip())]
        print(f"[ndsm] SOH rows={len(soh) - 1} crew={len(crew_rows)}")
        for col in ("Campaign", "Location", "User Dealer",
                    "Dealer Code Internet", "Dealer Code Video",
                    "Wireless Dealer Code", "Order Type"):
            i = ix.get(col)
            if i is None:
                continue
            c = collections.Counter(str(r[i]).strip() or "(blank)"
                                    for r in crew_rows if len(r) > i)
            print(f"[ndsm] SOH crew {col}: "
                  + ", ".join(f"{k}={v}" for k, v in c.most_common(6)))
        per2 = collections.Counter(str(r[i_un]).strip() for r in crew_rows)
        print(f"[ndsm] SOH crew reps: {dict(per2)}")
    except Exception as e:  # noqa: BLE001 — leg 2 failing must not hide leg 1
        print(f"[ndsm] SaraPlus leg FAILED: {type(e).__name__}: {e}")
    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
