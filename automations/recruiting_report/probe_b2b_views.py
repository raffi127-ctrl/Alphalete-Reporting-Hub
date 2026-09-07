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
    view list above is what the caller actually needs.

    2026-09-07: it answers HTTP 404 on this site, same as getViewsForWorkbook
    and getSheets. So '0 custom view(s) (HTTP 404)' means THE PROBE CANNOT SEE
    THEM — it is NOT evidence that a custom view was deleted. Read the HTTP
    code before drawing any conclusion from the count."""
    st, data = _call(page, "getCustomViews", {
        "filter": {"operator": "and", "clauses": [
            {"operator": "eq", "field": "workbookId", "value": str(wb_id)}]},
        "order": [{"field": "name", "ascending": True}],
        "page": {"startIndex": 0, "maxItems": 200}})
    res = data.get("result") or {}
    return st, (res.get("customViews") or res.get("views") or [])


def _seg(rec):
    """The view's url segment, spelled differently across Tableau builds —
    take the first one present rather than guessing. Can legitimately come
    back EMPTY: on DirectDepositICDVIEWVersion2_0 (2026-09-07) not one of
    these keys was on the record, which is why the probe also prints the raw
    key list per workbook."""
    return str(rec.get("viewUrlName") or rec.get("urlName")
               or rec.get("contentUrl") or rec.get("sheetUrl") or "")


def _seg_url(rec, repo):
    seg = _seg(rec)
    if not seg:
        return ""
    if "/" in seg:
        return "{}/#/site/sci/views/{}".format(BASE, seg.lstrip("/"))
    return "{}/#/site/sci/views/{}/{}".format(BASE, repo, seg)


def _squash(s):
    """A view's url segment is its display name with spaces and punctuation
    dropped ('PROGRAM SUMMARY' -> 'PROGRAMSUMMARY'), so this is what makes the
    'is the view we point at still here?' test work on NAMES. Doing that test
    on the URL instead reported PROGRAMSUMMARY as deleted on 2026-09-07 purely
    because its url segment came back empty — a false alarm."""
    return "".join(ch for ch in str(s or "").casefold() if ch.isalnum())


# The DD base view, no GUID — the one the API confirms is still published.
# Opened last so the custom-view list is read from the sheet DOWNLINEVIEW was
# saved on (custom views are per-USER and per-SHEET).
DD_BASE_VIEW = (BASE + "/#/site/sci/views/"
                "DirectDepositICDVIEWVersion2_0/PROGRAMSUMMARY")


def _list_custom_views(page, view_url: str) -> None:
    """Open a view and print the entries in its 'Manage Custom Views' dialog.

    This is the ONLY way to see them: the vizportal `getCustomViews` endpoint
    answers HTTP 404 on this site, so the API inventory above is blind to
    custom views. Selectors verified in automations/uploaded/order_log.py.

    The viz toolbar lives in a lazily-loaded iframe inside closed shadow DOM,
    so `page.evaluate` / `querySelectorAll` cannot see it — only Playwright
    locators pierce it. Match entries by normalized innerText, never by the
    `title` attribute (titles carry stray whitespace).

    Custom views are per-USER: this reads them for whichever account the
    ownerville SSO logged in as (rhidalgo = Rafael Hidalgo), which is exactly
    the account whose list matters, because that is the account the reports
    run under.
    """
    print("\n" + "=" * 64, flush=True)
    print(f"custom views on {view_url}", flush=True)
    page.goto(view_url, wait_until="domcontentloaded")
    viz = page.frame_locator('iframe[title="Data Visualization"]')
    btn = viz.locator(
        '[data-tb-test-id="viz-viewer-toolbar-button-manage-customviews"]')
    try:
        btn.first.wait_for(state="visible", timeout=60_000)
    except Exception as e:                                   # noqa: BLE001
        print(f"CVERR: the Custom Views toolbar button never appeared "
              f"({type(e).__name__}) — the viz did not finish loading.",
              flush=True)
        return
    try:
        label = btn.first.inner_text(timeout=5_000).strip()
        # The button doubles as the "View:" label — it names whatever view is
        # currently applied, so it says whether the URL landed on a custom
        # view or fell back to Original.
        print(f"CVLABEL: toolbar reads {label!r}", flush=True)
    except Exception:                                        # noqa: BLE001
        pass
    try:
        btn.first.click(timeout=10_000)
        page.wait_for_timeout(2500)
        names = viz.locator('[data-tb-test-id="view-name"]')
        n = names.count()
        print(f"{n} custom view entr(ies) in the dialog", flush=True)
        for i in range(n):
            try:
                print(f"CV: {names.nth(i).inner_text(timeout=3_000).strip()}",
                      flush=True)
            except Exception:                                # noqa: BLE001
                print("CV: (unreadable entry)", flush=True)
        page.keyboard.press("Escape")
    except Exception as e:                                   # noqa: BLE001
        print(f"CVERR: couldn't open the Custom Views dialog: "
              f"{type(e).__name__}: {str(e)[:140]}", flush=True)


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
            if views:
                # The record's key names move between builds and decide whether
                # a URL can be built at all — print them so an empty '-> ' is
                # readable instead of mysterious.
                print(f"KEYS: {sorted(views[0].keys())}", flush=True)
            rows = []
            for v in views:
                url = _seg_url(v, wb.get("repositoryUrl") or "")
                rows.append({"name": v.get("name"), "seg": _seg(v), "url": url})
                print(f"VIEW: {v.get('name')} -> {url or '(no url segment on '
                      f'the record)'}", flush=True)

            st, cvs = _custom_views(page, wb["id"])
            print(f"{len(cvs)} custom view(s) (HTTP {st})", flush=True)
            for c in cvs:
                print(f"CUSTOM: {c.get('name')} id={c.get('id')} "
                      f"view={c.get('viewId')}", flush=True)

            # Match on the squashed NAME (and the segment when there is one),
            # never on the URL — see _squash.
            if not any(_squash(expect) in (_squash(r["name"]),
                                           _squash(r["seg"]))
                       for r in rows):
                print(f"GONE: {repo}/{expect} is NOT in this workbook's view "
                      f"list — that source really is dead.", flush=True)
            else:
                print(f"ALIVE: {repo}/{expect} is still listed.", flush=True)
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

        _list_custom_views(page, DD_BASE_VIEW)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    print("\nsaved -> {}".format(OUT_JSON), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
