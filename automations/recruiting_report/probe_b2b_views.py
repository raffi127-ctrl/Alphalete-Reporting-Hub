"""READ-ONLY: inventory the Tableau views + custom views behind the Carlos OPT
phase, for the two sources that are currently dead.

Why this exists — two open blockers, same shape:

  * row 50 'Penetration Rate' reads `ATTTRACKER-B2B / MARKETPERFORMANCEZIPLEVEL`.
    That view stopped existing after 2026-08-24 (Eve confirmed by hand in the
    Tableau UI on 2026-08-31); every run since fails "Viz toolbar never rendered
    for view 'penetration'". It was a BASE view — no GUID, no custom view — so
    the error's own advice ("re-save the custom view") does not apply. What is
    missing is the URL of whatever replaced it.
  * the 'Direct Deposit' row reads
    `DirectDepositICDVIEWVersion2_0 / PROGRAMSUMMARY / DOWNLINEVIEW`, a custom
    view. It filled fine on 2026-08-31 and broke on 2026-09-07: four runs, all
    "couldn't activate the worksheet for Download->Data", i.e. none of the nine
    click points in the header band left 'Download -> Data' enabled. Either the
    dashboard's layout moved or DOWNLINEVIEW is gone and the page fell back to
    a different default — this probe says which.

Scraping cannot answer either one: Tableau's content pages are virtualized, so
an anchor sweep for '/views/' returns ZERO hits on a workbook that plainly
exists (2026-08-31) — a silent false negative that reads exactly like "the
workbook is gone". The inventory comes instead from the vizportal API the UI
itself calls (getWorkbooks / getViews / getCustomViews), same origin so the
session cookie and XSRF token come along. `getViewsForWorkbook` and `getSheets`
are 404s — they do not exist.

Downloads nothing, opens no viz, writes no Sheet. Every line is prefixed
('WB:', 'VIEW:', 'CUSTOM:', 'HOT:', 'GONE:') so `lucy logtail <its log> VIEW: 40`
can page the list past the ~470-char result cell — the same trick
carlos_captainship_bonus's probe_sheets uses.

Runs on Lucy 2, never from Windows: Tableau's SSO goes through ownerville,
which allows ONE session per account, so a Windows run evicts the session
holder and pauses every report on that machine (2026-09-02).

    lucy rerun probe_b2b_views --machine "Lucy 2"
    lucy logtail <its log> VIEW: 40
    lucy logtail <its log> HOT: 10
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://us-east-1.online.tableau.com"
OUT_JSON = (Path(__file__).resolve().parents[2] / "output"
            / "_penetration_probe" / "carlos_opt_view_inventory.json")

# Workbooks are matched on repositoryUrl — the URL segment opt_phase_carlos
# already carries — not on display name, which is not what the URL shows.
# (repositoryUrl, the view we expect to still be there, words worth flagging)
TARGETS = [
    ("ATTTRACKER-B2B", "MARKETPERFORMANCEZIPLEVEL",
     ("penetration", "zip", "market")),
    ("DirectDepositICDVIEWVersion2_0", "PROGRAMSUMMARY",
     ("program", "summary", "downline")),
]

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
    except Exception:                                        # noqa: BLE001
        return status, {}


def _views(page, wb_id):
    st, data = _call(page, "getViews", {
        "filter": {"operator": "and", "clauses": [
            {"operator": "eq", "field": "workbookId", "value": str(wb_id)}]},
        "order": [{"field": "name", "ascending": True}],
        "page": {"startIndex": 0, "maxItems": 200}})
    return st, (data.get("result") or {}).get("views") or []


def _custom_views(page, wb_id):
    """Custom views on a workbook. Best-effort: this method name has moved
    between Tableau builds, so a non-200 is reported, not raised — the base
    view list above is what the caller actually needs."""
    st, data = _call(page, "getCustomViews", {
        "filter": {"operator": "and", "clauses": [
            {"operator": "eq", "field": "workbookId", "value": str(wb_id)}]},
        "order": [{"field": "name", "ascending": True}],
        "page": {"startIndex": 0, "maxItems": 200}})
    res = data.get("result") or {}
    return st, (res.get("customViews") or res.get("views") or [])


def _seg_url(rec, repo):
    """The view's url segment is spelled differently across Tableau builds —
    take the first one present rather than guessing from the display name."""
    seg = str(rec.get("viewUrlName") or rec.get("urlName")
              or rec.get("contentUrl") or rec.get("sheetUrl") or "")
    if "/" in seg:
        return "{}/#/site/sci/views/{}".format(BASE, seg.lstrip("/"))
    return "{}/#/site/sci/views/{}/{}".format(BASE, repo, seg)


def main() -> int:
    from automations.shared.tableau_patchright import tableau_session

    inventory = {}
    with tableau_session(verbose=True) as page:
        page.goto(BASE + "/#/site/sci/workbooks", wait_until="domcontentloaded")
        page.wait_for_timeout(12_000)
        st, data = _call(page, "getWorkbooks", {
            "filter": {"operator": "and", "clauses": []},
            "order": [{"field": "name", "ascending": True}],
            "page": {"startIndex": 0, "maxItems": 500}})
        wbs = (data.get("result") or {}).get("workbooks") or []
        print(f"site has {len(wbs)} workbook(s) (HTTP {st})", flush=True)
        if not wbs:
            print("!! getWorkbooks returned nothing — the session is probably "
                  "not logged in; check the tableau_session output above.")
            return 1

        for repo, expect, hot_words in TARGETS:
            wb = next((w for w in wbs
                       if repo.casefold()
                       in (w.get("repositoryUrl") or "").casefold()), None)
            print("\n" + "=" * 64, flush=True)
            if not wb:
                print(f"GONE: no workbook whose repositoryUrl contains "
                      f"{repo!r} — the workbook itself moved or was deleted.",
                      flush=True)
                for w in wbs:
                    print(f"WB: {w.get('name')} "
                          f"repo={w.get('repositoryUrl')}", flush=True)
                continue
            print(f"WB: {wb.get('name')} id={wb.get('id')} "
                  f"repo={wb.get('repositoryUrl')} "
                  f"sheets={wb.get('sheetCount')}", flush=True)

            st, views = _views(page, wb["id"])
            print(f"{len(views)} view(s) (HTTP {st})", flush=True)
            rows = []
            for v in views:
                url = _seg_url(v, wb.get("repositoryUrl") or "")
                rows.append({"name": v.get("name"), "url": url})
                print(f"VIEW: {v.get('name')} -> {url}", flush=True)

            st, cvs = _custom_views(page, wb["id"])
            print(f"{len(cvs)} custom view(s) (HTTP {st})", flush=True)
            for c in cvs:
                print(f"CUSTOM: {c.get('name')} id={c.get('id')} "
                      f"view={c.get('viewId')}", flush=True)

            if not any(expect.casefold() in (r["url"] or "").casefold()
                       for r in rows):
                print(f"GONE: {repo}/{expect} is NOT in this workbook's view "
                      f"list — that source really is dead.", flush=True)
            hot = [r for r in rows
                   if any(k in (r["name"] or "").casefold() for k in hot_words)]
            for r in hot:
                print(f"HOT: {r['name']} -> {r['url']}", flush=True)
            if not hot:
                print("HOT: none — no view name mentions "
                      + "/".join(hot_words), flush=True)
            inventory[repo] = {
                "workbook": wb.get("name"), "views": rows,
                "custom_views": [{"name": c.get("name"), "id": c.get("id")}
                                 for c in cvs]}

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    print("\nsaved -> {}".format(OUT_JSON), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
