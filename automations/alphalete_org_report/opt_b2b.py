"""B2B OPT fill for every B2B ICD tab — most on the Alphalete Org sheet.

Megan 2026-05-24: "it's the same mapping from Carlos's report — duplicate it
onto this report." It IS the same metric set (confirmed by label diff: 62
shared labels), just at different ROW positions on Valeria's tab. So this
module REUSES Carlos's B2B engine (automations.recruiting_report.
opt_phase_carlos) wholesale — its VIEWS, ROW_TO_LABEL, values_for_icd,
apply_computed and write_icd_values — and only:

  1. downloads each ATTTRACKER-B2B view via the automated patchright path
     (Carlos's module uses manual CDP Chrome at :9222), and
  2. maps every metric to Valeria's row BY LABEL (never by Carlos's hardcoded
     row number) via metric_row_for_tab + a per-tab row_remap.

Metrics filled (canonical row → label, from ROW_TO_LABEL):
  Active Headcount on Tableau, New Internets, Voice Sales, Wireless, New
  Lines, Total Apps*, AVG Apps Per Active Headcount*, AVG New INT Sales*,
  National AVG Apps, Scorecard Ranking, 0-30 Day Cancel Rate, Activation/
  Approval %, the five churn rows, Penetration Rate, Direct Deposit.
  (* = computed in Python by apply_computed.)

Direct Deposit comes from the shared Program Summary workbook (same source
+ parser as JE). Personal Production (canonical row 42) is the ICD's OWN
self-row, read from SALES SUMMARY via `automations.shared.b2b_sales_summary`
(the old per-rep worksheet did not survive the 2026-08 ATTTRACKER-B2B
republish; that module carries the replacement recipe).

Every source below is downloaded inside its own try/except so one dead view
can't cost the whole fill. The price of that is silence, so anything that
fails to download is collected into `missing_sources` and turned into a
#claudecorrections ping by __main__ — a missing source costs CELLS, not tabs,
and without the ping the run just looks clean.
"""

import datetime as dt
import re
from pathlib import Path
from typing import List, Optional

import gspread

from automations.recruiting_report import fill as rfill
from automations.recruiting_report import opt_phase_carlos as cb
from automations.recruiting_report.opt_phase import drive_crosstab_dialog
from automations.alphalete_org_report.opt_nds import (
    ALPHALETE_ORG_SHEET_ID, OUTPUT_DIR, ORG_DD_URL, ORG_DD_SHEET,
    parse_direct_deposit, match_dd_owner, _norm_owner, _current_target_week_end)
from automations.shared import b2b_sales_summary as B2BSS
from automations.shared.tableau_patchright import (
    tableau_session, download_crosstab_patchright)


B2B_TAB = "Valeria Tristan - B2B"
B2B_ICD = "Valeria Tristan"
DD_ROW = 51   # canonical Direct Deposit row in ROW_TO_LABEL
PP_ROW = 42   # canonical Personal Production row

# All B2B ICDs on the Alphalete Org sheet: (ICD name, sheet tab). Carlos is the
# head — his full B2B OPT block fills here too (Megan 2026-06-03), not just
# Valeria's. The crosstab views carry every ICD, so we download once and extract
# per ICD.
# Each entry: (Tableau ICD name, sheet tab). An optional 3rd element names the
# CAPTAINSHIP whose spreadsheet the tab lives on — omitted means the Alphalete
# Org sheet, which is where every ICD here sat until Calvin Ribero. An optional
# 4th element gives extra Tableau spellings to try (the Org mapping's as_owner
# is only consulted for tabs on the Org sheet).
B2B_ICDS = [
    ("Valeria Tristan", "Valeria Tristan - B2B"),
    ("Carlos Hidalgo",  "Carlos Hidalgo -B2B"),
    # Atef Choudhury (Domin8 Acquisitions, office 23467) — added 2026-07-27.
    # NOTE the spelling split: the sheet tab says "Choudhry", AppStream and
    # Tableau say "Choudhury". The ICD name here must match TABLEAU; the tab
    # string is only the write target. _b2b_fallback_names also picks up
    # as_owner from office-mapping-alphalete-org.json for the same reason.
    # Not to be confused with Boaktear Chowdhury (Retail) — different person.
    ("Atef Choudhury",  "Atef Choudhry - B2B"),
    # Eveliz Wright (South Shore Consulting, office 18404) and Lizette
    # Ruiz-Conejo (Revolution Consulting, office 22109) — added 2026-07-27.
    # Both had a tab AND an AppStream office but sat in the mapping's `skip`
    # list with no reason, so neither half ever ran for them. Lizette is
    # another tab-vs-source spelling split: tab "Lizette Ruiz", AppStream and
    # Tableau "Lizette Ruiz-Conejo".
    ("Eveliz Wright",       "Eveliz Wright - B2B"),
    # FUERA 2026-08-31 (Eveliz, confirmado por Eve): Lizette Ruiz-Conejo ya no
    # es parte de la org. Su pestaña quedó OCULTA, no borrada, y su entrada
    # pasó a `skip` en office-mapping-alphalete-org.json. Tiene que salir de
    # ACÁ además: este módulo NO mira el flag `hidden`, así que si no le
    # seguiría escribiendo 19 celdas de OPT a una pestaña oculta.
    # ("Lizette Ruiz-Conejo", "Lizette Ruiz - B2B"),
    # Calvin Ribero was here from 2026-08-30 to 2026-08-31. REMOVED: he is not
    # a B2B ICD at all. Vernon, Inc. (ownerville office 22162, Chicago IL) is
    # not provisioned for B2B AT&T SBS, and he is in no B2B crosstab under
    # either spelling — which is why this step wrote nothing to his tab for a
    # month, silently.
    # He sells BOX (Box Energy): `B2BBOXEnergyTracker` -> view
    # **BoxDailyTracker**, 27 sales the week ending 8/30/2026. Note it is that
    # view specifically — `BoxSalesMetrics`, which opt_box reads, is scoped to
    # three owners and does not carry him either. His tab is filled by
    # `automations.alphalete_org_report.opt_box_daily`, which reaches across to
    # Raf's ATT Program - Focus Report the same way this list used to.
]

# Personal Production = the ICD's OWN sales for the week: the rep row where
# REP == the ICD's own name, formatted '3 NI / 2 NL'.
#
# The source moved (2026-08). The old per-rep 'Sales.Quality Metrics' worksheet
# did not survive the ATTTRACKER-B2B republish — what is left under that name is
# OWNER-level and carries the same product columns, which is exactly the trap
# that made row 42 wrong-or-blank in silence. The replacement is SALES SUMMARY's
# 'Sales Summary - Owner (+/-) Rep', and everything about reading it (the date
# boxes, the canvas '+' that has to be clicked to get rep rows at all, the
# CRU/IRU sums) lives in the shared module — Carlos's own Focus report reads the
# same source. [[project_b2b-worksheet-dedup-suffix-rename]]


def _parse_b2b_pp(path, logfn=print) -> dict:
    """Expanded SALES SUMMARY crosstab -> {rep-name-lower: {product: int}}.

    Returns {} when the export has no 'REP' column. That is not a parse detail:
    it means the Owner->Rep hierarchy was NOT expanded, so the export is
    owner-level and reading it would report each ICD's whole TEAM as their
    personal production. Empty makes the caller flag the source missing."""
    from automations.alphalete_org_report.opt_nds import _read_tab_csv
    rows = _read_tab_csv(path)
    by_rep = B2BSS.parse_owner_rep(rows)
    if not by_rep:
        headers = [(h or "").strip() for h in (rows[0] if rows else [])]
        logfn("OPT B2B: ✗ personal production: the export has no 'REP' "
              f"column, so the hierarchy never expanded. Columns: {headers}")
    return by_rep


def _b2b_pp_for(icd: str, by_rep: dict, fallback: str = "",
                logfn=print) -> str:
    """The ICD's OWN personal production: the rep row where REP == ICD name
    (with as_owner + first/last fallbacks). '-' when no self-row (the ICD runs
    a team but didn't personally sell), matching the manual-entry convention."""
    cands = [icd]
    if fallback and fallback.lower() != icd.lower():
        cands.append(fallback)
    rec = next((by_rep[c.lower()] for c in cands if c.lower() in by_rep), None)
    if rec is None:
        parts = icd.lower().split()
        if len(parts) >= 2:
            rec = next((v for k, v in by_rep.items()
                        if k.startswith(parts[0]) and k.endswith(parts[-1])), None)
    if rec is None and by_rep:
        # '-' has TWO meanings and they need different fixes: the ICD really
        # didn't sell this week, or their name is spelled differently in the
        # rep list. Say which, by naming any rep sharing their surname —
        # otherwise a spelling drift reads as a quiet, plausible zero.
        # Compare surname to surname. A plain substring test reports
        # 'tristan gehrt' as a near-miss for 'Valeria Tristan', where Tristan is
        # that rep's FIRST name — a false lead that argues for an alias nobody
        # needs. '-' for these ICDs is normal: they run a team and don't sell.
        surname = icd.lower().split()[-1] if icd.split() else ""
        near = [k for k in by_rep
                if surname and k.split() and k.split()[-1] == surname][:4]
        logfn(f"OPT B2B:   PP no self-row for {icd!r}"
              + (f" — but these reps share the surname: {near}. If one IS them,"
                 f" the spelling drifted; add it to the mapping's as_owner."
                 if near else " (no rep shares their surname — they simply "
                              "didn't sell this week)"))
    return B2BSS.format_pp(rec)


def _b2b_fallback_names(tab: str = B2B_TAB) -> List[str]:
    """Alternate names for an ICD from the Alphalete Org mapping (Tableau may
    spell the legal name differently than the tab)."""
    import json
    p = (Path(__file__).resolve().parent.parent / "recruiting_report"
         / "office-mapping-alphalete-org.json")
    try:
        data = json.loads(p.read_text())
    except Exception:
        return []
    for c in data.get("confirmed", []):
        if c.get("sheet_tab") == tab:
            return [n for n in (c.get("as_owner"),) if n]
    return []


def _week_col_label(today: Optional[dt.date] = None) -> str:
    # Same target as the rest of the Alphalete Org OPT (most recent Sunday
    # on-or-before today) so B2B fills the current week's column (5/24), not
    # the prior finalized one (5/17).
    d = _current_target_week_end(today)
    return f"{d.month}/{d.day}/{d.year % 100}"


def _download_by_substring(page, url: str, substr: str, out: Path,
                           key: str = "", logfn=print, pre_export=None) -> bool:
    """Download the crosstab worksheet whose dialog name CONTAINS `substr`.

    An EXACT worksheet name is the most brittle handle there is: Tableau appends
    dedup counters ('(3)') and a republish renames sheets wholesale. So
    enumerate the dialog, substring-match, then download that exact name.
    Returns True on success.

    On no match the FULL available list is logged, never truncated — when
    ATTTRACKER-B2B was republished the only thing that would have said what the
    sheet BECAME was that list, and every trace of it was cut off at 120 chars.
    """
    try:
        drive_crosstab_dialog(page, url, "__enumerate__", out, verbose=False)
        return False   # shouldn't reach — enumerate always raises
    except RuntimeError as e:
        m = re.search(r":\s*(\[.*\])\.", str(e))
        avail = []
        if m:
            import ast
            try:
                avail = ast.literal_eval(m.group(1))
            except Exception:
                avail = []
        target = next((s for s in avail if substr.lower() in s.lower()), None)
        if target is None:
            logfn(f"OPT B2B: ✗ {key or substr}: no worksheet matching "
                  f"{substr!r} in {avail}")
            return False
        # pre_export runs only on the REAL download. The enumerate pass above
        # doesn't need it — the sheet list doesn't depend on filters — and
        # skipping it there saves re-driving the dates + a 25s expand twice.
        drive_crosstab_dialog(page, url, target, out, verbose=False,
                              pre_export=pre_export)
        return True


def _download_view(page, view: "cb.ViewConfig", out: Path, logfn=print) -> bool:
    """Download a crosstab view via patchright, matching its worksheet by
    view.sheet_thumbnail_match (a SUBSTRING). Returns True on success."""
    return _download_by_substring(page, view.url, view.sheet_thumbnail_match,
                                  out, key=view.key, logfn=logfn)


def collect_b2b_views(page, logfn=print) -> dict:
    """Download + parse all B2B views + DD + Personal-Production ONCE (the
    crosstabs carry every ICD). Returns the parsed data for per-ICD extraction:
      {'views': {key: (by_owner, grand, view)}, 'dd': parsed_dd, 'pp': by_rep,
       'missing': [source keys that did not download]}.

    'missing' is what makes a dead source LOUD. Every download below is caught
    so one bad source can't cost the whole fill — but that also meant a source
    could disappear and the only trace was a log line: on 2026-08-10 the
    ATTTRACKER-B2B republish took the Personal Production worksheet with it and
    every B2B ICD quietly got '-' in row 42, step exit 0, no alert."""
    views: dict = {}
    missing: List[str] = []
    for view in cb.VIEWS:
        if view.key in ("dd", "personal_production"):
            continue
        out = OUTPUT_DIR / f"opt_b2b_{view.key}.csv"
        try:
            if not _download_view(page, view, out, logfn):
                missing.append(view.key)
                continue
            _hdr, by_owner, grand = cb._parse_view_csv(
                out, key_column=view.key_column, key_clean=view.key_clean,
                subrow_column=view.subrow_column, subrow_value=view.subrow_value,
                keep_all_rows=bool(view.aggregator))
            views[view.key] = (by_owner, grand, view)
            logfn(f"OPT B2B: {view.key}: {len(by_owner)} owner(s)")
        except Exception as e:
            logfn(f"OPT B2B: ✗ {view.key}: {type(e).__name__}: {str(e)[:120]}")
            missing.append(view.key)

    dd_parsed: dict = {}
    try:
        dd_out = OUTPUT_DIR / "opt_b2b_dd.csv"
        download_crosstab_patchright(ORG_DD_URL, ORG_DD_SHEET, dd_out,
                                     verbose=False, page=page)
        dd_parsed = parse_direct_deposit(dd_out)
    except Exception as e:
        logfn(f"OPT B2B: ✗ dd: {type(e).__name__}: {str(e)[:120]}")
        missing.append("dd")

    pp_by_rep: dict = {}
    pp_out = OUTPUT_DIR / "opt_b2b_personal_production.csv"
    try:
        # The week the rest of this step is filling — the SALES SUMMARY view has
        # no URL date param, so the window goes in through the hook's date boxes.
        pp_start, pp_end = B2BSS.week_bounds(_current_target_week_end())
        if _download_by_substring(
                page, B2BSS.VIEW_URL, B2BSS.SHEET_MATCH, pp_out,
                key="personal production", logfn=logfn,
                pre_export=B2BSS.expand_hook(pp_start, pp_end)):
            pp_by_rep = _parse_b2b_pp(pp_out, logfn)
            logfn(f"OPT B2B: personal production: {len(pp_by_rep)} rep(s) "
                  f"({pp_start} → {pp_end})")
    except Exception as e:
        logfn(f"OPT B2B: ✗ personal production: {type(e).__name__}: {str(e)[:120]}")
    if not pp_by_rep:
        missing.append("personal production")

    return {"views": views, "dd": dd_parsed, "pp": pp_by_rep,
            "missing": missing}


def values_for_b2b_icd(icd: str, tab: str, parsed: dict, logfn=print,
                       fallbacks: Optional[List[str]] = None) -> dict:
    """Extract one ICD's {canonical_row: value} from the once-parsed data —
    every view, DD, and Personal Production (row 42) — then apply_computed.

    `fallbacks` are extra Tableau spellings to try before falling back to the
    Alphalete Org mapping's as_owner. A tab on ANOTHER sheet has no row in that
    mapping, so passing them is the only way its alternate spelling is tried.
    """
    fallback = list(fallbacks or []) + _b2b_fallback_names(tab)
    fb = fallback[0] if fallback else ""
    values: dict = {}
    for key, (by_owner, grand, view) in parsed["views"].items():
        values.update(cb.values_for_icd(icd, by_owner, grand, view,
                                        fallback_names=fallback))
    dd_v = match_dd_owner(parsed["dd"], icd)
    if dd_v is not None:
        values[DD_ROW] = f"${dd_v:,.2f}"
    values[PP_ROW] = _b2b_pp_for(icd, parsed["pp"], fb, logfn)
    return cb.apply_computed(values)


def fill_b2b_tab(ws: gspread.Worksheet, values: dict, week_label: str,
                 dry_run: bool = False, logfn=print) -> List[str]:
    """Write {canonical_row: value} to Valeria's tab, mapping each canonical
    row to her actual row BY LABEL (ROW_TO_LABEL → metric_row_for_tab)."""
    grid = rfill._retry(ws.get_all_values)
    if not grid:
        return [f"[skip-b2b] {ws.title}: empty tab"]
    header = grid[0]
    target_col = next((i + 1 for i, h in enumerate(header)
                       if (h or "").strip() == week_label), None)
    if target_col is None:
        return [f"[skip-b2b] {ws.title}: no column for week {week_label}"]
    col_b = [(r[1] if len(r) > 1 else "") for r in grid]
    # Build the per-tab remap: canonical row -> this ICD's actual row, by label.
    remap = {}
    for canon, label in cb.ROW_TO_LABEL.items():
        r = cb.metric_row_for_tab(col_b, label)
        if r is not None:
            remap[canon] = r
    # Personal Production (row 42) isn't in ROW_TO_LABEL — look it up by label.
    pp_r = cb.metric_row_for_tab(col_b, "Personal Production")
    if pp_r is not None:
        remap[PP_ROW] = pp_r
    return cb.write_icd_values(ws, values, target_col, dry_run=dry_run,
                               row_remap=remap)


def run_b2b_opt(dry_run: bool = False, logfn=print) -> dict:
    """Pull the B2B views ONCE + fill every B2B ICD in B2B_ICDS. Each ICD's
    full OPT block, incl. PP.

    Most tabs are on the Alphalete Org sheet; an entry may name another
    captainship's spreadsheet instead (Calvin Ribero → Raf's ATT Program -
    Focus Report). The crosstabs are org-wide, so the extra tabs cost a write,
    not another download."""
    week_label = _week_col_label()
    logfn(f"OPT B2B: target week = {week_label!r}")
    try:
        with tableau_session(verbose=False) as page:
            parsed = collect_b2b_views(page, logfn)
    except Exception as e:
        msg = f"{type(e).__name__}: {str(e)[:140]}"
        logfn(f"OPT B2B: ✗ session: {msg}")
        return {"filled": [], "skipped": [], "errors": [msg],
                "missing_sources": ["Tableau session"]}

    client = rfill._client()
    # One open per TARGET spreadsheet, cached: nearly every ICD is on the Org
    # sheet, and re-opening it per tab would be five needless API round trips.
    sheets: dict = {}

    def _sheet_for(captainship: Optional[str]):
        key = captainship or "_org"
        if key not in sheets:
            sid = (ALPHALETE_ORG_SHEET_ID if captainship is None
                   else rfill.captainship_sheet_id(captainship))
            sheets[key] = rfill.open_by_key(sid, client)
        return sheets[key]

    filled, skipped = [], []
    for entry in B2B_ICDS:
        icd, tab = entry[0], entry[1]
        captainship = entry[2] if len(entry) > 2 else None
        fallbacks = list(entry[3]) if len(entry) > 3 else []
        values = values_for_b2b_icd(icd, tab, parsed, logfn,
                                    fallbacks=fallbacks)
        logfn(f"OPT B2B: collected {len(values)} metric(s) for {icd}")
        try:
            ws = rfill._retry(_sheet_for(captainship).worksheet, tab)
        except Exception as e:
            logfn(f"OPT B2B: ✗ {tab}: {type(e).__name__}: {str(e)[:120]}")
            skipped.append(tab)
            continue
        for ln in fill_b2b_tab(ws, values, week_label, dry_run, logfn):
            logfn(f"OPT B2B: {ln}")
            if ln.lstrip().startswith(("[OK", "[DRY-RUN")):
                filled.append(tab)
    return {"filled": filled, "skipped": skipped, "errors": [],
            "missing_sources": parsed.get("missing") or []}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    result = run_b2b_opt(dry_run=args.dry_run)
    print(f"\nFilled: {len(result['filled'])}; Errors: {len(result['errors'])}")
    for e in result["errors"]:
        print(f"  ✗ {e}")

    # A source that doesn't download costs CELLS, not tabs: the tab still lands
    # in `filled` because its OTHER metrics arrived, so 'Filled: 5; Errors: 0'
    # reads like a clean run while a whole row is blank across every B2B ICD.
    # Record it so the loud #claudecorrections ping fires from write_manifest —
    # the same alarm opt_retail got on 2026-08-10, added here after the
    # Personal Production worksheet went missing on 2026-08-10 and nothing said
    # so for a week. Exit stays 0 on purpose: the rest of the fill DID work, and
    # a non-zero here would mark the whole step failed and hide that.
    missing = result.get("missing_sources") or []
    if missing and not args.dry_run:
        print(f"⚠ SOURCE(S) MISSING — metrics fed by these are blank for this "
              f"week: {', '.join(missing)}")
        try:
            from automations.shared import run_manifest as _rm
            _rm.write_manifest(
                "alphalete_org_b2b", failed=missing, retry_args=[],
                kind="source",
                note=(f"{len(missing)} Tableau source(s) did not download for "
                      "the B2B OPT step. The B2B tabs filled from the sources "
                      "that DID come through; the metrics behind the missing "
                      "ones are blank, not wrong. Re-run with "
                      "`lucy rerun alphalete_org_b2b` once the view is back."))
        except Exception as e:  # noqa: BLE001 — alerting never breaks the run
            print(f"  ⚠ couldn't record the missing-source manifest "
                  f"({type(e).__name__}: {str(e)[:120]})")
    elif not args.dry_run:
        # ...and the mirror image: EVERY source came through, so close whatever
        # `drop-alphalete_org_b2b` incident the last bad run left open in
        # #claudecorrections (run_manifest.write_manifest calls
        # section_drop_alert.resolved on a clean manifest).
        #
        # Without this the incident could never close itself. This step only
        # ever wrote a manifest on FAILURE, and the wrapper (opt_all) writes its
        # own 'alphalete-org-run' id, not this one — so the alert said "re-run
        # `alphalete_org_b2b` — the fill is idempotent" and then the successful
        # re-run left the thread sitting open anyway, which is how you end up
        # re-diagnosing something that was fixed days ago (Eve 2026-08-17,
        # closing drop-alphalete_org_b2b for the 'cancel' view).
        try:
            from automations.shared import run_manifest as _rm
            _rm.mark_clean("alphalete_org_b2b", kind="source")
        except Exception as e:  # noqa: BLE001 — closing never breaks a good run
            print(f"  ⚠ couldn't record the clean-run manifest "
                  f"({type(e).__name__}: {str(e)[:120]})")
