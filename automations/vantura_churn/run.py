"""Vantura Master Sales Board — daily churn & activations update.

Flow (runbook 2026-07-13): pull each owner's 60-day Order Log + the Churn
Rates dashboard from Tableau → compute 0-30 bases/disconnects → RECONCILE
against the dashboard's 0-30 cell → only then write the live sheet
(Carlos: Churn + Activations tabs; Atef: Churn - Atef). If the derived
numbers don't match the dashboard, nothing is written and the run fails
loudly — that reconciliation is the whole safety story.

  python -m automations.vantura_churn.run                # full daily run
  python -m automations.vantura_churn.run --dry-run      # compute + print only
  python -m automations.vantura_churn.run --owner carlos
  python -m automations.vantura_churn.run --from-files carlos=/path/a.xlsx atef=/path/b.xlsx
  python -m automations.vantura_churn.run --skip-reconcile   # only with --from-files
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path

from automations.vantura_churn import compute, fill, pull

REPORT_ID = "vantura-churn"

OWNER_CFG = [
    # (key, owner-name prefix in the crosstab, churn tab, has activations tab)
    ("carlos", "CARLOS HIDALGO", fill.TAB_CHURN_CARLOS, True),
    ("atef", "ATEF CHOUDHURY", fill.TAB_CHURN_ATEF, False),
]


def _reconcile(who: str, summary: dict, dash: dict, log) -> list[str]:
    """Compare computed 0-30 numbers to the Churn Rates dashboard.
    Returns a list of mismatch descriptions (empty = reconciled)."""
    problems = []
    rate = (summary["disc_total"] / summary["base_total"]
            if summary["base_total"] else 0.0)
    log(f"  {who}: computed {summary['disc_total']}/{summary['base_total']}"
        f" = {rate:.1%}   dashboard says base={dash['base']}"
        f" rate={dash['rate']:.1%}" if dash["rate"] is not None else
        f"  {who}: computed {summary['disc_total']}/{summary['base_total']}"
        f" — dashboard cell unreadable: {dash['raw']}")
    if dash["base"] is not None and dash["base"] != summary["base_total"]:
        problems.append(f"{who}: base {summary['base_total']} != dashboard "
                        f"{dash['base']}")
    if dash["rate"] is not None and abs(rate - dash["rate"]) > 0.0015:
        problems.append(f"{who}: churn {rate:.2%} != dashboard "
                        f"{dash['rate']:.2%}")
    if dash["base"] is None and dash["rate"] is None:
        problems.append(f"{who}: could not read the dashboard 0-30 cell "
                        f"(raw: {dash['raw']})")
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
    ap.add_argument("--shot", action="store_true",
                    help="render the churn block to a PNG in output/ after "
                         "the write")
    ap.add_argument("--post", action="store_true",
                    help="with --shot, POST the PNG to the Activations "
                         "order-log channel. Off by default.")
    ap.add_argument("--preview", action="store_true",
                    help="write Carlos's churn numbers to the '"
                         + fill.TAB_CHURN_PREVIEW + "' tab instead of the "
                         "live one, and skip Atef + Activations. Use while "
                         "building the 2026-07-19 rebuild.")
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
    owners = [o for o in OWNER_CFG
              if args.owner in ("both", o[0])]
    if args.preview:
        # Preview run: Carlos only, onto his duplicate tab, no Activations.
        # The live 'Churn' tab and the daily job are left completely alone.
        owners = [(k, prefix, fill.TAB_CHURN_PREVIEW, False)
                  for k, prefix, _tab, _act in owners if k == "carlos"]
        if not owners:
            log("--preview is Carlos-only; nothing to do for "
                f"--owner {args.owner}.")
            return 1
        log(f"PREVIEW MODE → writing '{fill.TAB_CHURN_PREVIEW}' "
            "(live 'Churn' untouched)")

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
    for key, prefix, tab, _has_act in owners:
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
        _fail_manifest("Computed churn numbers do not match the Churn Rates "
                       "dashboard: " + "; ".join(problems))
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
    sh = fill.open_sheet()
    for key, prefix, tab, has_act in owners:
        log(f"▶ updating '{tab}'…")
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

    # ------------------------------------------------------------ screenshot
    if args.shot:
        from pathlib import Path as _P
        from automations.vantura_churn import shot as _shot
        carlos_tab = next((t for k, _p, t, _a in owners if k == "carlos"),
                          None)
        if carlos_tab:
            ws = sh.worksheet(carlos_tab)
            out = _P("output/vantura_churn") / f"churn-{today.isoformat()}.png"
            png = _shot.render_report(ws, out, log=log)
            log(f"  ✓ screenshot → {png}")
            # dry_run unless --post: posting outward is opt-in, never a
            # side effect of the daily refresh.
            _shot.post(png, day=today, dry_run=not args.post, log=log)

    _ok_manifest()
    log("✓ Vantura churn & activations update complete.")
    return 0


def _fail_manifest(msg: str) -> None:
    try:
        from automations.shared import run_manifest as _rm
        _rm.write_manifest(
            REPORT_ID, failed=["vantura_churn"], kind="report", note=msg,
            remediation=_rm.make_remediation(
                reason=msg,
                fix="Usually a stale Tableau load or the Order Log and the "
                    "dashboard refreshing seconds apart — a re-run normally "
                    "clears it. If it persists, the runbook's math and the "
                    "dashboard genuinely disagree: check the Order Log pull "
                    "(owner filter applied? 60-day window?) before touching "
                    "the sheet by hand.",
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
