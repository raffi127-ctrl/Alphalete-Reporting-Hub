"""Daily-run orchestrator for the Alphalete ORG Sales Board.

Runs the daily sections in the FASTEST order (sources.run_order):
  Stage 1  HTTP pulls    — cheap (~1-2s), one shared requests.Session,
                           cookies lifted ONCE; sections sharing a pull
                           (Retail NL + Retail Internet) pull together.
  Stage 2  CROSSTAB pulls — expensive UI (~60-90s), one reused patchright
                           browser session, no re-auth between pulls.
  Stage 3  MANUAL         — hand-keyed (Retail JE, Frontier); filled from
                           a supplied dict, otherwise left for manual entry.

Auth is PATCHRIGHT ONLY, like every other report ([[project_recruiting_
cdp_fragile]]): ONE tableau_session() patchright page for the whole run.
HTTP pulls reuse its cookies via requests_session_from_page(); crosstab
pulls reuse the same page. No CDP / debug-Chrome.

Each source group resolves to an ADAPTER that returns the engine's input
shape {owner_norm: {metric: {date: value}}}. Onboarding a section = wire
its adapter here once its view's per-day columns are confirmed live. Only
`sara_retail` is implemented + verified today; the rest log a clear
"needs live column confirm" and are skipped so the run still completes and
fills everything it can ([[feedback_fill_but_flag]]).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Callable, Dict, Optional

from automations.org_sales_board import fill_section as fs
from automations.org_sales_board import sources as src

PullDict = Dict[str, Dict[str, Dict[dt.date, int]]]


class AdapterContext:
    """Shared state passed to every adapter so they reuse the ONE patchright
    session (page for crosstabs, lifted cookies for HTTP) and a single grid
    read."""
    def __init__(self, *, today, out_dir: Path, from_csv: Optional[Path],
                 page, logfn: Callable[[str], None]):
        self.today = today
        self.out_dir = out_dir
        self.from_csv = from_csv
        self.page = page                # patchright Page (None in offline mode)
        self.logfn = logfn
        self._http_session = None       # lazy requests.Session (cookies once)

    def http_session(self):
        """requests.Session carrying the patchright context's Tableau
        cookies — same bridge opt_nds/opt_retail use for HTTP .csv pulls."""
        if self._http_session is None:
            from automations.shared.tableau_patchright import (
                requests_session_from_page,
            )
            self._http_session = requests_session_from_page(self.page)
        return self._http_session


# ----------------------------------------------------------- adapters

def _adapter_sara_retail(ctx: AdapterContext) -> PullDict:
    """Retail NL + Retail Internet — ONE SARA pull, two metrics. Verified."""
    from automations.org_sales_board import sara_pull
    if ctx.from_csv:
        csv_path = ctx.from_csv
        ctx.logfn(f"  [sara_retail] offline CSV {csv_path}")
    else:
        csv_path = sara_pull.pull_retail_nl_byday(
            ctx.out_dir, ctx.page, today=ctx.today, logfn=ctx.logfn)
    return sara_pull.parse_sara_byday_perday(
        csv_path, metrics=[sara_pull.METRIC_WIRELESS_LINES,
                           sara_pull.METRIC_INTERNET])


def _make_section_adapter(spec_key: str):
    """Build an adapter for a single-metric scraped section (Fiber/NDS/B2B)
    off its ScrapeSpec. One scrape → engine shape via section_pull."""
    def _adapter(ctx: AdapterContext) -> PullDict:
        from automations.org_sales_board import section_pull
        spec = section_pull.SPECS[spec_key]
        today = ctx.today or dt.date.today()
        if ctx.from_csv:
            csv_path = ctx.from_csv
            ctx.logfn(f"  [{spec_key}] offline CSV {csv_path}")
        else:
            csv_path = section_pull.pull_section_byday(
                spec, ctx.out_dir, ctx.page, logfn=ctx.logfn, today=today)
        return section_pull.parse_byday(spec, csv_path, today)
    return _adapter


# shared_key -> adapter. Unlisted keys are not yet implemented.
ADAPTERS: Dict[str, Callable[[AdapterContext], PullDict]] = {
    "sara_retail": _adapter_sara_retail,
    "fiber": _make_section_adapter("fiber"),
    "nds": _make_section_adapter("nds"),
    "b2b": _make_section_adapter("b2b"),
    "box": _make_section_adapter("box"),
}


# ----------------------------------------------------------- orchestration

def run_daily(ws, *, dry_run: bool = True, today=None,
              from_csv: Optional[Path] = None,
              only: Optional[list[str]] = None,
              include_captainships: bool = False,
              logfn: Callable[[str], None] = print) -> dict:
    """Execute the daily sections in fastest order under ONE patchright
    session. Returns a summary {filled, skipped, manual}. `only` restricts
    to specific section labels; `from_csv` feeds the SARA adapter offline
    (no browser opened) for engine validation. `include_captainships` runs
    the 10 captainship leaderboards in the SAME session after the sections
    (one login for the whole board) — always needs a live pull."""
    # Does this run actually need a live pull? (Offline if from_csv covers
    # everything, or only manual sections were requested.) Captainships
    # always pull live, so they force the session open.
    needs_pull = include_captainships or (from_csv is None and any(
        s.method != src.MANUAL and src.shared_groups().get(s.shared_key)
        and (not only or s.label in only)
        and s.shared_key in ADAPTERS
        for s in src.DAILY_SOURCES))

    if not needs_pull:
        return _run_daily_inner(ws, page=None, dry_run=dry_run, today=today,
                                from_csv=from_csv, only=only, logfn=logfn,
                                include_captainships=include_captainships)

    from automations.shared.tableau_patchright import tableau_session
    with tableau_session(verbose=False) as page:
        return _run_daily_inner(ws, page=page, dry_run=dry_run, today=today,
                                from_csv=from_csv, only=only, logfn=logfn,
                                include_captainships=include_captainships)


def _run_daily_inner(ws, *, page, dry_run, today, from_csv, only,
                     logfn, include_captainships=False) -> dict:
    grid = ws.get_all_values()
    raw_aliases = fs.load_aliases()
    ctx = AdapterContext(today=today, out_dir=Path("output"),
                         from_csv=from_csv, page=page, logfn=logfn)
    summary = {"filled": [], "skipped": [], "manual": []}

    stage_names = ["Tableau scrape (one session)", "MANUAL"]
    for stage_idx, group in enumerate(src.run_order()):
        if not group:
            continue
        name = stage_names[stage_idx] if stage_idx < len(stage_names) else "?"
        logfn(f"--- Stage {stage_idx + 1}: {name} ---")
        for source in group:
            if only and source.label not in only:
                continue
            sections = src.shared_groups().get(source.shared_key, [source])
            labels = [s.label for s in sections]

            if source.method == src.MANUAL:
                logfn(f"  {labels}: MANUAL — hand-key (rollover still freezes "
                      f"its weekly total)")
                summary["manual"].extend(labels)
                continue

            adapter = ADAPTERS.get(source.shared_key)
            if adapter is None:
                logfn(f"  {labels}: SKIP — adapter not wired yet "
                      f"(needs live column confirm of "
                      f"{source.workbook}/{source.view})")
                summary["skipped"].extend(labels)
                continue

            try:
                pull = adapter(ctx)
            except Exception as e:
                logfn(f"  {labels}: pull FAILED — {type(e).__name__}: {e}")
                summary["skipped"].extend(labels)
                continue
            logfn(f"  {labels}: parsed {len(pull)} owner(s)")

            for sec in sections:
                spec = fs.SectionSpec(label=sec.label, metric=sec.metric)
                plan = fs.plan_section_fill(grid, spec, pull,
                                            raw_aliases=raw_aliases,
                                            today=today)
                fs.apply_plan(ws, plan, dry_run=dry_run, logfn=logfn)
                summary["filled"].append(sec.label)

    logfn(f"=== daily summary: filled={summary['filled']} "
          f"skipped={summary['skipped']} manual={summary['manual']} ===")

    # Captainship leaderboards reuse THIS session's page — one login for the
    # whole board instead of a second --step captainships pass.
    if include_captainships:
        if page is None:
            logfn("  captainships SKIPPED — no live session (offline run)")
        else:
            from automations.org_sales_board import captainship
            logfn("--- Captainships (same session) ---")
            cap = captainship.run_captainships(ws, page, today=today,
                                               dry_run=dry_run, logfn=logfn)
            summary["captainships"] = cap

    return summary
