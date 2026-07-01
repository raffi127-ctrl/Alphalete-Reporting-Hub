# tableau_http is dead on the mini (CDP Chrome gone) — opt_nds HTTP sources may be silently failing

**Found 2026-07-01** while wiring the Insurance% pull.

## What's broken
`automations/alphalete_org_report/tableau_http.py` → `_grab_session()` attaches to a
**CDP debug Chrome on `http://localhost:9222`** (`fetch_office.CDP_URL`) to lift Tableau
SSO cookies. That debug Chrome **no longer runs on the mini** — the recruiting stack
migrated to patchright + the session holder is patchright-based, not a CDP debug Chrome.
So any `tableau_http.download_view_csv()` call fails with:

```
retrieving websocket url from http://localhost:9222  (connection refused)
```

## Who uses it (likely degraded)
`opt_nds.py` (Alphalete Org report) pulls several sources via `NDS_HTTP_VIEWS`
(tableau_http). These may be **silently failing or falling back**:
- `NDS-SNRES-ATT-OOFWorkbook / NDSWeeklyMetricsRep` → weekly metrics / 0-30 cancel rate
- `DropshipV_2 / ACTIVATIONRATES` → activation rates
- `NDS-SNRES-ATT-OOFWorkbook / LeadPenetrationOverview` → lead penetration
- `DropshipV_2 / SARAPLUSSALESSUMMARYBYDAY` → SARA by-day

## The fix (already proven for the Insurance% probe)
Fetch the `.csv` endpoint through the **patchright `tableau_session`'s request context**
instead of the dead CDP Chrome:
```python
with tableau_session() as page:
    resp = page.context.request.get(f"{BASE}/t/sci/views/{workbook}/{view}.csv", timeout=120_000)
    out.write_bytes(resp.body())
```
Shares the SSO cookies, no CDP, no `:9222`. Port `tableau_http._grab_session` /
`download_view_csv` to this (or route them through a patchright helper), then verify
opt_nds's HTTP sources actually return fresh data.

## To circle back
1. Confirm opt_nds's HTTP sources are actually stale/failing (check the Org report tabs).
2. Repoint `tableau_http` to the patchright request context.
3. Re-verify opt_nds end-to-end.
