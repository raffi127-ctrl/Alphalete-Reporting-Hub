"""Pull one office's Mon–Sat week from Ownerville.

Disposition by Rep (p=89) filters via URL ?startDate=&endDate= server-side —
the same mechanism the daily knocks pull uses with start == end; here they
span the week, so the whole Mon–Sat window comes back as ONE table (First /
Last Knock are the view's own week-level times, exactly what Raf reads off
the screen when he builds this by hand).

Talk-to rule (verified against Raf's own worked spreadsheet, 2026-08-22):
EVERY disposition column counts EXCEPT 'No answer' and 'Inaccessible' —
nobody was talked to in either. The columns are discovered from the live
header row, never listed by position, so a new disposition type Ownerville
adds starts counting on its own (and the run log names the columns summed,
so a surprise addition is visible, not silent).

Gaps come from the Time Tracker (p=510) JSON, which is single-date only —
the week is 6 calls, summed per badge ID.
"""
from __future__ import annotations

import datetime as dt

from automations.total_knocks import pull as knocks
from automations.total_knocks.pull import (
    COL_FIRST_KNOCK,
    COL_ID,
    COL_LAST_KNOCK,
    COL_REP,
    _norm,
    _to_int,
)
from automations.focus_office_att.run_all_owners import (
    _exit_impersonation,
    _find_owner_and_impersonate,
    _navigate_to_office_access,
)
from automations.focus_office_att.step5_fill_one_owner import page_rqst

# Computed / merged keys carried on each rep record next to the COL_* ones.
K_TALK_TO = "Total Talk To's"
K_GAP_MIN = "Gap Minutes"          # summed Time Tracker minutes, Mon–Sat

# Identity columns — scraped as-is, never counted.
_IDENTITY = {_norm(c) for c in (COL_ID, COL_REP, COL_FIRST_KNOCK,
                                COL_LAST_KNOCK)}
# Count columns that are NOT talk-tos: nobody answered / nobody reachable,
# plus the table's own aggregates.
_NOT_TALK_TO = {_norm(c) for c in (
    "No answer", "Inaccessible",
    "Total Leads Knocked", "Total Knocks", "Total Scheduled",
)}


def _navigate_week(page, rqst: str, monday: dt.date, saturday: dt.date,
                   *, attempts: int = 3, verbose: bool = True) -> None:
    """Same grid-not-built guard as the daily pull's _navigate (DataTables
    builds from an AJAX call that fires AFTER networkidle), with the week's
    range in the URL instead of a single day."""
    url = (f"https://v2.ownerville.com/index.cfm?p=89&rqst={rqst}"
           f"&startDate={monday.strftime('%m/%d/%Y')}"
           f"&endDate={saturday.strftime('%m/%d/%Y')}")
    for attempt in range(1, attempts + 1):
        page.goto(url, wait_until="networkidle", timeout=25000)
        try:
            page.wait_for_selector("#table-dispositions thead th",
                                   timeout=15000)
            break
        except Exception:  # noqa: BLE001 — stalled grid, not a fatal state
            if attempt == attempts:
                if verbose:
                    print(f"[wkd] grid never built after {attempts} "
                          "navigations — letting the scrape report it",
                          flush=True)
                break
            if verbose:
                print(f"[wkd] disposition grid not built yet "
                      f"(try {attempt}/{attempts}) — re-navigating",
                      flush=True)
    try:  # show all rows on one page where possible
        page.locator(
            "select[name='table-dispositions_length']").select_option("100")
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass


def _scrape_week_rows(page, idx: dict) -> tuple[list[dict], list[str]]:
    """One record per rep from the ranged table. Returns (rows,
    talk_to_columns) — the live header names that were summed into
    K_TALK_TO, so the caller can log the rule actually applied."""
    need = [COL_ID, COL_REP, COL_FIRST_KNOCK, COL_LAST_KNOCK]
    missing = [c for c in need if _norm(c) not in idx]
    if missing:
        raise RuntimeError(
            "Disposition table is missing expected column(s): "
            + ", ".join(missing)
            + ". Live headers were: " + ", ".join(sorted(idx)) + ".")

    # Every non-identity column is a count; counts not in _NOT_TALK_TO are
    # talk-tos (Raf's rule: everything except No answer / Inaccessible).
    talk_to_cols = [h for h, i in sorted(idx.items(), key=lambda kv: kv[1])
                    if h and h not in _IDENTITY and h not in _NOT_TALK_TO]

    try:
        page.wait_for_function(
            "() => document.querySelectorAll("
            "'#table-dispositions tbody tr').length >= 1",
            timeout=10000)
    except Exception:
        return [], talk_to_cols

    table = page.locator("table#table-dispositions")
    out: list[dict] = []
    seen_ids: set[str] = set()
    for _ in range(20):  # safety cap on pagination
        for tr in table.locator("tbody tr").all():
            cells = [c.inner_text().strip() for c in tr.locator("td").all()]
            if not cells or cells[0].lower().startswith("no data"):
                continue
            if max(idx.values()) >= len(cells):
                continue
            rec: dict = {
                COL_ID: cells[idx[_norm(COL_ID)]],
                COL_REP: cells[idx[_norm(COL_REP)]],
                COL_FIRST_KNOCK: cells[idx[_norm(COL_FIRST_KNOCK)]],
                COL_LAST_KNOCK: cells[idx[_norm(COL_LAST_KNOCK)]],
            }
            rec[K_TALK_TO] = sum(_to_int(cells[idx[h]]) for h in talk_to_cols)
            rid = str(rec[COL_ID]).strip()
            if rid and rid in seen_ids:
                continue
            if rid:
                seen_ids.add(rid)
            out.append(rec)
        nxt = page.locator("#table-dispositions_next").first
        if nxt.count() == 0 or "disabled" in (nxt.get_attribute("class") or ""):
            break
        nxt.click()
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
    return out, talk_to_cols


def _week_gaps(page, rqst: str, monday: dt.date, saturday: dt.date,
               verbose: bool = True) -> dict[str, int]:
    """{badge_id: total gap minutes, Mon–Sat}. Six p=510 calls — the endpoint
    has no range mode (dateToSearch= is one date)."""
    totals: dict[str, int] = {}
    day = monday
    while day <= saturday:
        tt = knocks._scrape_time_tracker(page, rqst,
                                         day.strftime("%m/%d/%Y"),
                                         verbose=False)
        for rid, rec in tt.items():
            totals[rid] = totals.get(rid, 0) + int(
                rec.get(knocks.COL_TOTAL_GAPS) or 0)
        day += dt.timedelta(days=1)
    if verbose:
        print(f"[wkd] Time Tracker: weekly gap minutes for "
              f"{len(totals)} rep(s)", flush=True)
    return totals


def _pin_campaign(page, rqst: str, campaign_id: str,
                  verbose: bool = True) -> None:
    """Sticky-campaign guard: TeleMapper pages are scoped to whatever campaign
    the session last had selected — by anyone. Best-effort, same as the
    knocks pull's."""
    try:
        page.goto(f"https://v2.ownerville.com/index.cfm?p=88&rqst={rqst}"
                  f"&invD2DClientId={campaign_id}",
                  wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(1000)
        if verbose:
            print(f"[wkd]   pinned TeleMapper campaign "
                  f"(invD2DClientId={campaign_id})", flush=True)
    except Exception as e:  # noqa: BLE001
        if verbose:
            print(f"[wkd]   campaign pin failed ({type(e).__name__}) — "
                  "continuing with the session's current campaign", flush=True)


def pull_office_week(page, cfg: dict, aliases_raw, monday: dt.date,
                     saturday: dt.date, *, verbose: bool = True) -> list[dict]:
    """One office's week on an already-open ownerville page. For an
    "impersonate" office the impersonation is entered and ALWAYS exited, so
    the next office starts from master. Returns rep records carrying
    COL_ID / COL_REP / COL_FIRST_KNOCK / COL_LAST_KNOCK / K_TALK_TO /
    K_GAP_MIN (K_GAP_MIN absent when the rep has no Time Tracker rows)."""
    page.set_default_timeout(60_000)
    page.set_default_navigation_timeout(60_000)

    impersonated = False
    if cfg.get("ov") == "impersonate":
        if _exit_impersonation(page) and verbose:
            print("[wkd]   cleared lingering impersonation", flush=True)
        if not _navigate_to_office_access(page):
            raise RuntimeError(
                "Couldn't reach the Office Access page (?p=901) to "
                f"impersonate {cfg['name']!r}.")
        rqst, reason = _find_owner_and_impersonate(page, cfg["name"],
                                                   aliases_raw)
        if not rqst:
            raise RuntimeError(
                f"Couldn't impersonate {cfg['name']!r}: {reason}")
        impersonated = True
        rqst = page_rqst(page) or rqst
    else:
        rqst = knocks._capture_rqst(page)
        if not rqst:
            raise RuntimeError("Couldn't capture ownerville rqst token from "
                               f"{page.url!r} after login.")

    try:
        _pin_campaign(page, rqst, str(cfg.get("campaign_id", "3")),
                      verbose=verbose)
        if verbose:
            print(f"[wkd] Disposition by Rep {monday} → {saturday} "
                  f"({cfg['name']})", flush=True)
        _navigate_week(page, rqst, monday, saturday, verbose=verbose)
        idx = knocks._header_index(page)
        rows, talk_to_cols = _scrape_week_rows(page, idx)
        if verbose:
            print(f"[wkd] {len(rows)} rep(s); talk-to = sum of: "
                  + ", ".join(talk_to_cols), flush=True)
        gaps = _week_gaps(page, rqst, monday, saturday, verbose=verbose)
    finally:
        if impersonated:
            if _exit_impersonation(page):
                if verbose:
                    print("[wkd]   exited impersonation", flush=True)
            elif verbose:
                print("[wkd]   ⚠ exit-impersonation call didn't succeed",
                      flush=True)

    matched = 0
    for rec in rows:
        rid = str(rec.get(COL_ID, "")).strip()
        if rid in gaps:
            rec[K_GAP_MIN] = gaps[rid]
            matched += 1
    if verbose:
        print(f"[wkd] merged weekly gaps onto {matched}/{len(rows)} rep(s)",
              flush=True)
    return rows
