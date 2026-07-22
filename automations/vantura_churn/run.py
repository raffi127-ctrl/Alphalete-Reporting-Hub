"""Vantura Master Sales Board — daily churn & activations update.

Flow (runbook 2026-07-13): pull each owner's 60-day Order Log + the Churn
Rates dashboard from Tableau → compute 0-30 bases/disconnects → RECONCILE
against the dashboard's 0-30 cell → only then write the live sheet
(Carlos: 'LUCY CHURN' + Activations tabs; Atef: Churn - Atef). If the derived
numbers don't match the dashboard, nothing is written and the run fails
loudly — that reconciliation is the whole safety story.

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

from automations.vantura_churn import compute, fill, pull

REPORT_ID = "vantura-churn"

# Atef's own board (Domin8) — his LUCY CHURN tab lives here, NOT on Carlos's
# sheet. Was writing to a "Churn - Atef" tab on Carlos's board (fill.SHEET_ID);
# 2026-07-21 each office now writes its OWN sheet's LUCY CHURN tab.
ATEF_SHEET_ID = "15YUHkAcG2AfiF6KRhCiOBKGDdS9nnjxdfvIXr7oRX30"

OWNER_CFG = [
    # (key, owner-name prefix in the crosstab, sheet id, churn tab, has-activations)
    ("carlos", "CARLOS HIDALGO", fill.SHEET_ID, fill.TAB_CHURN_CARLOS, True),
    ("atef", "ATEF CHOUDHURY", ATEF_SHEET_ID, "LUCY CHURN", False),
]


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
#   a product type dropped base off ~14%   -> caught
#   truncated/empty pull   base off >30%   -> caught
#   refresh race           base off <5%    -> tolerated, and LOGGED
BASE_TOL_PCT = 0.10        # relative band on the dashboard's own base
BASE_TOL_MIN = 10          # absolute floor, so small bases aren't hair-trigger
RATE_TOL_PP = 0.005        # 0.5 percentage points on the churn rate


def _reconcile(who: str, summary: dict, dash: dict, log) -> list[str]:
    """Compare computed 0-30 numbers to the Churn Rates dashboard.
    Returns a list of mismatch descriptions (empty = reconciled).

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
    ap.add_argument("--owner", choices=("both", "carlos", "atef"),
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
        cdp_pull.probe_activation_rates(log=log,
                                        view_url=args.probe_activations_url)
        return 0
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
    owners = [o for o in OWNER_CFG
              if args.owner in ("both", o[0])]
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
    ar_reps_path = ar_office_path = None
    # Activation rates are Carlos's ask and live on his tab only.
    want_rates = (not args.skip_rates
                  and any(k == "carlos" for k, *_ in owners))
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
        if want_rates:
            from automations.vantura_churn import activation_rates as _ar
            ar_reps_path = out_dir / "activation_office.csv"
            ar_office_path = out_dir / "activation_office_totals.csv"
            specs.append((_ar.VIEW_URL, _ar.REP_SHEET, ar_reps_path))
            csv_fetches.append((_ar.CSV_URL, ar_office_path))
            log("▶ Activation Rates (per-rep + office totals)…")
        cdp_pull.download_views(specs, today=today, verbose=False, log=log,
                                csv_fetches=csv_fetches)

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
            problems += _reconcile(key.upper(), summary, dash, log)

    # ------------------------------------------- activation rates (Carlos)
    rates = None
    if want_rates and ar_reps_path and ar_office_path:
        import csv as _csv
        from automations.vantura_churn import activation_rates as _ar
        with open(ar_office_path, encoding="utf-8-sig", errors="replace") as fh:
            office = _ar.parse_rates(list(_csv.reader(fh)))
        reps = _ar.parse_rep_rates(compute._load_grid(ar_reps_path))
        # The per-rep split is only trustworthy if it adds back up to the
        # office numbers — same contract as the churn reconciliation above.
        rate_problems = _ar.reconcile_reps(reps, office)
        o30, o60 = office["0-30"], office["31-60"]
        log(f"RATES: 0-30 {o30['activated']}/{o30['sold']} = "
            f"{o30['rate']:.1%}   31-60 {o60['activated']}/{o60['sold']} = "
            f"{o60['rate']:.1%}   ({len(reps)} reps)")
        if rate_problems:
            problems += [f"activation rates — {p}" for p in rate_problems]
        else:
            rates = (office, reps)

    if problems:
        log("\n✗ RECONCILIATION FAILED — NOTHING WRITTEN:")
        for p in problems:
            log(f"   {p}")
        detail = ("Computed churn numbers do not match the Churn Rates "
                  "dashboard: " + "; ".join(problems))
        _fail_manifest(detail)
        if not args.dry_run:
            _email_failure(detail, log=log)
        return 2

    if args.dry_run:
        for key, *_ in owners:
            log(f"\n[dry-run] {key} helper block "
                f"({len(results[key]['helper'])} rows):")
            for r in results[key]["helper"]:
                log("   " + " | ".join("" if v is None else str(v)
                                       for v in r))
        log("\n[dry-run] no writes performed.")
        return 0

    # ------------------------------------------------------------- writes
    for key, prefix, sid, tab, has_act in owners:
        sh = fill.open_sheet(sid)   # each office writes its OWN board
        log(f"▶ updating '{tab}' on sheet {sid[:8]}…")
        # Self-heal the 'Viewing:' dropdown: editing the tab's headers can
        # leave the validation on one cell and the FILTER reading another,
        # which silently breaks product switching. No-op when they agree.
        try:
            fill.repair_viewing_dropdown(sh.worksheet(tab), log=log)
        except Exception as e:  # noqa: BLE001 — never block the daily write
            log(f"  ⚠ dropdown check skipped: {e}")
        # A duplicated churn tab doesn't inherit the hidden helper columns,
        # so R:AE sit in plain view next to the report. No-op once hidden.
        try:
            fill.hide_helper_columns(sh.worksheet(tab), log=log)
        except Exception as e:  # noqa: BLE001
            log(f"  ⚠ helper-column hide skipped: {e}")
        fill.update_churn_tab(sh.worksheet(tab), results[key]["summary"]["base"],
                              results[key]["helper"], log=log)
        if key == "carlos" and rates is not None:
            fill.update_activation_rates(sh.worksheet(tab), rates[0],
                                         rates[1], log=log)
        if has_act and not args.skip_activations:
            log(f"▶ updating '{fill.TAB_ACTIVATIONS}'…")
            act = compute.activations_rows(results[key]["lines"], today)
            fill.update_activations(sh.worksheet(fill.TAB_ACTIVATIONS), act,
                                    log=log)

    # ---------------------------------------------------- screenshot → Slack
    # Runs ONLY after the write above succeeds, so a stale/half-written board
    # is never posted. Replies the churn overview + rep breakdown into that
    # day's 'B2B Quality & Bonus' thread (Carlos's ask, Megan approved
    # 2026-07-20). Posting is LIVE by default in a full run; --no-post or
    # --dry-run holds it. Best-effort: a Slack hiccup must not fail a run that
    # already wrote the board correctly.
    if not args.skip_post:
        carlos_tab = next((t for k, _p, _s, t, _a in owners if k == "carlos"),
                          None)
        if carlos_tab:
            try:
                from automations.vantura_churn import shot as _shot
                _shot.post_report(sh.worksheet(carlos_tab), day=today,
                                  dry_run=args.dry_run or args.no_post,
                                  log=log)
            except Exception as e:  # noqa: BLE001 — never fail a good write
                log(f"  ⚠ screenshot post skipped: {e}")

    _ok_manifest()
    log("✓ Vantura churn & activations update complete.")
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


def _fail_manifest(msg: str) -> None:
    try:
        from automations.shared import run_manifest as _rm
        _rm.write_manifest(
            REPORT_ID, failed=["vantura_churn"], kind="report", note=msg,
            remediation=_rm.make_remediation(
                reason=msg,
                fix=f"A re-run probably will NOT clear this. The gate already "
                    f"tolerates normal refresh drift (base ±{BASE_TOL_PCT:.0%},"
                    f" churn ±{RATE_TOL_PP * 100:.1f}pp), so reaching here "
                    "means the Order Log and the CHURN RATES dashboard "
                    "genuinely disagree by more than that. Check the Order Log "
                    "pull first (owner filter applied? 60-day window?), then "
                    "whether CHURNRATES has finished refreshing — compare its "
                    "0-30 'Activated SPE/SP' with the computed base. Re-run "
                    "only after one of those explains the gap. The board is "
                    "stale, not wrong, meanwhile.",
                link="https://us-east-1.online.tableau.com/#/site/sci/views/"
                     "ATTTRACKER-B2B/CHURNRATES",
                message="Vantura churn update stopped before writing — "
                        "computed numbers didn't match the Churn Rates "
                        "dashboard."))
    except Exception:
        pass


def _ok_manifest() -> None:
    try:
        from automations.shared import run_manifest as _rm
        _rm.write_manifest(REPORT_ID, kind="report", ok=True,
                           note="Churn + Activations reconciled and written.")
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
