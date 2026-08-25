"""Vantura Master Sales Board — daily churn & activations update.

Flow (runbook 2026-07-13): pull each owner's 60-day Order Log + the Churn
Rates dashboard from Tableau → compute 0-30 bases/disconnects → RECONCILE
against the dashboard's 0-30 cell → only then write the live sheet
(Carlos: 'LUCY CHURN' + Activations tabs; Atef: Churn - Atef). If the derived
numbers don't match the dashboard, nothing is written and the run fails
loudly — that reconciliation is the whole safety story. The ONE exception is
a dashboard that hasn't rolled its 0-30 window forward yet, which reads as us
being wrong when we are the fresh side (_reconcile_stale_window).

  python -m automations.vantura_churn.run                # full daily run
  python -m automations.vantura_churn.run --dry-run      # compute + print only
  python -m automations.vantura_churn.run --owner carlos
  python -m automations.vantura_churn.run --from-files carlos=/path/a.xlsx atef=/path/b.xlsx
  python -m automations.vantura_churn.run --skip-reconcile   # only with --from-files
  python -m automations.vantura_churn.run --carlos-only --shot

Carlos's churn tab was PROMOTED 2026-07-19 from "Churn" to "LUCY CHURN" —
the rebuild carrying the activation-rate cells and the per-rep list. The old
"Churn" tab is no longer written; it stays in place for history and as a
back-out path.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path

from automations.recruiting_report import fill as _fill_shared
from automations.vantura_churn import compute, fill, pull

REPORT_ID = "vantura-churn"

# Atef's own board (Domin8) — his LUCY CHURN tab lives here, NOT on Carlos's
# sheet. Was writing to a "Churn - Atef" tab on Carlos's board (fill.SHEET_ID);
# 2026-07-21 each office now writes its OWN sheet's LUCY CHURN tab.
ATEF_SHEET_ID = "15YUHkAcG2AfiF6KRhCiOBKGDdS9nnjxdfvIXr7oRX30"

# Jamis Garay (Atomic Marketing) — onboarded 2026-07-31. His board's churn tab
# is spelled 'Lucy Churn'; tab lookup is case-tolerant now, but the name is
# recorded as the sheet actually spells it.
JAMIS_SHEET_ID = "1lDm-ZmV4OjAPipx-lbqQUrd1VifpULzRNP3klGqEZhU"

OWNER_CFG = [
    # (key, owner-name prefix in the crosstab, sheet id, churn tab, has-activations)
    ("carlos", "CARLOS HIDALGO", fill.SHEET_ID, fill.TAB_CHURN_CARLOS, True),
    ("atef", "ATEF CHOUDHURY", ATEF_SHEET_ID, "LUCY CHURN", False),
    ("jamis", "JAMIS GARAY", JAMIS_SHEET_ID, "Lucy Churn", False),
]

# Offices NOT yet in the default `--owner both` daily run. They are fully
# configured and run on demand (`--owner <key>`), but stay out of the unattended
# batch until one clean verified run proves their numbers.
#
# WHY THIS EXISTS (2026-08-01): reconciliation is all-or-nothing — ONE office
# whose computed churn doesn't match the CHURN RATES dashboard sets `problems`,
# and the run then writes NOTHING for ANY office. So a brand-new office joining
# the 4am batch un-verified can silently zero out Carlos's and Atef's boards
# too. Staging costs one flag; the alternative costs everyone's data.
#
# TO PROMOTE: run `--owner jamis --dry-run` on Lucy 2 (needs Carlos's Tableau
# session), confirm it reconciles, then delete the key from this set.
#
# EMPTY as of 2026-08-01: jamis promoted the same day. He cleared the bar this
# set exists for — a live `--owner jamis` run on Lucy 2 reconciled against the
# CHURN RATES dashboard and wrote his board (203/62/11 activations, 24 reps
# with 0-30 data), and reconcile_reps confirmed the per-rep rows sum to HIS
# office totals rather than the team's. He's in the nightly `--owner both`
# batch now. Keep the mechanism — the next office onboarded needs it.
STAGED: set = set()


def _activation_cfg():
    """Per-office activation-rates source for E5/F5 + the AE:AF rep list.
    key -> (view_url, custom_view_name, owner_prefix). Each office's server-side
    ACTIVATIONRATES saved view exposes ONLY its own reps on the 'Activation
    Office' worksheet — Carlos's CARLOSLOCALEXPANDED excludes Atef — so the view
    URL must be per office. The office-totals .csv is the bare dashboard export
    filtered in code by owner_prefix (same as Carlos always did)."""
    from automations.vantura_churn import activation_rates as _ar
    return {
        "carlos": (_ar.VIEW_URL, _ar.CUSTOM_VIEW, _ar.OWNER_PREFIX),
        # AtefEXP2 (Eve, 2026-08-19) — REPLACES AtefEXP (9cfd3e6c…), which
        # stopped exposing the 'Activation Office' worksheet and took the whole
        # run down with it. Note how this one is built: there is still NO Atef
        # filter in "B2B Captain's Teams (SFDC)", so Eve selected his sellers
        # as individual OWNERS. That means the "Owner & Office" values in this
        # export may be the REPS, not 'ATEF CHOUDHURY' — if the owner_prefix
        # below matches nothing, read `--dump-rep-grid atef` on the Vantura
        # Diag tab and set the prefix(es) to what the export actually says.
        "atef": ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                 "ATTTRACKER-B2B/ACTIVATIONRATES/"
                 "d30e7ebf-2f24-4c7f-9419-b2c713a50abb/AtefEXP2?:iid=1",
                 "Atef EXP 2", "ATEF CHOUDHURY"),
        # JAMIS — no Jamis-scoped saved view exists yet (his onboarding row has
        # per_office_views {}), and "Owner & Office" can NOT be URL-sliced, so
        # there is no way to hand Tableau an office-filtered view here. Use the
        # ALL-TEAM view and let the OWNER FILTER HAPPEN IN CODE: parse_rep_rates
        # and parse_rates both drop every row whose "Owner & Office" doesn't
        # start with the prefix, so isolation does not depend on the view. Two
        # guards back it: parse_rep_rates RAISES when the prefix matches no rows
        # (never silently posts the team), and reconcile_reps requires the rep
        # rows to add up to Jamis's own office totals.
        #
        # UNVERIFIED until a `--owner jamis --dry-run` on Lucy 2: whether this
        # team view exposes the 'Activation Office' worksheet the per-rep list
        # needs (Carlos's CARLOSLOCALEXPANDED was picked for exactly that). If
        # it doesn't, parse_rep_rates fails loudly naming the missing columns —
        # the fix is then Carlos saving a JamisEXPANDED view (add-b2b-office.md,
        # "What Carlos makes") and swapping the URL on this one line.
        "jamis": ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                  "ATTTRACKER-B2B/ACTIVATIONRATES/"
                  "3c5ad8dd-5c2b-43d1-96fe-63b945de10fb/"
                  "CarlosTeamViewExpanded?:iid=1",
                  "Carlos Team View Expanded", "JAMIS GARAY"),
    }


# Reconciliation tolerances (Megan 2026-07-19).
#
# The gate used to demand EXACT equality on the base. It can't: the Order Log
# is live while CHURN RATES refreshes on its own cycle, so the two disagree by
# a few records at any given moment. On 2026-07-19 the 7am run was blocked by a
# ONE-record race (base 390 vs 391, disconnects 14 vs 15) and wrote nothing —
# the board silently kept the previous day's numbers.
#
# So: keep the CHURN RATE tight (that's the number people read) and let the
# base drift within a band that still catches every structural failure.
#   wrong owner            base off ~70%   -> caught
#   truncated/empty pull   base off >30%   -> caught
#   refresh race           base off <5%    -> tolerated, and LOGGED
#
# This table used to claim "a product type dropped -> base off ~14% -> caught".
# It no longer holds and was corrected 2026-08-25: Wireless has grown to 88% of
# CARLOS's base, so losing Air (7%) or Internet (5%) now lands INSIDE the ±10%
# band. Only Wireless still breaks it alone. `_vanished_products` covers that
# gap against the tab's own previous numbers instead of against a percentage.
BASE_TOL_PCT = 0.10        # relative band on the dashboard's own base
BASE_TOL_MIN = 10          # absolute floor, so small bases aren't hair-trigger
RATE_TOL_PP = 0.005        # 0.5 percentage points on the churn rate


def _reconcile(who: str, summary: dict, dash: dict, log,
               prev_summary: dict | None = None,
               prev2_summary: dict | None = None) -> list[str]:
    """Compare computed 0-30 numbers to the Churn Rates dashboard.
    Returns a list of mismatch descriptions (empty = reconciled).

    `prev_summary` is the SAME Order Log summarised against YESTERDAY's 0-30
    window (cutoff one day earlier). When today's window doesn't reconcile but
    yesterday's does, the disagreement is CHURNRATES not having rolled its
    window forward yet — see _reconcile_stale_window. `prev2_summary` (two days
    back) is diagnostic only: it never rescues a run, it just says so in the
    failure text.
    """
    problems = _compare(who, summary, dash, log)
    if not problems:
        return problems
    return _reconcile_stale_window(who, summary, dash, log, problems,
                                   prev_summary, prev2_summary)


def _reconcile_stale_window(who: str, summary: dict, dash: dict, log,
                            problems: list[str],
                            prev_summary: dict | None,
                            prev2_summary: dict | None) -> list[str]:
    """Rescue the ONE disagreement that is the dashboard's fault, not ours.

    Every day the 0-30 window drops the accounts posted 31 days ago, and that
    cohort is the MATURE end of the list — it carries a disproportionate share
    of the disconnects. So the morning CHURNRATES hasn't rolled its window
    forward yet, the dashboard still counts that cohort and reads HIGHER than
    we do on both the base and (much more visibly) the rate.

    2026-08-25 is the exact shape: CARLOS computed 22/383 = 5.74%, dashboard
    391 / 6.40%. The three missing disconnects were NORBERTO P (Air), Baibhav G
    and Rajendra J (Internet) — all posted 7/25, all sitting at the top of the
    tab's own roll-off helper the day before, all correctly dropped by us and
    still counted by the dashboard. Re-summarising the same Order Log against
    YESTERDAY's cutoff gave 25/390 vs the dashboard's base 391 / 6.40% — a
    textbook reconciliation (measured, not predicted: that is the line this
    branch logged on the run that finally wrote the board). Our numbers were
    right and the gate blocked the write anyway, so the board sat on Sunday's
    figures until 07:14.

    The rescue is deliberately narrow: only ONE day back, and the shifted
    numbers must clear the SAME tolerances — a genuine structural break (wrong
    owner, a dropped product type, a truncated pull) misses by far too much for
    a one-day shift to close it. Today's FRESH numbers are what gets written;
    the D-1 view is only ever used to decide who is behind.
    """
    if prev_summary is not None and not _compare(who, prev_summary, dash,
                                                 lambda *a: None):
        rate = (summary["disc_total"] / summary["base_total"]
                if summary["base_total"] else 0.0)
        log(f"    ↳ {who}: today's window does NOT match the dashboard, but "
            f"YESTERDAY's does ({prev_summary['disc_total']}/"
            f"{prev_summary['base_total']} vs base={dash['base']}) — "
            "CHURNRATES has not rolled its 0-30 window forward yet. Writing "
            f"today's numbers ({summary['disc_total']}/{summary['base_total']}"
            f" = {rate:.2%}); the dashboard is the stale side.")
        return []
    if prev2_summary is not None and not _compare(who, prev2_summary, dash,
                                                  lambda *a: None):
        problems.append(
            f"{who}: the dashboard matches our TWO-day-old window, so "
            "CHURNRATES is ≥2 days behind — that is a CHURNRATES refresh "
            "problem, not an Order Log one. Not auto-tolerated: check the "
            "workbook's extract schedule before re-running.")
    return problems


# A product that still had this many active accounts yesterday cannot honestly
# reach zero overnight: the 0-30 base is a 30-day rolling population, so an
# office that stops selling something decays through 8, 5, 2, 1 over weeks. A
# clean drop to 0 from a real number is a LABEL problem, not a sales one.
VANISH_FLOOR = 5


def _vanished_products(who: str, bases: dict, prev_bases: dict,
                       log) -> list[str]:
    """Catch a product type that stopped being recognised, which the base band
    can no longer see.

    The tolerance table above claims "a product type dropped -> base off ~14%
    -> caught". That stopped being true as Wireless grew: Internet is 19 of
    CARLOS's 383 units (5%) and Air 28 (7%), so PRODUCT_MAP failing to match
    either — Tableau renaming 'NEW INTERNET', a stray suffix, a new casing —
    lands well inside the ±10% band and writes a quietly wrong board. Only
    Wireless (88%) still breaks the band on its own.

    So compare against what the tab ALREADY says instead of against a
    percentage. No baseline (fresh tab, unreadable box) = no opinion.
    """
    if not prev_bases:
        return []
    gone = [(p, prev_bases[p]) for p in sorted(bases)
            if bases.get(p, 0) == 0 and prev_bases.get(p, 0) >= VANISH_FLOOR]
    if not gone:
        return []
    for p, was in gone:
        log(f"  ✗ {who}: {p} computed 0 units, but the tab still shows {was} "
            "from the last run")
    return [f"{who}: {p} went from {was} active accounts to 0 in one run — "
            f"the Order Log almost certainly renamed the '{p}' product label "
            "(check PRODUCT_MAP against the crosstab's 'Product Type (Broken "
            "Out)' values); a real wind-down decays over weeks, it does not "
            "drop to zero" for p, was in gone]


def _compare(who: str, summary: dict, dash: dict, log) -> list[str]:
    """The tolerance check itself — computed vs dashboard, no interpretation.

    Drift inside tolerance is REPORTED, not hidden — a run that passes with a
    visible gap should still look different in the log from an exact match.
    """
    problems = []
    rate = (summary["disc_total"] / summary["base_total"]
            if summary["base_total"] else 0.0)
    if dash["rate"] is None and dash["base"] is None:
        log(f"  {who}: computed {summary['disc_total']}/"
            f"{summary['base_total']} — dashboard cell unreadable: "
            f"{dash['raw']}")
        problems.append(f"{who}: could not read the dashboard 0-30 cell "
                        f"(raw: {dash['raw']})")
        return problems

    dash_rate = "?" if dash["rate"] is None else f"{dash['rate']:.1%}"
    log(f"  {who}: computed {summary['disc_total']}/{summary['base_total']}"
        f" = {rate:.1%}   dashboard says base={dash['base']} "
        f"rate={dash_rate}")

    if dash["base"] is not None:
        gap = abs(summary["base_total"] - dash["base"])
        tol = max(BASE_TOL_MIN, dash["base"] * BASE_TOL_PCT)
        if gap > tol:
            problems.append(
                f"{who}: base {summary['base_total']} vs dashboard "
                f"{dash['base']} — off by {gap} (tolerance {tol:.0f})")
        elif gap:
            log(f"    ↳ base drift {gap} record(s) within tolerance "
                f"{tol:.0f} — the Order Log and the dashboard refresh "
                "independently")
    if dash["rate"] is not None:
        gap = abs(rate - dash["rate"])
        if gap > RATE_TOL_PP:
            problems.append(
                f"{who}: churn {rate:.2%} vs dashboard {dash['rate']:.2%} "
                f"— off by {gap * 100:.2f}pp (tolerance "
                f"{RATE_TOL_PP * 100:.2f}pp)")
        elif gap:
            log(f"    ↳ churn drift {gap * 100:.2f}pp within tolerance "
                f"{RATE_TOL_PP * 100:.2f}pp")
    return problems


CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
DIAG_TAB = "Vantura Diag"


def _write_diag(lines: list[str]) -> None:
    """Full probe output → a diag tab on the control sheet (the queue's
    Result cell truncates at ~480 chars; this is the readable channel)."""
    try:
        from automations.recruiting_report.fill import _client
        sh = _client().open_by_key(CONTROL_SHEET_ID)
        try:
            ws = sh.worksheet(DIAG_TAB)
        except Exception:
            ws = sh.add_worksheet(title=DIAG_TAB, rows=300, cols=2)
        ws.clear()
        ws.batch_update([{"range": f"A1:A{len(lines)}",
                          "values": [[l[:2000]] for l in lines]}])
    except Exception as e:  # noqa: BLE001 — diag must never mask the probe
        print(f"diag write failed: {e}", flush=True)


def _dump_rep_grid(today: dt.date, log, key: str = "carlos") -> int:
    """DIAG: download one office's 'Activation Office' per-rep crosstab + the
    office totals CSV and dump BOTH raw to the 'Vantura Diag' tab (readable from
    any machine). Read-only w.r.t. report data.

    Takes an office key (default carlos) because a RE-CREATED saved view has to
    be inspected before it can be trusted: the export's own "Owner & Office"
    values decide the owner_prefix in _activation_cfg(), and a view built from
    individually-selected sellers may not carry the owner's name at all. The
    distinct owner values are listed first, before the raw rows."""
    from pathlib import Path as _P
    import csv as _csv
    from automations.vantura_churn import cdp_pull, compute
    from automations.vantura_churn import activation_rates as _ar

    cfg = _activation_cfg()
    if key not in cfg:
        log(f"--dump-rep-grid: unknown office {key!r}; have "
            + ", ".join(sorted(cfg)))
        return 1
    view_url, _cv, own = cfg[key]
    rp = _P(f"/tmp/_dump_activation_office_{key}.csv")
    op = _P(f"/tmp/_dump_activation_office_totals_{key}.csv")
    lines: list[str] = [f"dump-rep-grid @ {dt.datetime.now().isoformat(timespec='seconds')}",
                        f"view_url={view_url}", f"owner_prefix={own!r}", ""]
    try:
        with cdp_pull._cdp_lock(label="vantura dump-rep-grid", log=log):
            cdp_pull.download_views([(view_url, _ar.REP_SHEET, rp)], today=today,
                                    verbose=False, log=log,
                                    csv_fetches=[(_ar.CSV_URL, op)])
        grid = compute._load_grid(rp)
        seen = []
        for r in grid[1:]:
            v = _ar._owner_name(r[0]) if r else ""
            if v and v not in seen:
                seen.append(v)
        lines.append(f"=== distinct col-1 values ({len(seen)}) — this is what "
                     f"owner_prefix has to match ===")
        lines += ["  " + v for v in seen[:60]]
        lines.append("")
        lines.append(f"=== '{_ar.REP_SHEET}' grid: {len(grid)} rows ===")
        for r in grid:
            lines.append(" | ".join("" if c is None else str(c) for c in r))
        lines.append("")
        with open(op, encoding="utf-8-sig", errors="replace") as fh:
            totals = list(_csv.reader(fh))
        lines.append(f"=== office totals CSV: {len(totals)} rows ===")
        for r in totals:
            joined = " | ".join(str(c) for c in r)
            if own.upper() in joined.upper() or r is totals[0]:
                lines.append(joined)
        if len(lines) and not any(own.upper() in ln.upper() for ln in lines):
            lines.append(f"(NO row of the totals CSV contains {own!r} — the "
                         "owner_prefix in _activation_cfg() is wrong for this "
                         "view; use one of the distinct values listed above.)")
    except Exception as e:  # noqa: BLE001
        import traceback
        lines.append(f"DUMP ERROR: {str(e)[:200]}")
        lines += ["  " + ln[:200] for ln in traceback.format_exc().splitlines()[-6:]]
    _write_diag(lines)
    log(f"dump-rep-grid: wrote {len(lines)} lines to '{DIAG_TAB}'")
    return 0


def _probe(today: dt.date, log) -> int:
    """CDP probe: download Carlos's Order Log crosstab via REAL Chrome (the
    patchright-proof path) and report row counts. Findings → the 'Vantura Diag' tab."""
    lines: list[str] = []

    def rec(s):
        log(s)
        lines.append(str(s))

    rec(f"cdp-probe @ {dt.datetime.now().isoformat(timespec='seconds')}")
    try:
        from automations.vantura_churn import cdp_pull
        out = Path("/tmp/vantura_probe_carlos.xlsx")
        with cdp_pull._cdp_lock(label="vantura probe", log=rec):
            info = cdp_pull.probe(pull.orderlog_url("carlos", today),
                                  pull.ORDERLOG_SHEET, out, today, log=rec)
        rec(f"RESULT: {info}")
    except Exception as e:  # noqa: BLE001
        import traceback
        rec(f"CDP PROBE ERROR: {str(e)[:200]}")
        for ln in traceback.format_exc().splitlines()[-6:]:
            rec("  " + ln[:200])
    _write_diag(lines)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="vantura_churn")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute + reconcile + print; write nothing")
    ap.add_argument("--probe", action="store_true",
                    help="diagnostics only: load the filtered Order Log view "
                         "and dump what it shows to the control sheet")
    ap.add_argument("--probe-activations-url", default=None, metavar="URL",
                    help="probe THIS activation-rates view instead of the "
                         "default (use to compare custom views).")
    ap.add_argument("--probe-activations", action="store_true",
                    help="diagnostics only: dump what the ACTIVATION RATES "
                         "view exports (columns, bucket captions, Carlos's "
                         "rows) to the 'Vantura Diag' tab. LUCY 2 ONLY.")
    ap.add_argument("--dump-rep-grid", nargs="?", const="carlos", default=None,
                    metavar="OFFICE",
                    help="diagnostics only: dump one office's full 'Activation "
                         "Office' per-rep grid + office totals to the 'Vantura "
                         "Diag' tab, distinct owner values first (that is what "
                         "verifies a re-created saved view). Defaults to "
                         "carlos. LUCY 2 ONLY.")
    # Choices come from OWNER_CFG so adding an office is ONE table row, not a
    # row plus a literal here that silently rejects the new key.
    ap.add_argument("--owner", choices=tuple(["both"] + [k for k, *_ in OWNER_CFG]),
                    default="both")
    ap.add_argument("--today", default=None,
                    help="override 'today' (YYYY-MM-DD) — testing only")
    ap.add_argument("--from-files", nargs="*", default=None, metavar="KEY=XLSX",
                    help="skip Tableau; use existing Order Log downloads, "
                         "e.g. carlos=/path/a.xlsx atef=/path/b.xlsx")
    ap.add_argument("--skip-reconcile", action="store_true",
                    help="skip the dashboard check (only sensible with "
                         "--from-files; a live run should never skip it)")
    ap.add_argument("--skip-activations", action="store_true")
    ap.add_argument("--skip-rates", action="store_true",
                    help="skip the activation-rate cells + per-rep list")
    ap.add_argument("--no-post", action="store_true",
                    help="render the screenshots but DON'T send them to Slack "
                         "(resolve + report the target only)")
    ap.add_argument("--skip-post", action="store_true",
                    help="skip the screenshot step entirely")
    ap.add_argument("--post-only", action="store_true",
                    help="skip the whole data pull/write; just render from the "
                         "current sheet and post to the B2B Quality thread "
                         "(also refreshes the thread header). LUCY 2 to post "
                         "as Lucy.")
    ap.add_argument("--theme", action="store_true",
                    help="restyle Carlos's churn tab (header, tiers chart, "
                         "filter control) and exit. Aesthetic only — NOT part "
                         "of the daily run, so manual highlights survive.")
    ap.add_argument("--carlos-only", action="store_true",
                    help="Carlos's churn tab only — skip Atef + Activations.")
    args = ap.parse_args(argv)

    log = lambda *a: print(*a, flush=True)  # noqa: E731
    today = (dt.date.fromisoformat(args.today) if args.today
             else dt.date.today())
    if args.probe:
        return _probe(today, log)
    if args.probe_activations:
        from automations.vantura_churn import cdp_pull
        with cdp_pull._cdp_lock(label="vantura activation-rates", log=log):
            cdp_pull.probe_activation_rates(log=log,
                                            view_url=args.probe_activations_url)
        return 0
    if args.dump_rep_grid:
        return _dump_rep_grid(today, log, args.dump_rep_grid)
    if args.theme:
        ws = fill.open_sheet().worksheet(fill.TAB_CHURN_CARLOS)
        fill.apply_theme(ws, log=log)
        return 0
    if args.post_only:
        # Render + post from the sheet AS-IS: no Tableau pull, no reconcile,
        # no write. For re-posting or fixing the thread header without a full
        # data run. Reflects whatever is currently on the tab.
        from automations.vantura_churn import shot as _shot
        ws = fill.open_sheet().worksheet(fill.TAB_CHURN_CARLOS)
        r = _shot.post_report(ws, day=today, dry_run=args.no_post, log=log)
        log(f"post-only result: {r}")
        return 0
    # `--owner both` = the promoted offices only; naming an office explicitly
    # always runs it (that's how a STAGED office gets its verification run).
    owners = [o for o in OWNER_CFG
              if (o[0] == args.owner
                  or (args.owner == "both" and o[0] not in STAGED))]
    staged_skipped = [o[0] for o in OWNER_CFG
                      if args.owner == "both" and o[0] in STAGED]
    if staged_skipped:
        log("STAGED (not in the daily batch): " + ", ".join(staged_skipped)
            + " — run `--owner <key> --dry-run` to verify, then clear STAGED.")
    if args.carlos_only:
        owners = [(k, prefix, sid, tab, False)
                  for k, prefix, sid, tab, _act in owners if k == "carlos"]
        if not owners:
            log("--carlos-only conflicts with "
                f"--owner {args.owner}; nothing to do.")
            return 1

    # ---------------------------------------------------------- downloads
    files: dict[str, Path] = {}
    churnrates_path = None
    # Activation rates now run per office (each with its own saved view).
    _act_cfg = _activation_cfg()
    rate_keys = ([] if args.skip_rates
                 else [k for k, *_ in owners if k in _act_cfg])
    ar_paths: dict = {}   # office key -> (reps_csv, office_totals_csv)
    rate_source_down: dict = {}   # office key -> why its rates didn't download
    if args.from_files:
        for spec in args.from_files:
            k, _, p = spec.partition("=")
            files[k] = Path(p)
        if not args.skip_reconcile:
            log("NOTE: --from-files without --skip-reconcile still pulls "
                "the Churn Rates dashboard from Tableau.")
    need_tableau = (set(k for k, *_ in owners) - set(files)) or \
                   (not args.skip_reconcile)
    if need_tableau:
        # Downloads run through REAL Chrome over CDP (cdp_pull): the B2B
        # ORDERLOG dashboard won't export under patchright's stealth Chromium.
        # One session downloads every owner's Order Log + the Churn Rates
        # crosstab. Fully isolated from resume_pushing (own profile/port).
        from automations.vantura_churn import cdp_pull
        out_dir = Path(tempfile.gettempdir()) / "vantura_churn"
        out_dir.mkdir(exist_ok=True)
        specs = []
        for key, *_ in owners:
            if key in files:
                continue
            p_out = out_dir / f"orderlog_{key}.xlsx"
            files[key] = p_out
            specs.append((pull.orderlog_url(key, today),
                          pull.ORDERLOG_SHEET, p_out))
            log(f"▶ Order Log ({key}, {today - dt.timedelta(days=60)}..{today})")
        if not args.skip_reconcile:
            churnrates_path = out_dir / "churnrates.xlsx"
            specs.append((pull.CHURNRATES_URL, pull.CHURNRATES_SHEET,
                          churnrates_path))
            log("▶ Churn Rates dashboard…")
        csv_fetches = []
        if rate_keys:
            from automations.vantura_churn import activation_rates as _ar
            for k in rate_keys:
                view_url, _cv, _own = _act_cfg[k]
                rp = out_dir / f"activation_office_{k}.csv"
                op = out_dir / f"activation_office_totals_{k}.csv"
                # optional=True: an office's activation view is worth CELLS
                # (E5/F5 + the AE:AF rep list), not the report. 2026-08-19 —
                # Atef's AtefEXP view stopped offering the 'Activation Office'
                # worksheet and the raise took CARLOS's and JAMIS's churn down
                # with it, though both Order Logs had already downloaded fine.
                specs.append((view_url, _ar.REP_SHEET, rp, True))
                csv_fetches.append((_ar.CSV_URL, op, True))
                ar_paths[k] = (rp, op)
                log(f"▶ Activation Rates ({k}: per-rep + office totals)…")
        dl_failures: dict = {}
        with cdp_pull._cdp_lock(label="vantura download_views", log=log):
            cdp_pull.download_views(specs, today=today, verbose=False, log=log,
                                    csv_fetches=csv_fetches,
                                    failures=dl_failures)
        # An office whose activation source didn't come through is dropped from
        # the rates pass entirely — half a pair (reps without office totals)
        # can't be reconciled, and reconcile_reps would report it as a data
        # problem, which would then block the churn write for EVERY office.
        for k in list(ar_paths):
            rp, op = ar_paths[k]
            why = dl_failures.get(str(rp)) or dl_failures.get(str(op))
            if why:
                rate_source_down[k] = why
                ar_paths.pop(k)
                log(f"  ⚠ activation rates ({k}) SKIPPED — {why[:160]}")

    # ------------------------------------------------- compute + reconcile
    results = {}
    problems: list[str] = []
    for key, prefix, _sid, tab, _has_act in owners:
        lines = compute.load_orderlog(files[key], prefix)
        summary = compute.churn_summary(lines, today)
        results[key] = {
            "lines": lines, "summary": summary,
            "helper": compute.helper_block(lines, today),
        }
        b, d = summary["base"], summary["disc"]
        log(f"{key.upper()}: bases W/A/I = {b['Wireless']}/{b['Air']}/"
            f"{b['Internet']}  disconnects = {d['Wireless']}/{d['Air']}/"
            f"{d['Internet']}  ({summary['disc_total']}/"
            f"{summary['base_total']})")
        if not args.skip_reconcile:
            dash = pull.parse_churnrates(churnrates_path, prefix)
            # Same Order Log, older 0-30 cutoffs: what the dashboard would say
            # if it were a day (or two) behind on rolling its window forward.
            # Only used to decide WHO is stale — never written.
            problems += _reconcile(
                key.upper(), summary, dash, log,
                prev_summary=compute.churn_summary(
                    lines, today - dt.timedelta(days=1)),
                prev2_summary=compute.churn_summary(
                    lines, today - dt.timedelta(days=2)))

    # ------------------------------------------- activation rates (per office)
    rates_by_office: dict = {}
    if ar_paths:
        import csv as _csv
        from automations.vantura_churn import activation_rates as _ar
        for k, (rp, op) in ar_paths.items():
            _vu, _cv, own = _act_cfg[k]
            # Parsing is inside the try for the same reason the download is:
            # parse_rates/parse_rep_rates RAISE when the owner prefix matches no
            # row (a re-created saved view can come back shaped differently —
            # AtefEXP2 is built from individually-selected sellers). That raise
            # used to escape main() and cost every office its churn write.
            try:
                with open(op, encoding="utf-8-sig", errors="replace") as fh:
                    office = _ar.parse_rates(list(_csv.reader(fh)),
                                             owner_prefix=own)
                reps = _ar.parse_rep_rates(compute._load_grid(rp),
                                           owner_prefix=own)
            except Exception as e:  # noqa: BLE001 — rates cost cells, not the run
                rate_source_down[k] = f"{type(e).__name__}: {str(e)[:200]}"
                log(f"  ⚠ activation rates ({k}) UNUSABLE — {e}")
                continue
            # The per-rep split is only trustworthy if it adds back up to the
            # office numbers — same contract as the churn reconciliation above.
            rate_problems = _ar.reconcile_reps(reps, office)
            o30, o60 = office["0-30"], office["31-60"]
            log(f"RATES ({k}): 0-30 {o30['activated']}/{o30['sold']} = "
                f"{o30['rate']:.1%}   31-60 {o60['activated']}/{o60['sold']} = "
                f"{o60['rate']:.1%}   ({len(reps)} reps)")
            if rate_problems:
                # NOT `problems`: that list aborts the whole run before ANY
                # write, and one office's rep/office mismatch is not a reason to
                # leave three churn tabs stale. It rides the source ping with
                # the rest, and the office simply keeps yesterday's rate cells.
                rate_source_down[k] = "; ".join(rate_problems)[:300]
                log(f"  ⚠ activation rates ({k}) DON'T RECONCILE — "
                    + "; ".join(rate_problems))
            else:
                rates_by_office[k] = (office, reps)

    if problems:
        return _abort(problems,
                      "Computed churn numbers do not match the Churn Rates "
                      "dashboard: " + "; ".join(problems), log, args.dry_run)

    if args.dry_run:
        for key, *_ in owners:
            log(f"\n[dry-run] {key} helper block "
                f"({len(results[key]['helper'])} rows):")
            for r in results[key]["helper"]:
                log("   " + " | ".join("" if v is None else str(v)
                                       for v in r))
        log("\n[dry-run] no writes performed.")
        return 0

    # ------------------------------------ resolve the tabs + structural check
    # Resolve every office's tab BEFORE writing any of them, and read back the
    # numbers already on it. Reconciliation is deliberately all-or-nothing (see
    # STAGED); a check that only fired on office #3 would leave #1 and #2
    # written and #3 stale — the split state the all-or-nothing rule exists to
    # prevent. The handles are reused below, so this costs no extra lookups.
    sheets = {}                 # office key -> (spreadsheet, worksheet)
    for key, prefix, sid, tab, has_act in owners:
        sh = fill.open_sheet(sid)   # each office writes its OWN board
        # Resolve the tab ONCE, case-tolerantly (a hand-duplicated board spells
        # it 'Lucy Churn', not 'LUCY CHURN' — Jamis, 2026-08-01), and reuse the
        # handle: 4 lookups per office was also 4 Sheets calls per office.
        ws = _fill_shared.worksheet_ci(sh, tab)
        sheets[key] = (sh, ws)
        problems += _vanished_products(key.upper(),
                                       results[key]["summary"]["base"],
                                       fill.read_product_bases(ws, log=log),
                                       log)
    if problems:
        return _abort(problems,
                      "A product type stopped being recognised, so nothing was "
                      "written: " + "; ".join(problems), log, args.dry_run)

    # ------------------------------------------------------------- writes
    churn_ws = {}               # office key -> its resolved churn worksheet
    act_problems: list = []     # offices whose activations tab couldn't be written
    for key, prefix, sid, tab, has_act in owners:
        sh, ws = sheets[key]
        churn_ws[key] = ws
        log(f"▶ updating '{ws.title}' on sheet {sid[:8]}…")
        # Self-heal the 'Viewing:' dropdown: editing the tab's headers can
        # leave the validation on one cell and the FILTER reading another,
        # which silently breaks product switching. No-op when they agree.
        try:
            fill.repair_viewing_dropdown(ws, log=log)
        except Exception as e:  # noqa: BLE001 — never block the daily write
            log(f"  ⚠ dropdown check skipped: {e}")
        # A duplicated churn tab doesn't inherit the hidden helper columns,
        # so R:AE sit in plain view next to the report. No-op once hidden.
        try:
            fill.hide_helper_columns(ws, log=log)
        except Exception as e:  # noqa: BLE001
            log(f"  ⚠ helper-column hide skipped: {e}")
        fill.update_churn_tab(ws, results[key]["summary"]["base"],
                              results[key]["helper"], log=log)
        if rates_by_office.get(key):
            office, reps = rates_by_office[key]
            fill.update_activation_rates(ws, office, reps, log=log)
        if has_act and not args.skip_activations:
            log(f"▶ updating '{fill.TAB_ACTIVATIONS}'…")
            # The activations half must NOT be able to undo the churn half.
            # 2026-08-15: the tab was gone from Carlos's board and the bare
            # sh.worksheet() lookup raised WorksheetNotFound out of main() —
            # exit 1, no manifest, no Slack post, even though LUCY CHURN had
            # already been written correctly seconds earlier. Resolve the tab
            # by content (fill.activations_worksheet), and on failure record
            # it and carry on: the run finishes and reports activations as the
            # one broken piece.
            try:
                act_ws = fill.activations_worksheet(sh, log=log)
                act = compute.activations_rows(results[key]["lines"], today)
                fill.update_activations(act_ws, act, log=log)
            except Exception as e:  # noqa: BLE001 — churn already landed
                log(f"  ✗ activations NOT updated ({key}): {e}")
                act_problems.append(f"{key} — {e}")

    # ---------------------------------------------------- screenshot → Slack
    # Runs ONLY after the write above succeeds, so a stale/half-written board
    # is never posted. Replies the churn overview + rep breakdown into that
    # day's 'B2B Quality & Bonus' thread (Carlos's ask, Megan approved
    # 2026-07-20). Posting is LIVE by default in a full run; --no-post or
    # --dry-run holds it. Best-effort: a Slack hiccup must not fail a run that
    # already wrote the board correctly.
    if not args.skip_post:
        # CARLOS'S OWN worksheet — churn_ws[key], never `sh`. `sh` is whatever
        # board the write loop happened to end on, and every office board has a
        # churn tab by the same name, so `sh.worksheet(carlos_tab)` posted the
        # LAST office's tab into Carlos's thread (it was reading ATEF's board;
        # found 2026-08-01). Exactly the isolation failure that halted the jamis
        # trackers a day earlier — one office's numbers under another's name.
        carlos_ws = churn_ws.get("carlos")
        if carlos_ws:
            try:
                from automations.vantura_churn import shot as _shot
                _shot.post_report(carlos_ws, day=today,
                                  dry_run=args.dry_run or args.no_post,
                                  log=log)
            except Exception as e:  # noqa: BLE001 — never fail a good write
                log(f"  ⚠ screenshot post skipped: {e}")

    # ------------------------------------------------- partial-failure report
    # Churn wrote, activations didn't. Loud, not silent: the board looks fine
    # to anyone reading it, so nothing but a red manifest + an email tells
    # Megan that half the report is stale.
    if act_problems:
        log("\n✗ CHURN WROTE, ACTIVATIONS DID NOT:")
        for p in act_problems:
            log(f"   {p}")
        detail = ("Churn tabs updated normally, but the activations tab "
                  "could not be written: " + "; ".join(act_problems))
        _act_fail_manifest(detail)
        if not args.dry_run:
            _email_failure(detail, log=log)
        return 3

    # --------------------------------------- activation source down (a PING)
    # Eve's rule: a dead source that costs CELLS pings by manifest kind="source"
    # and the step still exits 0. Its OWN manifest id, never REPORT_ID — the
    # _ok_manifest() below marks that one clean and would erase this notice.
    # need_tableau guard: with --from-files and no reconcile nothing was
    # pulled at all, so neither a ping nor a clean-close would mean anything.
    if rate_keys and need_tableau and not args.dry_run:
        _rate_source_manifest(rate_source_down, log=log)

    _ok_manifest()
    log("✓ Vantura churn & activations update complete.")
    if rate_source_down:
        log("  ⚠ activation rates NOT refreshed for: "
            + ", ".join(sorted(rate_source_down))
            + " — those cells are stale, not wrong.")
    return 0


# Megan + the reporting inbox only — Raf is deliberately NOT on this
# (Megan 2026-07-20). Address confirmed 1191 (not 1119).
FAILURE_TO = ["Meganhidalgo1191@gmail.com", "alphaletereporting@gmail.com"]


def _email_failure(msg: str, log=print) -> None:
    """Email on a blocked/failed run — ALWAYS on (Megan 2026-07-19).

    This job runs on its own LaunchAgent, outside the 4am batch, and its
    wrapper exits 0 so launchd never flags it. Before this, a reconciliation
    failure wrote nothing and said nothing: the board just kept yesterday's
    numbers and looked fine. That is exactly how 2026-07-19 went unnoticed.

    Best-effort — a mail problem must never mask the underlying failure.
    """
    try:
        import socket
        from email.message import EmailMessage
        from automations.day_orchestrator.notify import _send_email
        host = socket.gethostname()
        when = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        subject = f"❌ Vantura Churn & Activations did NOT write ({when})"
        text = (
            f"The Vantura churn refresh ran on {host} at {when} and wrote "
            f"NOTHING.\n\n{msg}\n\n"
            "The board still shows the PREVIOUS successful run's numbers — "
            "it is stale, not wrong.\n\n"
            "DON'T just re-run and expect it to clear. The gate already "
            f"tolerates normal refresh drift (base +/-{BASE_TOL_PCT:.0%}, "
            f"churn +/-{RATE_TOL_PP * 100:.1f}pp), so getting here means the "
            "Order Log and the CHURN RATES dashboard genuinely disagree by "
            "more than that.\n\n"
            "Check, in order:\n"
            "  1. Did the Order Log pull apply the owner filter and the "
            "60-day window? A short or wrong-owner pull is the usual cause.\n"
            "  2. Has CHURNRATES finished refreshing? Compare its 0-30 "
            "'Activated SPE/SP' against the numbers above.\n"
            "  3. Only then re-run:  lucy rerun vantura_churn "
            "--machine \"Lucy 2\"\n"
        )
        html = ("<p><b>The Vantura churn refresh wrote NOTHING.</b></p>"
                f"<p>{host} &middot; {when}</p>"
                f"<pre style='background:#f6f6f6;padding:10px'>{msg}</pre>"
                "<p>The board still shows the previous successful run's "
                "numbers &mdash; <b>stale, not wrong</b>.</p>"
                "<p><b>Don't just re-run.</b> The gate already tolerates "
                f"normal refresh drift (base &plusmn;{BASE_TOL_PCT:.0%}, "
                f"churn &plusmn;{RATE_TOL_PP * 100:.1f}pp), so this is a real "
                "divergence. Check the Order Log pull (owner filter? 60-day "
                "window?) and whether CHURNRATES has finished refreshing, "
                "then:<br><code>lucy rerun vantura_churn --machine "
                "\"Lucy 2\"</code></p>")
        _send_email(subject, html, text, FAILURE_TO, False, "vantura-churn-fail")
    except Exception as e:  # noqa: BLE001 — never mask the real failure
        log(f"  ⚠ failure email not sent: {e}")


def _abort(problems: list[str], detail: str, log, dry_run: bool) -> int:
    """One exit for every "we will not write" verdict: log the reasons, record
    the manifest, mail it, exit 2. Shared so the structural check can't drift
    into a quieter failure than the reconciliation one."""
    log("\n✗ NOTHING WRITTEN:")
    for p in problems:
        log(f"   {p}")
    _fail_manifest(detail)
    if not dry_run:
        _email_failure(detail, log=log)
    return 2


def _fail_manifest(msg: str) -> None:
    try:
        from automations.shared import run_manifest as _rm
        _rm.write_manifest(
            REPORT_ID, failed=["vantura_churn"], kind="report", note=msg,
            remediation=_rm.make_remediation(
                reason=msg,
                fix=f"A re-run probably will NOT clear this. The gate already "
                    f"tolerates normal refresh drift (base ±{BASE_TOL_PCT:.0%},"
                    f" churn ±{RATE_TOL_PP * 100:.1f}pp) AND a CHURNRATES that "
                    "is one day behind on rolling its 0-30 window forward "
                    "(the common morning race — it makes the dashboard read "
                    "high because the cohort about to roll off carries most of "
                    "the disconnects). Reaching here means neither explains "
                    "it. Read the lines above this one: '≥2 days behind' is a "
                    "CHURNRATES extract problem, not ours — check the "
                    "workbook's refresh schedule. Otherwise check the Order "
                    "Log pull (owner filter applied? 60-day window? a product "
                    "type Tableau renamed?) and compare the dashboard's 0-30 "
                    "'Activated SPE/SP' with the computed base. The board is "
                    "stale, not wrong, meanwhile.",
                link="https://us-east-1.online.tableau.com/#/site/sci/views/"
                     "ATTTRACKER-B2B/CHURNRATES",
                message="Vantura churn update stopped before writing — "
                        "computed numbers didn't match the Churn Rates "
                        "dashboard."))
    except Exception:
        pass


def _act_fail_manifest(msg: str) -> None:
    """Half-failure: churn is current, activations is stale.

    Deliberately a different message from _fail_manifest — that one means
    NOTHING was written and the board is stale in full. Here the churn tabs
    are today's and only the activations tab is behind, and the fix is on the
    Sheet (restore/rename a tab), not in a re-run.
    """
    try:
        from automations.shared import run_manifest as _rm
        _rm.write_manifest(
            REPORT_ID, failed=["vantura_churn"], kind="report", note=msg,
            remediation=_rm.make_remediation(
                reason=msg,
                fix="The churn tabs ARE today's — only activations is stale. "
                    f"The run looks for a tab named '{fill.TAB_ACTIVATIONS}' "
                    "(any casing/spacing), then any tab with 'activation' in "
                    "its name, then a tab whose header row is Rep / Customer "
                    "Name / Total Apps / DTR Status / … — so a rename is "
                    "handled automatically and reaching here means the tab is "
                    "GONE. Restore it on the Vantura Master Sales Board with "
                    "File ▸ Version history ▸ Restore (or undelete the tab), "
                    f"or rename the replacement back to "
                    f"'{fill.TAB_ACTIVATIONS}'. Then re-run — a re-run alone "
                    "will not fix it.",
                link="https://docs.google.com/spreadsheets/d/"
                     f"{fill.SHEET_ID}/edit",
                message="Vantura churn wrote fine, but the Activations tab is "
                        "missing from the Master Sales Board — that half of "
                        "the report is stale."))
    except Exception:
        pass


RATES_SOURCE_ID = "vantura_churn_activation_rates"


def _rate_source_manifest(down: dict, log=print) -> None:
    """Ping (or clear) the activation-rates source notice.

    Separate from the report manifest on purpose: the churn half wrote fine, so
    the Hub card stays GREEN and the report is not "failed" — but the office's
    activation cells are stale and somebody has to know. A clean run closes the
    incident by itself (mark_clean), so nothing has to remember to."""
    try:
        from automations.shared import run_manifest as _rm
        if not down:
            _rm.mark_clean(RATES_SOURCE_ID, kind="source")
            return
        who = ", ".join(sorted(down))
        _rm.write_manifest(
            RATES_SOURCE_ID, failed=sorted(down), kind="source",
            note=("Activation rates did not download for: " + who + ". Their "
                  "churn tabs ARE today's — only the activation cells (E5/F5 "
                  "and the per-rep list) are stale."),
            remediation=_rm.make_remediation(
                reason="; ".join(f"{k}: {v[:160]}" for k, v in sorted(down.items())),
                fix="A re-run will NOT fix a missing worksheet. In ATT TRACKER "
                    "- B2B / ACTIVATION RATES, open that office's saved view "
                    "and check it still shows the 'Activation Office' "
                    "worksheet: a workbook republish breaks saved views and "
                    "Tableau then falls back to the default dashboard, which "
                    "only has 'Activation Total' + 'zzz Last Refresh'. Have "
                    "the view re-created (as Rafael) and update its GUID URL "
                    "in `_activation_cfg()` in automations/vantura_churn/"
                    "run.py. Re-run after that.",
                link="https://us-east-1.online.tableau.com/#/site/sci/views/"
                     "ATTTRACKER-B2B/ACTIVATIONRATES",
                message="Vantura churn wrote fine, but the activation rates "
                        "for " + who + " couldn't be pulled — those cells are "
                        "stale."))
    except Exception as e:  # noqa: BLE001 — alerting never breaks a good run
        log(f"  ⚠ couldn't record the activation-source manifest "
            f"({type(e).__name__}: {str(e)[:120]})")


def _ok_manifest() -> None:
    try:
        from automations.shared import run_manifest as _rm
        _rm.write_manifest(REPORT_ID, kind="report", ok=True,
                           note="Churn + Activations reconciled and written.")
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
