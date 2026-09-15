"""READ-ONLY probe: which Quantum Fiber views carry one ICD, and at what grain.

Why (Eve, 2026-09-14): the Angel Padilla tab (ex-Shealey Miller, AppStream
22400 + 23858) has no Office Metrics block. Its ICD sells Quantum Fiber, so
the ATT sources don't carry it. On 9/9 the `AT&T Quantum Fiber Sales Tracker`
workbook (RES-LumenSalesTrackervMZ) looked 30-day-rolling only; before
deciding whether those rows get filled, this lists EVERY view of the workbook,
every crosstab sheet each view offers, and prints each sheet's columns plus
the ICD's rows, so a weekly grain can't hide.

Runs on a Lucy, not a laptop — the laptops power off at night:

    lucy rerun probe_quantum_views --inspect
    lucy logtail rerun probe_quantum_views "S|" 4       # one line per sheet
    lucy logtail rerun probe_quantum_views "P|" 4       # the ICD's rows

HOW, and the three traps it steps around:
  - Views come from the vizportal API the UI itself calls. Content pages are
    virtualized, so scraping `a[href*='/views/']` returns zero anchors. A
    view record's URL is in `path` (there is no viewUrlName — reading that
    dropped every view on the first run, 2026-09-14).
  - Every view in this workbook is a DASHBOARD, and Download -> Data is
    disabled on a dashboard until a worksheet is clicked (second run: 14/14
    failed). Crosstab works on dashboards: pass 1 lists each view's sheets,
    pass 2 downloads them.
  - A tableau_session dies after ~8 downloads, so pass 2 runs in batches of
    CHUNK with a fresh login per batch, one attempt per sheet.

Output is SHORT lines on purpose: a queue result cell holds ~470 chars.
Touches no Sheet, sends nothing. Own browser profile; freshness alerts off
(ALPHALETE_SKIP_FRESHNESS) so a probe never reports a source stale.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
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
CHUNK = 6

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
    views = (data.get("result") or {}).get("views") or []
    print("getViews HTTP {} · {} record(s)".format(st, len(views)))
    repo = wb.get("repositoryUrl") or ""
    out = []
    for v in views:
        seg = str(v.get("path") or v.get("viewUrlName") or v.get("urlName")
                  or "").strip("/")
        if not seg:
            print("  no path for {!r}".format(v.get("name")))
            continue
        seg = seg.replace("/sheets/", "/")
        if "/" not in seg:
            seg = "{}/{}".format(repo, seg)
        out.append((v.get("name") or "(unnamed)",
                    "{}/#/site/sci/views/{}".format(BASE, seg)))
    return out


def _short(s, n=60) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n - 1] + "…"


def _read_grid(path: Path) -> list:
    raw = path.read_bytes()
    for enc in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except Exception:  # noqa: BLE001
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    delim = "\t" if text.count("\t") >= text.count(",") else ","
    return list(csv.reader(text.splitlines(), delimiter=delim))


def _report(view: str, sheet: str, path: Path, needles: tuple) -> None:
    rows = _read_grid(path)
    if not rows:
        print("S|{}|{}|EMPTY".format(_short(view, 40), _short(sheet, 40)))
        return
    hits = [r for r in rows[1:]
            if any(n in " ".join(r).casefold() for n in needles)]
    print("S|{}|{}|rows={}|icd={}|cols={}".format(
        _short(view, 40), _short(sheet, 40), len(rows) - 1, len(hits),
        _short(" ; ".join(c for c in rows[0] if c), 220)))
    for r in hits[:12]:
        print("P|{}|{}".format(_short(sheet, 30),
                               _short(" ; ".join(r), 300)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--needle", action="append",
                    help="row text to match, case-insensitive (repeatable). "
                         "Default: padilla, azul")
    ap.add_argument("--max-downloads", type=int, default=30,
                    help="cap on crosstab downloads in pass 2 (default 30)")
    ap.add_argument("--inspect", action="store_true",
                    help="no-op: marks the rerun as a probe for the queue")
    args = ap.parse_args(argv)
    needles = tuple(n.casefold() for n in (args.needle or ["padilla", "azul"]))

    os.environ["ALPHALETE_SKIP_FRESHNESS"] = "1"
    OUT.mkdir(parents=True, exist_ok=True)
    from automations.shared.tableau_patchright import (
        download_crosstab_patchright, tableau_session)
    from automations.recruiting_report.opt_phase import list_crosstab_sheets

    profile = OUT / ".profile"
    todo = []
    # Pass 1 — views and their crosstab sheets. Navigation only, no download.
    with tableau_session(verbose=True, profile_dir=profile) as page:
        page.goto(BASE + "/#/site/sci/workbooks", wait_until="domcontentloaded")
        page.wait_for_timeout(12_000)
        st, data = _call(page, "getWorkbooks", {
            "filter": {"operator": "and", "clauses": []},
            "order": [{"field": "name", "ascending": True}],
            "page": {"startIndex": 0, "maxItems": 500}})
        wbs = (data.get("result") or {}).get("workbooks") or []
        wb = next((w for w in wbs if any(
            n in (w.get("name", "") + " " + (w.get("repositoryUrl") or "")).casefold()
            for n in WB_NEEDLES)), None)
        if not wb:
            print("Quantum workbook NOT found among {} (HTTP {})".format(len(wbs), st))
            return 1
        print("WORKBOOK {!r} (id {})".format(wb["name"], wb["id"]))
        for name, url in _views(page, wb):
            try:
                sheets = list_crosstab_sheets(url, page=page)
            except Exception as exc:  # noqa: BLE001
                print("V|{}|LIST FAILED {}".format(_short(name, 40),
                                                   _short(repr(exc), 120)))
                continue
            print("V|{}|{}".format(_short(name, 40),
                                   _short(" ; ".join(sheets), 300)), flush=True)
            todo += [(name, url, s) for s in sheets]

    todo = todo[:args.max_downloads]
    print("pass 2: {} sheet(s) to download".format(len(todo)), flush=True)
    # Pass 2 — download each sheet, CHUNK per fresh login, one attempt each.
    failed = 0
    for i in range(0, len(todo), CHUNK):
        try:
            with tableau_session(verbose=False, profile_dir=profile) as page:
                for j, (name, url, sheet) in enumerate(todo[i:i + CHUNK], start=i):
                    out = OUT / "sheet_{:02d}.csv".format(j)
                    try:
                        download_crosstab_patchright(url, sheet, out,
                                                     verbose=False, page=page)
                        _report(name, sheet, out, needles)
                    except Exception as exc:  # noqa: BLE001
                        failed += 1
                        print("S|{}|{}|FAILED {}".format(
                            _short(name, 40), _short(sheet, 40),
                            _short(repr(exc), 120)))
                    sys.stdout.flush()
        except Exception as exc:  # noqa: BLE001
            print("batch {} died: {}".format(i // CHUNK, _short(repr(exc), 160)))
    print("DONE: {} sheet(s), {} failed".format(len(todo), failed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
