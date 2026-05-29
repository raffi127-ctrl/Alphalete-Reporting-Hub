"""Scrape Time Tracker + Disposition for every owner tab in the Sheet.

Uses a SINGLE persistent Playwright session for the whole batch — no
subprocess per owner. Master rqst is captured once at start and reused
to bounce back to Office Access between owners (the master "Office
Access" nav link is hidden from impersonated owner portals, so direct
URL navigation is the only reliable path).

Per owner: navigate to Office Access → search owner by name → grab
officeId → call confirmImpersonate via AJAX → navigate to Time Tracker
+ Disposition per day → scrape → fill the Sheet tab.

An error on one owner doesn't stop the rest. Summary printed at end.

If a run is interrupted (Chrome dropped, Stop button, crash), the next
normal run resumes — owners already scraped today are skipped. See
CHECKPOINT_FILE below.

No prereq: launches its own patchright Chrome window via
tableau_patchright.ownerville_session() and logs into ownerville
unattended (persistent profile keeps Cloudflare/login warm between runs).

Run:
    .venv/bin/python -m automations.focus_office_att.run_all_owners
    .venv/bin/python -m automations.focus_office_att.run_all_owners --only "Cody Cannon,Sam Park"
    .venv/bin/python -m automations.focus_office_att.run_all_owners --skip "Cody Cannon"
    .venv/bin/python -m automations.focus_office_att.run_all_owners --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import traceback
from pathlib import Path

from automations.recruiting_report import fill as _fill
from automations.focus_office_att.aliases import (
    load_aliases,
    get_search_candidates,
    save_alias,
)
from automations.focus_office_att.apply_data_border import apply_bold_border
from automations.focus_office_att.auto_collapse import update_collapse_states
from automations.focus_office_att.autosize_rep_col import autosize_all_data_cols
from automations.focus_office_att.columns import resolve_layout
from automations.focus_office_att.step5_fill_one_owner import (
    TT_FIELD_TO_CANONICAL,
    DISP_FIELD_TO_CANONICAL,
    _merge_rep_records,
    design_cosmetic_ops,
    fill_owner_tab,
    page_rqst,
    scrape_day,
    scrape_disposition_day,
)

DEST_SPREADSHEET_ID = "1xgVE_e8bZimACgPdqcdNCr1qo4sedWect_zzEcUgEJY"
TIME_TRACKER_PAGE = "p=510"

# Owner tabs that DON'T live as sub-offices in the impersonation table —
# their data sits at the master/admin level (Alphalete Marketing,
# officeId 11280). For these, skip the Office Access search +
# confirmImpersonate steps entirely; just use the current master rqst
# to scrape ?p=510 + ?p=89 directly. Per Megan: Raf is the master
# admin, so 'his dashboard' IS the master view.
NO_IMPERSONATE_OWNERS = {"Rafael Hidalgo"}

# ----------------------------------------------------------------------
# Resume checkpoint
# ----------------------------------------------------------------------
# A full Phase-2 scrape is ~30 owners. If a run is interrupted partway
# (Chrome dropped, the Hub Stop button, a crash), a re-run shouldn't redo
# the owners that already finished. Each owner that scrapes OK is appended
# here; on the next run, owners listed under the SAME run_key are skipped.
# daily.py deletes this file after the Monday wipe and after a fully
# successful run — so a file that's still here always means "the last run
# was interrupted; resume it."
CHECKPOINT_FILE = (
    Path(__file__).resolve().parents[2] / "output" / "focus_office_run_checkpoint.json"
)

# A genuine crash-and-retry happens within minutes. If the checkpoint is
# older than this, it's a stale leftover (or a deliberate hours-later
# re-run) — ignore it and scrape fresh so today's data isn't skipped.
_CHECKPOINT_MAX_AGE_S = 2 * 3600


def _read_checkpoint() -> dict | None:
    try:
        if CHECKPOINT_FILE.exists():
            return json.loads(CHECKPOINT_FILE.read_text())
    except Exception:
        pass
    return None


def _checkpoint_fresh(cp: dict) -> bool:
    try:
        ts = dt.datetime.fromisoformat(cp.get("updated_at", ""))
        return (dt.datetime.now() - ts).total_seconds() <= _CHECKPOINT_MAX_AGE_S
    except Exception:
        return False


def _write_checkpoint(run_key: str, completed: list[str]) -> None:
    """Best-effort — a checkpoint write must never break the scrape."""
    try:
        CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
        CHECKPOINT_FILE.write_text(json.dumps({
            "run_key": run_key,
            "completed": completed,
            "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
        }, indent=2))
    except Exception:
        pass


def _checkpoint_mark_done(run_key: str, owner: str) -> None:
    """Record `owner` as scraped OK in the checkpoint for this run."""
    cp = _read_checkpoint() or {}
    done = list(cp.get("completed", [])) if cp.get("run_key") == run_key else []
    if owner not in done:
        done.append(owner)
    _write_checkpoint(run_key, done)


def _prompt_for_unknown_owner(sheet_tab_name: str) -> str | None:
    """Ask the user what ownerville name to use for an unknown Sheet tab.
    Returns the typed name, or None to skip this owner.

    When stdin is not a TTY (background/cron run), auto-skips with a
    visible warning instead of blocking on input — Hub-button-triggered
    runs have no interactive terminal and would freeze otherwise.
    """
    if not sys.stdin.isatty():
        print(f"\n  ⚠ '{sheet_tab_name}' couldn't be found in ownerville under that name.")
        print(f"     [non-interactive mode — auto-skipping. Add an alias and re-run to backfill.]")
        return None
    print(f"\n  ⚠ '{sheet_tab_name}' couldn't be found in ownerville under that name.")
    print(f"     Open ownerville's Office Access table in your browser and look them up.")
    print(f"     What is their EXACT name in ownerville? (blank or 's' to skip)")
    try:
        ans = input(f"     > ").strip()
    except EOFError:
        return None
    if not ans or ans.lower() == "s":
        return None
    return ans


def _parse_csv(s: str) -> set[str]:
    return {x.strip() for x in (s or "").split(",") if x.strip()}


def _find_ownerville_page(browser):
    for ctx in browser.contexts:
        for pg in ctx.pages:
            if "ownerville" in pg.url:
                return pg
    return None


def _capture_master_rqst(page) -> str | None:
    """Navigate to root and read the rqst from the resulting master Welcome URL."""
    print("  → Resetting ownerville tab to master Welcome…")
    page.goto("https://v2.ownerville.com/", wait_until="networkidle", timeout=25000)
    print(f"  ✓ Landed on {page.url}")
    m = re.search(r"rqst=([A-Fa-f0-9_]+)", page.url)
    return m.group(1) if m else None


def _navigate_to_office_access(page) -> bool:
    """Get the ownerville tab onto the Office Access (?p=901) page.

    Each call re-establishes the master session by navigating to root, then
    follows up to ?p=901 with whatever fresh rqst the server hands back.
    The previously-captured master rqst becomes invalid once an impersonation
    happens, so we can't reuse it between owners — fresh per-iteration is the
    only reliable path.

    Returns True if we land on p=901.
    """
    # 1. Reset to master Welcome to get a fresh rqst.
    try:
        page.goto("https://v2.ownerville.com/", wait_until="networkidle", timeout=25000)
    except Exception as e:
        print(f"  ⚠ Root nav errored: {type(e).__name__}: {str(e)[:120]}")
        return False
    m = re.search(r"rqst=([A-Fa-f0-9_]+)", page.url)
    if not m:
        print(f"  ❌ No rqst after root navigation: {page.url}")
        return False
    fresh_rqst = m.group(1)

    # 2. Navigate to Office Access using the fresh rqst.
    url = f"https://v2.ownerville.com/index.cfm?p=901&rqst={fresh_rqst}"
    try:
        page.goto(url, wait_until="networkidle", timeout=20000)
    except Exception as e:
        print(f"  ⚠ Direct ?p=901 nav errored: {type(e).__name__}: {str(e)[:120]}")
        return False

    if "p=901" in page.url:
        return True

    # Last resort: server bounced; click the nav link from wherever we are.
    print(f"  → Bounced to {page.url}; trying side-nav click…")
    try:
        page.locator("a[href*='p=901']").first.click(timeout=8000)
        page.wait_for_url("**p=901*", timeout=10000)
    except Exception as e:
        print(f"  ❌ Side-nav click also failed: {type(e).__name__}: {str(e)[:120]}")
        return False
    return "p=901" in page.url


def _exit_impersonation(page) -> bool:
    """Call exitImpersonate AJAX to release the current impersonation.

    Bypasses the SweetAlert confirmation modal — same trick as
    confirmImpersonate. Once this returns ok, the server's session goes back
    to master/admin mode and the previously-captured master rqst is valid
    again for ?p=901 access.

    Returns True on success. Safe to call even if not currently impersonating
    (the server returns ok=false and we just move on).
    """
    rqst = page_rqst(page)
    if not rqst:
        print("  ⚠ exit-impersonate: no rqst token on page")
        return False
    try:
        # Vanilla fetch (no jQuery `$`) so it works under patchright's
        # isolated evaluate world. fetch is a browser builtin; same-origin
        # cookies ride along automatically. Headers match what $.ajax sent
        # (X-Requested-With + form-urlencoded) so the ColdFusion endpoint
        # treats it identically.
        result = page.evaluate(
            """async (rqst) => {
                try {
                    const resp = await fetch("components/promotions/promotions.cfc", {
                        method: "POST",
                        credentials: "same-origin",
                        headers: {
                            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                            "X-Requested-With": "XMLHttpRequest"
                        },
                        body: new URLSearchParams({rqst: rqst, method: "exitImpersonate"}).toString()
                    });
                    const text = await resp.text();
                    let parsed; try { parsed = JSON.parse(text); } catch (e) { parsed = null; }
                    return {ok: !!(parsed && parsed.data && parsed.data.success)};
                } catch (e) {
                    return {ok: false, error: String(e)};
                }
            }""",
            rqst,
        )
        return bool(result.get("ok"))
    except Exception as e:
        print(f"  ⚠ exit-impersonate call errored: {type(e).__name__}: {str(e)[:120]}")
        return False


def _find_owner_and_impersonate(page, sheet_tab_name: str, aliases_raw: dict) -> tuple[str | None, str]:
    """On the Office Access page, search for the owner (trying canonical name
    plus any known aliases), grab their officeId, and call confirmImpersonate.

    Returns (rqstValue, "ok") on success.
    Returns (None, reason) on failure where reason is one of:
      - "name not found in ownerville"  — alias missing / name drifted
      - "no ov access (impersonate denied)"  — the real access denial
      - "ov page error: missing officeId"  — site DOM unexpected
    The reason is written verbatim to scrape_results.json so the Sheet
    banner can show an actionable hint instead of a generic 'failed'.
    """
    # Wait for the DataTables AJAX load.
    page.locator("table#promotingOffices").wait_for(state="visible", timeout=10000)
    page.wait_for_function(
        """() => {
            const rows = document.querySelectorAll('table#promotingOffices tbody tr');
            if (rows.length < 2) return false;
            const firstCellText = rows[0].textContent || '';
            return !firstCellText.toLowerCase().includes('loading');
        }""",
        timeout=20000,
    )

    table = page.locator("table#promotingOffices")
    sb = page.locator("#promotingOffices_filter input").first

    def _try_search(cand: str) -> tuple:
        """Run the filter for `cand`; return (matching_row_or_None, visible_names_list)."""
        try:
            sb.fill(cand)
            page.wait_for_timeout(800)
        except Exception as e:
            print(f"  ⚠ Search box unusable: {e}")
            return None, []
        rows = table.locator("tbody tr").all()
        cand_lower = " ".join(cand.lower().split())
        visible = []
        for tr in rows:
            cells = tr.locator("td").all()
            if len(cells) < 3:
                continue
            name_text = " ".join(cells[2].inner_text().lower().split())
            visible.append(name_text)
            if name_text == cand_lower:
                return tr, visible
        return None, visible

    candidates = get_search_candidates(sheet_tab_name, aliases_raw)
    owner_row = None
    last_visible_names: list[str] = []

    for cand in candidates:
        owner_row, last_visible_names = _try_search(cand)
        if owner_row is not None:
            if cand != sheet_tab_name:
                print(f"  ✓ Matched via known alias '{cand}' (Sheet tab: '{sheet_tab_name}')")
            break

    # Fall back: interactively prompt for an unknown name, save it as an alias.
    if owner_row is None:
        print(f"  ❌ Couldn't find '{sheet_tab_name}' in ownerville. Tried: {candidates}")
        new_alias = _prompt_for_unknown_owner(sheet_tab_name)
        if not new_alias:
            return None, "name not found in ownerville"
        owner_row, last_visible_names = _try_search(new_alias)
        if owner_row is None:
            print(f"  ❌ '{new_alias}' also not found — skipping {sheet_tab_name}.")
            return None, "name not found in ownerville"
        save_alias(sheet_tab_name, new_alias)
        # Refresh local map so subsequent searches in this run pick it up.
        aliases_raw.setdefault(sheet_tab_name, []).append(new_alias)

    # Grab officeId from the action button. The action cell can be in
    # one of THREE states for a row we can see:
    #   (a) clickable button with data-officeid  → normal, impersonate
    #   (b) text 'Request Sent' (no button)      → access request in flight,
    #       not yet approved
    #   (c) some other non-clickable text        → office disabled / odd state
    # Read the cell text FIRST (fast) so we can return a specific status
    # for case (b) without paying a 30s Playwright timeout.
    action_cell = owner_row.locator("td").last
    try:
        cell_text = (action_cell.inner_text(timeout=4000) or "").strip().lower()
    except Exception:
        cell_text = ""
    if "request sent" in cell_text or "request pending" in cell_text:
        print(f"  ⏳ Action cell shows 'Request Sent' — access pending in OV.")
        return None, "ov access request pending (request sent in office access table)"

    action_btn = action_cell.locator("button, a").first
    try:
        office_id = action_btn.get_attribute("data-officeid", timeout=4000) or ""
    except Exception:
        # No clickable element in the cell AND no 'Request Sent' text matched.
        # Most likely the office is in some other non-normal state.
        print(f"  ❌ Action button not clickable — office may be disabled / suspended. "
              f"Cell text: {cell_text!r}")
        return None, "ov row has no impersonate button (office may be disabled)"
    if not office_id:
        print(f"  ❌ Action button missing data-officeid attribute.")
        return None, "ov page error: missing officeId"

    rqst = page_rqst(page)
    if not rqst:
        print(f"  ❌ confirmImpersonate: no rqst token on page")
        return None, "ov page error: missing rqst token"

    # Call the impersonate AJAX endpoint directly (bypasses the SweetAlert).
    # Vanilla fetch (no jQuery `$`) so it survives patchright's isolated
    # evaluate world — the old `$.ajax` path saw `$` as undefined and failed
    # for every owner. Headers mirror $.ajax (X-Requested-With + form body).
    result = page.evaluate(
        """({officeId, rqst}) => (async () => {
            try {
                const resp = await fetch("components/promotions/promotions.cfc", {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "X-Requested-With": "XMLHttpRequest"
                    },
                    body: new URLSearchParams({rqst: rqst, officeid: officeId, method: "confirmImpersonate"}).toString()
                });
                const text = await resp.text();
                let parsed; try { parsed = JSON.parse(text); } catch (e) { parsed = null; }
                if (parsed && parsed.data && parsed.data.success) {
                    return {ok: true, redirect: 'index.cfm?p=2&rqst=' + rqst};
                }
                return {ok: false, response: JSON.stringify(parsed).slice(0, 200)};
            } catch (e) {
                return {ok: false, error: String(e)};
            }
        })()""",
        {"officeId": office_id, "rqst": rqst},
    )
    if not result.get("ok"):
        print(f"  ❌ confirmImpersonate failed: {result}")
        return None, "no ov access (impersonate denied)"

    # Navigate to the impersonated portal and read the new rqst token (the
    # server hands back a fresh one for the impersonated session).
    page.goto(f"https://v2.ownerville.com/{result['redirect']}", wait_until="networkidle", timeout=20000)
    new_rqst = page_rqst(page)
    return new_rqst, "ok"


def _scrape_one_owner(page, ws, days: list[dt.date], rqst: str) -> dict:
    """Scrape Time Tracker + Disposition for one owner across the given days,
    fill the Sheet tab, run post-fill ops. Returns stats dict."""
    metrics = (
        list(TT_FIELD_TO_CANONICAL.values())
        + list(DISP_FIELD_TO_CANONICAL.values())
        + ["Total Apps", "New INT", "Upgrades", "DTV", "New Lines"]
    )
    layout = resolve_layout(ws, metrics=metrics, interactive=False)

    # Time Tracker per-day scrape. Some owner portals load slowly, so we
    # retry the initial Time Tracker nav once before giving up.
    tt_url = f"https://v2.ownerville.com/index.cfm?p=510&rqst={rqst}"
    for attempt in (1, 2):
        try:
            page.goto(tt_url, wait_until="networkidle", timeout=45000)
            break
        except Exception as e:
            if attempt == 2:
                raise
            print(f"  ⚠ Time Tracker nav attempt {attempt} timed out; retrying…")
    tt_by_date: dict = {}
    for d in days:
        tt_by_date[d] = scrape_day(page, d)

    # Disposition per-day scrape (uses URL date param, so navigation per day).
    disp_by_date: dict = {}
    for d in days:
        disp_by_date[d] = scrape_disposition_day(page, d, rqst)

    # Merge by (date, rep) → one record per rep per day.
    scraped_by_date: dict = {}
    for d in days:
        by_name: dict = {}
        for r in tt_by_date.get(d, []):
            key = r["name"].lower().strip()
            by_name[key] = {**by_name.get(key, {}), **r}
        for r in disp_by_date.get(d, []):
            key = r["name"].lower().strip()
            by_name[key] = _merge_rep_records(by_name.get(key, {"name": r["name"]}), r)
        scraped_by_date[d] = list(by_name.values())

    stats = fill_owner_tab(ws, scraped_by_date, layout)

    # Cosmetic ops are EXPENSIVE (each = 1-3 Sheets API calls). Skip the
    # whole design pass if fill_owner_tab made no changes — re-applying
    # the same design to an unchanged tab is pure waste.
    if stats["written_cells"] == 0 and not stats["new_reps"]:
        print(f"  → no changes — skipping the design pass")
        return {
            "tt_counts": {d.isoformat(): len(tt_by_date[d]) for d in days},
            "disp_counts": {d.isoformat(): len(disp_by_date[d]) for d in days},
            "written": stats["written_cells"],
            "skipped": stats["skipped_cells"],
            "new_reps": stats["new_reps"],
        }

    # Apply the full owner-tab design. design_cosmetic_ops is the single
    # source of truth (shared with Phase 3) so a run reproduces the WHOLE
    # design. Each op is wrapped — a transient Sheets hiccup on one
    # cosmetic step shouldn't invalidate the owner's data write.
    for label, fn in design_cosmetic_ops(ws, layout):
        try:
            fn()
        except Exception as e:
            print(f"  ⚠ {label} failed (cosmetic, ignoring): {type(e).__name__}: {e}")

    return {
        "tt_counts": {d.isoformat(): len(tt_by_date[d]) for d in days},
        "disp_counts": {d.isoformat(): len(disp_by_date[d]) for d in days},
        "written": stats["written_cells"],
        "skipped": stats["skipped_cells"],
        "new_reps": stats["new_reps"],
    }


def main() -> int:
    # Pace Sheets calls under Google's quota — the per-owner design pass
    # is read-heavy; without this a full run 429-storms.
    from automations.focus_office_att._ratelimit import install as _install_pacing
    _install_pacing()
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="",
                    help="Comma-separated owner tab names to scrape (rest skipped).")
    ap.add_argument("--skip", default="",
                    help="Comma-separated owner tab names to skip.")
    ap.add_argument("--dry-run", action="store_true",
                    help="List the planned owner-order without scraping.")
    ap.add_argument("--week-start", default=None,
                    help="Monday of week to scrape (YYYY-MM-DD); defaults to current week.")
    ap.add_argument("--daily-window", action="store_true",
                    help="Re-scrape yesterday + today only (fast incremental "
                         "path for mid-week daily runs). Yesterday is re-pulled "
                         "because the prior run scraped it as a still-in-progress "
                         "partial day — this run finalizes it now that it's done.")
    args = ap.parse_args()

    only = _parse_csv(args.only)
    skip = _parse_csv(args.skip)

    sh = _fill._client().open_by_key(DEST_SPREADSHEET_ID)
    all_tabs = {t.title: t for t in sh.worksheets()}
    owner_tabs = [t for t in all_tabs if t != "Template"]
    if only:
        owner_tabs = [t for t in owner_tabs if t in only]
    if skip:
        owner_tabs = [t for t in owner_tabs if t not in skip]

    today = dt.date.today()
    if args.daily_window:
        # Mid-week fast path: re-scrape yesterday + today only. Yesterday
        # is re-pulled because the prior run scraped it as a partial,
        # still-in-progress day; now that it's complete its numbers are
        # final. Today is scraped for an early read — the next run
        # finalizes it. Days before yesterday don't change.
        days = [today - dt.timedelta(days=1), today]
    else:
        if args.week_start:
            monday = dt.datetime.strptime(args.week_start, "%Y-%m-%d").date()
        else:
            monday = today - dt.timedelta(days=today.weekday())
        days = [monday + dt.timedelta(days=i) for i in range(7)
                if monday + dt.timedelta(days=i) <= today]

    # Resume: skip owners already scraped OK in an interrupted run earlier
    # today. Only normal full / daily runs use the checkpoint — targeted
    # --only / --skip / --week-start / --dry-run runs always scrape fresh.
    checkpoint_active = not (only or skip or args.week_start or args.dry_run)
    run_key = f"{today.isoformat()}|{'daily' if args.daily_window else 'full'}"
    resumed: list[str] = []
    if checkpoint_active:
        cp = _read_checkpoint()
        if cp and cp.get("run_key") == run_key and _checkpoint_fresh(cp):
            resumed = [o for o in cp.get("completed", []) if o in owner_tabs]
            if resumed:
                _done = set(resumed)
                owner_tabs = [t for t in owner_tabs if t not in _done]
                print(f"↻ Resuming an interrupted run — {len(resumed)} owner(s) "
                      f"already scraped today, {len(owner_tabs)} left.")
        else:
            # No usable checkpoint — start a clean one for this run.
            _write_checkpoint(run_key, [])

    print(f"Plan: scrape {len(owner_tabs)} owner(s); days: {[d.strftime('%a %m/%d') for d in days]}")
    for i, t in enumerate(owner_tabs, 1):
        print(f"  {i:>2}. {t}")
    if args.dry_run:
        print("\n[DRY-RUN] no scraping performed.")
        return 0

    # Owners carried over from an interrupted run already scraped OK.
    results: dict[str, str] = {o: "ok" for o in resumed}
    # Unattended ownerville login via patchright — replaces the debug-Chrome
    # CDP attach (broken on Chrome 148). Megan 2026-05-25.
    from automations.shared.tableau_patchright import ownerville_session
    with ownerville_session(verbose=True) as page:
        print(f"✓ Ownerville session ready. URL: {page.url}")

        aliases_raw = load_aliases()
        if aliases_raw:
            total = sum(len(v) for v in aliases_raw.values())
            print(f"  Loaded {total} owner alias(es) for {len(aliases_raw)} ICD(s) from Sheet")

        # Clear any pre-existing impersonation lock. If Megan's Chrome was
        # left in an impersonated state from a previous (interrupted) run,
        # the server bounces ?p=901 → ?p=2&bounce=990 until exitImpersonate
        # is called. Always safe — returns ok=false if not currently impersonating.
        if _exit_impersonation(page):
            print("  ✓ Cleared lingering impersonation from prior session")

        for i, owner in enumerate(owner_tabs, 1):
            print(f"\n[{i}/{len(owner_tabs)}] === {owner} ===")
            scraped_ok = False
            is_master = owner in NO_IMPERSONATE_OWNERS
            try:
                if is_master:
                    # Master-level owner (e.g. Raf) — no impersonation. Get a
                    # fresh master rqst by navigating to root, then scrape
                    # ?p=510 + ?p=89 directly with that rqst.
                    print(f"  → Master-level owner — skipping impersonation")
                    rqst = _capture_master_rqst(page)
                    if not rqst:
                        results[owner] = "no master rqst"
                        continue
                    ws = all_tabs[owner]
                    stats = _scrape_one_owner(page, ws, days, rqst)
                    scraped_ok = True
                    results[owner] = "ok"
                    if checkpoint_active:
                        _checkpoint_mark_done(run_key, owner)
                    tt = sum(stats["tt_counts"].values())
                    disp = sum(stats["disp_counts"].values())
                    print(f"  ✓ wrote {stats['written']} cell(s); TT={tt} rep-days, "
                          f"Disp={disp} rep-days; +{len(stats['new_reps'])} new rep(s)")
                    continue

                # _navigate_to_office_access navigates the ownerville tab to
                # root + then ?p=901. Works on iteration 1 (no impersonation
                # yet); works on iterations 2+ because we exit_impersonation
                # at the end of each previous iteration, releasing the server
                # lock that would otherwise bounce ?p=901 to ?p=2.
                if not _navigate_to_office_access(page):
                    results[owner] = "couldn't reach Office Access"
                    continue
                rqst, reason = _find_owner_and_impersonate(page, owner, aliases_raw)
                if not rqst:
                    results[owner] = reason
                    continue
                print(f"  ✓ Impersonated; rqst={rqst[:8]}…")
                ws = all_tabs[owner]
                stats = _scrape_one_owner(page, ws, days, rqst)
                scraped_ok = True
                results[owner] = "ok"
                if checkpoint_active:
                    _checkpoint_mark_done(run_key, owner)
                tt = sum(stats["tt_counts"].values())
                disp = sum(stats["disp_counts"].values())
                print(f"  ✓ wrote {stats['written']} cell(s); TT={tt} rep-days, Disp={disp} rep-days; "
                      f"+{len(stats['new_reps'])} new rep(s)")
            except Exception as e:
                results[owner] = f"exception: {type(e).__name__}: {str(e)[:120]}"
                print(f"  ✗ {results[owner]}")
                traceback.print_exc()
            finally:
                if is_master:
                    # No impersonation to exit; nothing to do.
                    continue
                # ALWAYS exit impersonation between owners so the master
                # rqst is valid for the next iteration's ?p=901 navigation.
                # Safe even if we didn't successfully impersonate — returns
                # ok=false in that case and we just continue.
                if _exit_impersonation(page):
                    print(f"  ✓ Exited impersonation")
                elif scraped_ok:
                    print(f"  ⚠ Exit-impersonation call didn't succeed; next owner may fail")
    # (ownerville_session closes the browser on exit — no manual teardown)

    print("\n=== SUMMARY ===")
    ok = [o for o, s in results.items() if s == "ok"]
    bad = [(o, s) for o, s in results.items() if s != "ok"]
    print(f"  ✓ {len(ok)} owner(s) scraped OK")
    for o, s in bad:
        print(f"  ✗ {o}: {s}")

    # Persist per-owner results so the daily entrypoint can color tabs
    # (owners that didn't scrape OK = pending OV access → amber).
    #
    # MERGE semantics — when --only is used (e.g. retry just Steve),
    # we MUST NOT wipe out the other owners' statuses from the previous
    # full run. We read the existing file, overlay this run's results
    # on top, and write back. For a full run (no --only filter) we get
    # the same end state as before because every owner appears in
    # `results` anyway.
    try:
        results_path = Path(__file__).resolve().parents[2] / "output" / "focus_office_scrape_results.json"
        results_path.parent.mkdir(parents=True, exist_ok=True)
        merged: dict = {}
        if results_path.exists():
            try:
                prev = json.loads(results_path.read_text())
                merged = dict(prev.get("results", {}) or {})
            except Exception:
                merged = {}
        merged.update(results)   # current run overlays previous
        results_path.write_text(json.dumps({
            "run_at": dt.datetime.now().isoformat(timespec="seconds"),
            "results": merged,
        }, indent=2))
    except Exception as e:
        print(f"  ⚠ couldn't write scrape-results file: {e}")

    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
