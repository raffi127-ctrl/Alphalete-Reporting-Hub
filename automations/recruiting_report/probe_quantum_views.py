"""READ-ONLY probe: which Quantum Fiber views carry one ICD, and at what grain.

Why (Eve, 2026-09-14): the Angel Padilla tab (ex-Shealey Miller, AppStream
22400 + 23858) has no Office Metrics block. Its ICD sells Quantum Fiber, so
the ATT sources don't carry it. On 9/9 the `AT&T Quantum Fiber Sales Tracker`
workbook (RES-LumenSalesTrackervMZ) looked 30-day-rolling only; before
deciding whether those rows get filled, this lists EVERY view of the workbook
and prints its columns plus the ICD's rows, so a weekly grain can't hide.

Runs on a Lucy, not a laptop — the laptops power off at night:

    lucy rerun probe_quantum_views --inspect
    lucy logtail rerun probe_quantum_views 400

How it finds the views: the vizportal API the UI itself calls. Tableau's
content pages are virtualized, so scraping `a[href*='/views/']` returns zero
anchors — a silent false "nothing there".

Touches no Sheet, sends nothing, downloads no crosstab. Uses its own browser
profile, so it never waits on (or blocks) the shared one.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "output" / "_probe_quantum_views"
BASE = "https://us-east-1.online.tableau.com"
WB_NEEDLES = ("lumensalestracker", "quantum fiber sales tracker")

CALL = """async ({method, params}) => {
    const xsrf = (document.cookie.match(/XSRF-TOKEN=([^;]+)/) || [])[1] || '';
    const r = await fetch('/vizportal/api/web/v1/' + method, {
        method: 'POST',
        headers: {'Content-Type': 'application/json;charset=UTF-8',
                  'X-XSRF-TOKEN': decodeURIComponent(xsrf),
                  'Accept': 'application/json'},
        credentials: 'include',
        body: JSON.stringify({method: method, params: params})});
    const t = await r.text();
    return [r.status, t.slice(0, 300000)];
}"""


def _call(page, method, params):
    status, raw = page.evaluate(CALL, {"method": method, "params": params})
    try:
        return status, json.loads(raw)
    except Exception:  # noqa: BLE001
        return status, {}


def _views(page, wb) -> list:
    st, data = _call(page, "getViews", {
        "filter": {"operator": "and", "clauses": [
            {"operator": "eq", "field": "workbookId", "value": str(wb["id"])}]},
        "order": [{"field": "name", "ascending": True}],
        "page": {"startIndex": 0, "maxItems": 200}})
    out = []
    for v in (data.get("result") or {}).get("views") or []:
        seg = (v.get("viewUrlName") or v.get("urlName") or v.get("contentUrl")
               or v.get("sheetUrl") or "")
        if not seg:
            continue
        path = seg.lstrip("/") if "/" in seg else "{}/{}".format(
            wb.get("repositoryUrl"), seg)
        out.append((v.get("name") or "(unnamed)",
                    "{}/#/site/sci/views/{}".format(BASE, path)))
    return out


def _report(path: Path, needles: tuple) -> None:
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.reader(fh, delimiter="\t"))
    if not rows:
        print("    (empty grid)")
        return
    print("    columns: {}".format(rows[0]))
    print("    rows: {}".format(len(rows) - 1))
    for r in rows[1:4]:
        print("    sample: {}".format(r))
    hits = [r for r in rows[1:]
            if any(n in " ".join(r).casefold() for n in needles)]
    print("    MATCHING rows: {}".format(len(hits)))
    for r in hits[:60]:
        print("      {}".format(r))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--needle", action="append",
                    help="row text to match, case-insensitive (repeatable). "
                         "Default: padilla, azul")
    ap.add_argument("--inspect", action="store_true",
                    help="no-op: marks the rerun as a probe for the queue")
    args = ap.parse_args(argv)
    needles = tuple(n.casefold() for n in (args.needle or ["padilla", "azul"]))

    OUT.mkdir(parents=True, exist_ok=True)
    from automations.shared.tableau_patchright import (
        scrape_view_data_patchright, tableau_session)

    with tableau_session(verbose=True, profile_dir=OUT / ".profile") as page:
        page.goto(BASE + "/#/site/sci/workbooks", wait_until="domcontentloaded")
        page.wait_for_timeout(12_000)
        st, data = _call(page, "getWorkbooks", {
            "filter": {"operator": "and", "clauses": []},
            "order": [{"field": "name", "ascending": True}],
            "page": {"startIndex": 0, "maxItems": 500}})
        wbs = (data.get("result") or {}).get("workbooks") or []
        print("site has {} workbook(s) (HTTP {})".format(len(wbs), st), flush=True)
        wb = next((w for w in wbs if any(
            n in (w.get("name", "") + " " + (w.get("repositoryUrl") or "")).casefold()
            for n in WB_NEEDLES)), None)
        if not wb:
            print("Quantum workbook NOT found on this site")
            return 1
        print("WORKBOOK {!r} (id {}, repo {!r})".format(
            wb["name"], wb["id"], wb.get("repositoryUrl")))
        views = _views(page, wb)
        for n, u in views:
            print("  view {!r} -> {}".format(n, u))

        failed = 0
        for i, (name, url) in enumerate(views):
            print("\n=== {} ===".format(name), flush=True)
            out = OUT / "view_{:02d}.tsv".format(i)
            try:
                scrape_view_data_patchright(url, out, verbose=False, page=page)
                _report(out, needles)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print("    x scrape failed: {}".format(repr(exc)[:400]))
            sys.stdout.flush()
    print("\nDONE: {} view(s), {} failed".format(len(views), failed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
