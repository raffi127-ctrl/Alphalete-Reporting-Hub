"""READ-ONLY: find the new Charter (Spectrum) workbook on Tableau and show what
its order-log-ish views carry, so the Spectrum Order Log can be built on it.

Maud 2026-11-24: "would you be able to create an order log for Spectrum
please? There is a Charter workbook on Tableau now!" Nobody here knows the
workbook's url segment, view names or columns yet — this answers all three.

What it does, on the sci site via the vizportal API (same calls as
recruiting_report.probe_b2b_views — page scraping misses virtualized lists):
  * every workbook whose name/repositoryUrl says charter or spectrum -> 'WB:'
  * every view of each -> 'VIEW:'
  * for each view, the first lines of its .csv export -> 'COLS:' (header),
    'ROW:' (first 3 data rows), 'ROWS:' (row count). Views that won't export
    print 'CSVERR:'.

Downloads only into memory, writes no Sheet, posts nothing. Prefixed lines so
`lucy logtail <log> COLS: 20` can page past the result cell.

Runs on a Lucy (Tableau SSO via ownerville). `lucy rerun spectrum_order_log_probe`
"""
from __future__ import annotations

import csv
import io
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — py3.9 / non-tty
    pass

from automations.recruiting_report.probe_b2b_views import (
    BASE, _call, _seg, _views)

WORDS = ("charter", "spectrum")

CSV_JS = """async (url) => {
    const r = await fetch(url, {credentials: 'include'});
    const t = await r.text();
    const lines = t.split('\\n');
    return [r.status, lines.slice(0, 4).join('\\n'), lines.length];
}"""


def _csv_peek(page, repo: str, seg: str) -> None:
    url = "{}/t/sci/views/{}/{}.csv".format(BASE, repo, seg.split("/")[-1])
    try:
        st, head, n = page.evaluate(CSV_JS, url)
    except Exception as e:  # noqa: BLE001
        print(f"CSVERR: {seg}: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return
    if st != 200:
        print(f"CSVERR: {seg}: HTTP {st}", flush=True)
        return
    rows = list(csv.reader(io.StringIO(head.lstrip("﻿"))))
    if not rows:
        print(f"CSVERR: {seg}: empty export", flush=True)
        return
    print(f"COLS: {seg} | " + " | ".join(rows[0]), flush=True)
    for r in rows[1:4]:
        print(f"ROW: {seg} | " + " | ".join(r)[:400], flush=True)
    print(f"ROWS: {seg} ~{max(n - 2, 0)}", flush=True)


def main() -> int:
    from automations.shared.tableau_patchright import tableau_session

    with tableau_session(verbose=True) as page:
        page.goto(BASE + "/#/site/sci/workbooks", wait_until="domcontentloaded")
        page.wait_for_timeout(12_000)
        st, data = _call(page, "getWorkbooks", {
            "filter": {"operator": "and", "clauses": []},
            "order": [{"field": "name", "ascending": True}],
            "page": {"startIndex": 0, "maxItems": 1000}})
        wbs = (data.get("result") or {}).get("workbooks") or []
        print(f"site has {len(wbs)} workbook(s) (HTTP {st})", flush=True)
        if not wbs:
            print("!! getWorkbooks returned nothing — session not logged in?")
            return 1
        hits = [w for w in wbs if any(
            k in (str(w.get("name")) + " " + str(w.get("repositoryUrl"))).casefold()
            for k in WORDS)]
        if not hits:
            print("GONE: no workbook mentions charter/spectrum. All names:")
            for w in wbs:
                print(f"WB-ALL: {w.get('name')} repo={w.get('repositoryUrl')}",
                      flush=True)
            return 1
        for wb in hits:
            repo = wb.get("repositoryUrl") or ""
            print("\n" + "=" * 64, flush=True)
            print(f"WB: {wb.get('name')} repo={repo} id={wb.get('id')} "
                  f"project={wb.get('projectName')} "
                  f"updated={wb.get('updatedAt')}", flush=True)
            st, views = _views(page, wb["id"])
            print(f"{len(views)} view(s) (HTTP {st})", flush=True)
            for v in views:
                seg = _seg(v)
                print(f"VIEW: {v.get('name')} -> {repo}/{seg}", flush=True)
            for v in views:
                # The record's url segment comes back EMPTY on this site
                # (2026-11-24); the segment is the name with spaces and
                # punctuation dropped ('Order Log' -> 'OrderLog').
                seg = _seg(v) or "".join(
                    ch for ch in str(v.get("name") or "") if ch.isalnum())
                if seg:
                    _csv_peek(page, repo, seg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
