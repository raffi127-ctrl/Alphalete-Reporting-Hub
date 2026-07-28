"""Reconciliation — the completeness guarantee.

NEVER trust exit 0. After a report runs, re-open the target sheet (or read the
report's run-manifest) and confirm the data was ACTUALLY written — naming the
specific blanks when it wasn't. This is what catches a report that exits clean
having filled nothing or half a column (the Khalil row-clobber / half-refreshed
Tableau failure mode).

Verify is pluggable per report (config `verify` block):
  type 'manifest'        -> read output/manifests/<report_id>.json (ok / failed[])
  type 'sheet_column'    -> open sheet/tab, confirm the target date/week column
                            exists and the anchor rows are non-blank
  type 'not_configured'  -> can't verify yet; report VERIFY_UNKNOWN (a soft pass
                            in dry-run, surfaced as "verify not wired" so we wire
                            it during the dry-run week before cutover)

Reuses the existing gspread client (recruiting_report.fill) — same oauth-token,
same 429 retry — so we never spin up a second auth path.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ReconResult:
    ok: bool                       # True = verified filled
    unknown: bool = False          # True = could not verify (not wired)
    missing: List[str] = field(default_factory=list)
    note: str = ""


def verify(report, target_date: dt.date, *, dry_run: bool, verbose: bool = True) -> ReconResult:
    """Dispatch to the configured verifier for `report`."""
    vcfg = report.verify or {}
    vtype = vcfg.get("type", "not_configured")
    try:
        if vtype == "manifest":
            return _verify_manifest(vcfg, target_date)
        if vtype == "sheet_column":
            return _verify_sheet_column(vcfg, target_date)
        if vtype == "slack_sections":
            return _verify_slack_sections(vcfg, target_date)
        if vtype == "cells_nonblank":
            return _verify_cells_nonblank(vcfg, target_date)
        # not_configured / unknown
        return ReconResult(ok=True, unknown=True,
                           note=f"verify not wired ({vtype}) — confirm cells by hand")
    except Exception as e:
        # A reconciliation failure must never crash the orchestrator; report it.
        return ReconResult(ok=False, note=f"reconcile error: {str(e).splitlines()[0][:140]}")


# ---------------- manifest verifier ----------------

def _verify_manifest(vcfg: dict, target_date: dt.date) -> ReconResult:
    """Read the report's standard run-manifest (output/manifests/<id>.json).
    ok=true,failed=[] -> DONE. Otherwise name the failed units.

    FRESHNESS GATE: a manifest is only trusted when its run_ts is from
    `target_date`. A report that crashes BEFORE writing its manifest leaves the
    PRIOR run's file in place — without this check a stale `ok=true` would let
    the loop (and _reverify_terminal) flip a real failure to DONE. A stale
    manifest is treated as unknown (soft-pass) so the loop still relies on the
    exit code (which is checked first) and re-verify won't falsely clear it.
    This can only PREVENT a false DONE, never cause a false FAILED."""
    from automations.shared.run_manifest import read_manifest

    report_id = vcfg.get("report_id")
    m = read_manifest(report_id)
    if m is None:
        return ReconResult(ok=True, unknown=True,
                           note=f"no manifest found for {report_id!r} — confirm by hand")
    # Only a manifest written by TODAY's run is authoritative.
    run_date = None
    try:
        run_date = dt.datetime.fromisoformat(m.get("run_ts", "")).date()
    except Exception:
        run_date = None
    if run_date != target_date:
        stamp = run_date.isoformat() if run_date else "unknown"
        return ReconResult(ok=True, unknown=True,
                           note=f"manifest for {report_id!r} is stale "
                                f"(run {stamp}, expected {target_date.isoformat()}) "
                                f"— confirm by hand")
    if m.get("ok"):
        # Pass the report's own clean-run note through (e.g. Financial records
        # which workbooks it pulled) so the summary email can surface it; fall
        # back to the generic label when the report wrote none.
        return ReconResult(ok=True, note=m.get("note") or "manifest clean")
    failed = m.get("failed", []) or []
    return ReconResult(ok=False, missing=failed,
                       note=m.get("note", "") or f"{len(failed)} unit(s) failed")


# ---------------- slack-sections verifier (defense-in-depth) ----------------

def _verify_slack_sections(vcfg: dict, target_date: dt.date) -> ReconResult:
    """Verify a threaded Slack report posted EVERY section it enumerated in its
    parent, by comparing expected-vs-actual against Slack's own posted-state —
    NOT the report's self-report. This is the independent cross-check to the
    manifest verifier: the manifest trusts what the runner THOUGHT it posted;
    this trusts the thread_state.json the runner writes only AFTER each upload
    returns success. A section counts as posted only when it's actually landed.

    Why thread_state (not a live Slack read): these office channels are
    no-history-read for our token — the runner itself can't read them back, which
    is exactly why it persists thread_state.json (needs no Slack scope). So this
    verifier reuses that authority. It is PER MACHINE: the file lives on the
    runner that posted (Lucy 2 for b2b_metrics), and the orchestrator reconciling
    the same report runs on that same machine, so the file is local.

    Config:
      report_id: "b2b_metrics"   # which report's offices/sections to reconcile
      state_file: "output/b2b_quality/thread_state.json"  # actual-posted authority

    Completeness rule MIRRORS the runner: an office posts to its primary channel
    plus any mirrors, each keeping its own thread; a section counts present only
    when it's in EVERY one of that office's channels (set-intersection), so a
    mirror that dropped one still reads as a miss — same as the card pill.

    False-alarm guards:
      • Expected = ITEMS minus the office's skip_views (identical to the parent
        header), so a gated-out section is never expected. Items that post even
        when blank (Out of Bounds) are expected AND land, so never a miss.
      • state_file ABSENT entirely -> unknown (soft pass): can't verify from here
        (e.g. running on the wrong machine), never a false failure.
      • An office with NO thread_state for today -> "no parent posted" miss (the
        'didn't post at all' case), reported distinctly from a dropped section.
    """
    from pathlib import Path
    import json

    report_id = vcfg.get("report_id", "b2b_metrics")
    if report_id != "b2b_metrics":
        # Only b2b_metrics is wired to this adapter today; anything else is a
        # config typo — soft-pass rather than crash the reconcile.
        return ReconResult(ok=True, unknown=True,
                           note=f"slack_sections: no adapter for {report_id!r}")

    from automations.b2b_metrics import runner as _rn
    from automations.b2b_metrics import offices as _off

    repo_root = Path(__file__).resolve().parents[2]
    state_path = repo_root / vcfg.get("state_file",
                                      "output/b2b_quality/thread_state.json")
    if not state_path.exists():
        return ReconResult(ok=True, unknown=True,
                           note=f"slack_sections: {state_path.name} not present "
                                f"here — can't verify (per-machine state)")
    try:
        blob = json.loads(state_path.read_text())
    except Exception as e:
        return ReconResult(ok=True, unknown=True,
                           note=f"slack_sections: unreadable state ({str(e)[:60]})")

    def _posted_for(channel: str) -> set:
        entry = blob.get(f"{target_date.isoformat()}|{channel}")
        return set((entry or {}).get("posted") or []) if isinstance(entry, dict) else set()

    missing: List[str] = []
    for key in _off.ORDER:
        o = _off.get(key)
        expected = _rn.expected_ids(o)
        channels = [o.channel_id] + [c for c, _name in o.mirror_channels]
        posted_sets = [_posted_for(c) for c in channels]
        # No thread at all for this office today -> nothing posted -> whole office.
        if all(not s for s in posted_sets):
            missing.append(f"{key}: (no parent posted)")
            continue
        present = set.intersection(*posted_sets) if posted_sets else set()
        for sid in expected:
            if sid not in present:
                missing.append(f"{key}: {sid}")

    if missing:
        return ReconResult(ok=False, missing=missing,
                           note=f"{len(missing)} Slack section(s) not confirmed in-thread")
    return ReconResult(ok=True, note="all Slack sections confirmed in every thread")


# ---------------- sheet-column verifier ----------------

def _verify_sheet_column(vcfg: dict, target_date: dt.date) -> ReconResult:
    """Open the sheet/tab and confirm the target date/week column is filled in
    the anchor rows. Label-anchored (never positional). Config:
       sheet:        spreadsheet key
       tab:          worksheet title
       anchor_label: a column-B label whose row must be non-blank in the target col
       date_header:  'daily' | 'weekly_sunday' (how to find the target column)
       anchor_labels: optional list (all must be non-blank)
    """
    from automations.recruiting_report import fill

    key = vcfg.get("sheet")
    tab = vcfg.get("tab")
    labels = vcfg.get("anchor_labels") or ([vcfg["anchor_label"]] if vcfg.get("anchor_label") else [])
    if not (key and tab and labels):
        return ReconResult(ok=True, unknown=True, note="sheet_column verify under-specified")

    sh = fill.open_by_key(key)
    ws = sh.worksheet(tab)
    grid = ws.get_all_values()
    if not grid:
        return ReconResult(ok=False, note=f"tab {tab!r} is empty")

    col_idx = _find_target_column(grid, target_date, vcfg.get("date_header", "daily"))
    if col_idx is None:
        return ReconResult(ok=False,
                           note=f"target column for {target_date.isoformat()} not found in {tab!r}")

    missing: List[str] = []
    for label in labels:
        row_idx = _find_label_row(grid, label)
        if row_idx is None:
            missing.append(f"{label} (row label not found)")
            continue
        val = grid[row_idx][col_idx] if col_idx < len(grid[row_idx]) else ""
        if not str(val).strip():
            missing.append(f"{label} (blank in target column)")

    if missing:
        return ReconResult(ok=False, missing=missing,
                           note=f"{len(missing)} anchor cell(s) blank in {tab!r}")
    return ReconResult(ok=True, note=f"verified {len(labels)} anchor cell(s) filled in {tab!r}")


# ---------------- cells-nonblank verifier ----------------

def _verify_cells_nonblank(vcfg: dict, target_date: dt.date) -> ReconResult:
    """Confirm a SNAPSHOT board actually has data. Boards like the Country /
    All-Campaigns sales boards overwrite in place and label their columns with
    day NAMES (not dates), so the date-column verifier can't anchor them — but a
    run that produced an empty/broken board leaves its summary row blank. This
    re-reads that row and flags an empty board (the P1 'exited 0 but wrote
    nothing' case). Config (label-anchored, never positional):
       sheet:  spreadsheet key
       tab:    worksheet title
       checks: [{row_label, min_nonblank=1, start_col=2}]  (start_col: 0-based,
               2 = column C, i.e. skip the col-A/B label cells)
    NOTE: this catches a BLANK board, not a stale-but-populated one; no-run is
    still caught by the orchestrator's noon backstop (MISSED)."""
    from automations.recruiting_report import fill

    key, tab = vcfg.get("sheet"), vcfg.get("tab")
    checks = vcfg.get("checks") or []
    if not (key and tab and checks):
        return ReconResult(ok=True, unknown=True, note="cells_nonblank under-specified")
    sh = fill.open_by_key(key)
    ws = sh.worksheet(tab)
    grid = ws.get_all_values()
    if not grid:
        return ReconResult(ok=False, note=f"tab {tab!r} is empty")

    missing: List[str] = []
    for chk in checks:
        label = chk.get("row_label", "")
        need = int(chk.get("min_nonblank", 1))
        start = int(chk.get("start_col", 2))
        ri = _find_label_row(grid, label)
        if ri is None:
            missing.append(f"{label} (row label not found)")
            continue
        filled = [c for c in grid[ri][start:] if str(c).strip()]
        if len(filled) < need:
            missing.append(f"{label} ({len(filled)}/{need} cells filled)")

    if missing:
        return ReconResult(ok=False, missing=missing,
                           note=f"{len(missing)} board anchor(s) empty in {tab!r}")
    return ReconResult(ok=True, note=f"verified {len(checks)} board anchor(s) filled in {tab!r}")


def _find_label_row(grid, label: str) -> Optional[int]:
    """Find a row by its column-B (index 1) label — never positional."""
    norm = label.strip().lower()
    for i, row in enumerate(grid):
        if len(row) > 1 and row[1].strip().lower() == norm:
            return i
        if row and row[0].strip().lower() == norm:   # some tabs label in col A
            return i
    return None


def _find_target_column(grid, target_date: dt.date, mode: str) -> Optional[int]:
    """Find the column whose header matches the target date (daily) or the
    week-ending Sunday (weekly_sunday). Scans the first ~6 header rows for any
    cell that parses to the target date."""
    from automations.day_orchestrator.readiness import _parse_date

    want = target_date
    if mode == "weekly_sunday":
        # week-ending Sunday on/after target
        want = target_date + dt.timedelta(days=(6 - target_date.weekday()) % 7)
    for row in grid[:6]:
        for c, cell in enumerate(row):
            d = _parse_date(cell)
            if d and d == want:
                return c
    return None
