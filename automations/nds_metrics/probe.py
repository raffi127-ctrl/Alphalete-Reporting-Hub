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


def dd_join(log=print) -> int:
    """Join the WE 10.25 DD (Scoutly RAW tab, NDS Wireless campaign) to the
    SaraPlus SOH cache by customer — Carlos 2026-10-28: "check through sara
    plus and figure it out. doesnt make sense that its this behind." Shows,
    per PAID customer: present in SaraPlus at all? status? active date?"""
    import collections
    import csv as _csv
    import io
    from automations.nds_metrics.run import OUT_DIR, _parse_date
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key("1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY")
    raw = next(w for w in sh.worksheets() if w.title.strip().lower() == "raw")
    vals = raw.get_all_values()
    ix = {h: i for i, h in enumerate(vals[0])}
    dd = collections.defaultdict(float)
    dd_dates: dict = {}
    for r in vals[1:]:
        if r and r[0].strip() == "10.25" and "NDS" in r[ix["Campaign"]].upper():
            try:
                amt = float(str(r[ix["Total $ to ICD"]]).replace("$", "")
                            .replace(",", "") or 0)
            except ValueError:
                amt = 0.0
            key = (r[ix["Customer Name"]].strip().upper() or "(blank)",
                   r[ix["Rep Name"]].strip())
            dd[key] += amt
            dd_dates.setdefault(key, r[ix["Sale Date"]].strip())
    cache = sorted(OUT_DIR.glob("nds_soh_*.csv"))[-1]
    rows = list(_csv.reader(io.StringIO(
        cache.read_bytes().decode("utf-8-sig", errors="replace"))))
    hx = {h.strip(): i for i, h in enumerate(rows[0])}
    def cell(r, c):
        i = hx.get(c)
        return str(r[i]).strip() if i is not None and len(r) > i else ""
    def toks(n):
        return {t for t in n.upper().replace(",", " ").split() if len(t) > 1}
    # The alphaletegp export has NO Customer Name column, so the join key
    # is REP (token overlap) + DD Sale Date == SOH Order Date (±1 day).
    soh = []
    for r in rows[1:]:
        soh.append((toks(cell(r, "User Name")),
                    _parse_date(cell(r, "Order Date")), r))
    log(f"[ddjoin] {len(dd)} paid customer(s) on the 10.25 DD vs "
        f"{len(soh)} SOH row(s) in {cache.name} "
        f"(join: rep + sale date; export has no customer column)")
    found = missing = 0
    # dd keys now carry the sale date too
    for (cust, rep), amt in sorted(dd.items(), key=lambda x: -x[1]):
        rt = toks(rep)
        sd = _parse_date(dd_dates.get((cust, rep), ""))
        def _ok(st, od):
            if not (rt and st and (rt & st)):
                return False
            if sd is None or od is None:
                return bool(rt & st)
            return abs((od - sd).days) <= 1
        hit = next((r for st, od, r in soh if _ok(st, od)), None)
        if hit is None:
            missing += 1
            log(f"DDJOIN MISSING  {cust[:24]:24} {rep[:20]:20} ${amt:>7,.0f}")
        else:
            found += 1
            log(f"DDJOIN present  {cust[:24]:24} {rep[:20]:20} ${amt:>7,.0f}"
                f" | status={cell(hit, 'Wireless Status') or '?':10}"
                f" | act={cell(hit, 'Wireless Active Date') or '-':10}"
                f" | ord={cell(hit, 'Order Date') or '-'}"
                f" | lines={cell(hit, 'Wireless Line Count') or '?'}")
    log(f"[ddjoin] present {found}, MISSING {missing}")
    print("=== done ===", flush=True)
    return 0


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
        # Carlos 2026-10-27: "show me the recent sales on carhi1816" —
        # every crew order of the last 10 days on THIS dealer, one line each.
        def _d(v):
            for f in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
                try:
                    return dt.datetime.strptime(
                        str(v).strip().split()[0], f).date()
                except (ValueError, IndexError):
                    continue
            return None
        i_od, i_cn = ix.get("Order Date"), ix.get("Customer Name")
        i_ws, i_lc = ix.get("Wireless Status"), ix.get("Wireless Line Count")
        for r in sorted(crew_rows,
                        key=lambda r: _d(r[i_od]) or dt.date.min,
                        reverse=True):
            d = _d(r[i_od]) if i_od is not None and len(r) > i_od else None
            if d is None or (today - d).days > 10:
                continue
            def g(i):
                return str(r[i]).strip() if i is not None and len(r) > i                     else ""
            print(f"B2BATT {d} | {g(i_un)[:24]:24} | {g(i_cn)[:24]:24} | "
                  f"{g(i_ws) or '?':12} | {g(i_lc) or '?'} line(s)")
    except Exception as e:  # noqa: BLE001 — leg 2 failing must not hide leg 1
        print(f"[ndsm] SaraPlus leg FAILED: {type(e).__name__}: {e}")
    print("=== done ===", flush=True)
    return 0


def _entry(argv=None):
    import sys as _sys
    args = list(argv if argv is not None else _sys.argv[1:])
    if "--dd-join" in args:
        return dd_join()
    return main(argv)


if __name__ == "__main__":
    sys.exit(_entry())
