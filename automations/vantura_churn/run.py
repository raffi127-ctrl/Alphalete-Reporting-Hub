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
    """Read-only look at the filtered ORDERLOG view on this machine: does the
    URL-param filtering (dates + owner) actually apply, and what does the viz
    show? Findings land on the '{DIAG_TAB}' control-sheet tab."""
    from automations.shared.tableau_patchright import tableau_session
    lines: list[str] = []

    def rec(s):
        log(s)
        lines.append(str(s))

    rec(f"probe @ {dt.datetime.now().isoformat(timespec='seconds')}")
    # TIMING TEST: the B2B ORDERLOG is a heavy dashboard ('Computing models'
    # ~50s per opt_phase). Crosstab may only enumerate its worksheets after a
    # long render. Load, then open the crosstab dialog at escalating waits and
    # report thumb counts to find the threshold.
    url = pull.orderlog_url("carlos", today)
    rec(f"goto: {url}")
    try:
        with tableau_session(verbose=False) as page:
            try:
                page.goto("about:blank", wait_until="domcontentloaded",
                          timeout=10_000)
            except Exception:
                pass
            page.goto(url, wait_until="domcontentloaded")
            viz = page.frame_locator('iframe[title="Data Visualization"]')
            try:
                viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-'
                            'download"]').wait_for(state="visible",
                                                   timeout=180_000)
                rec("toolbar: visible")
            except Exception as e:
                rec(f"toolbar: NOT visible ({str(e)[:100]})")

            def _open_and_count(tag):
                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(600)
                    viz.locator('[data-tb-test-id="viz-viewer-toolbar-'
                                'button-download"]').click()
                    page.wait_for_timeout(1500)
                    viz.locator('[data-tb-test-id="download-flyout-'
                                'download-crosstab-MenuItem"]').click()
                    page.wait_for_timeout(5000)
                    thumbs = viz.locator(
                        '[data-tb-test-id^="sheet-thumbnail-"]')
                    n = thumbs.count()
                    names = [thumbs.nth(i).inner_text().strip()
                             for i in range(n)]
                    dlg = viz.locator('[role="dialog"]')
                    dtxt = (dlg.first.inner_text(timeout=6000)[:120]
                            if dlg.count() else "")
                    rec(f"[{tag}] thumbs={n} names={names} dlg={dtxt!r}")
                    return n
                except Exception as e:
                    rec(f"[{tag}] err {str(e)[:120]}"); return 0

            waited = 0
            for target in (30, 90, 150, 240):
                page.wait_for_timeout((target - waited) * 1000)
                waited = target
                if _open_and_count(f"+{target}s") > 0:
                    rec(f"*** thumbs appeared at +{target}s ***")
                    break
    except Exception as e:  # noqa: BLE001
        rec(f"PROBE ERROR: {str(e)[:300]}")
    _write_diag(lines)
    return 0

    url = pull.orderlog_url("carlos", today)
    rec(f"goto: {url}")
    try:
        with tableau_session(verbose=False) as page:
            try:
                page.goto("about:blank", wait_until="domcontentloaded",
                          timeout=10_000)
            except Exception:
                pass
            page.goto(url, wait_until="domcontentloaded")
            viz = page.frame_locator('iframe[title="Data Visualization"]')
            try:
                viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-'
                            'download"]').wait_for(state="visible",
                                                   timeout=120_000)
                rec("toolbar: visible")
            except Exception as e:
                rec(f"toolbar: NOT visible ({str(e)[:100]})")
            page.wait_for_timeout(30_000)
            rec("final url: " + page.url[:400])
            try:
                body = viz.locator("body").inner_text(timeout=20_000)
                rec(f"viz body chars: {len(body)}")
                flat = body.replace("\n", " ⏎ ")
                for i in range(0, min(len(flat), 4000), 400):
                    rec("BODY| " + flat[i:i + 400])
            except Exception as e:
                rec(f"viz body: err {str(e)[:150]}")
            # The dialog says 'No sheets to select' because ORDERLOG is a
            # DASHBOARD and no worksheet is active. Try each activation
            # strategy, reopen the crosstab dialog, and report whether the
            # 'Order Log' sheet appears — so we know which one to bake in.
            def _open_dialog():
                viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-'
                            'download"]').click()
                page.wait_for_timeout(1500)
                viz.locator('[data-tb-test-id="download-flyout-download-'
                            'crosstab-MenuItem"]').click()
                page.wait_for_timeout(5000)

            def _dialog_state(tag):
                thumbs = viz.locator('[data-tb-test-id^="sheet-thumbnail-"]')
                n = thumbs.count()
                names = []
                for i in range(n):
                    try:
                        names.append(thumbs.nth(i).inner_text().strip())
                    except Exception:
                        names.append("?")
                dlg = viz.locator('[role="dialog"]')
                dtxt = (dlg.first.inner_text(timeout=8000)[:200]
                        if dlg.count() else "")
                rec(f"[{tag}] thumbs={n} names={names} dlg={dtxt!r}")
                return n

            # Is this a dashboard or a single worksheet?
            for cls in ("tab-dashboard", "tab-worksheet", "tabDashboard",
                        "tab-viz-worksheet"):
                try:
                    rec(f"has .{cls}: {viz.locator('.' + cls).count()}")
                except Exception:
                    pass
            try:
                rec(f"tabZone-viz count: {viz.locator('.tabZone-viz').count()}")
            except Exception:
                pass

            # Dump the whole Download flyout so we know every export option
            # (Crosstab needs a sheet; 'Data' / 'Image' / 'PDF' may not).
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(600)
                viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-'
                            'download"]').click()
                page.wait_for_timeout(1800)
                items = viz.locator('[data-tb-test-id$="-MenuItem"]')
                rec(f"download flyout items: {items.count()}")
                for i in range(items.count()):
                    it = items.nth(i)
                    try:
                        tid = it.get_attribute("data-tb-test-id")
                        txt = it.inner_text().strip()
                        dis = it.get_attribute("aria-disabled")
                        rec(f"  menu[{i}] {tid} txt={txt!r} disabled={dis}")
                    except Exception:
                        pass
            except Exception as e:
                rec(f"flyout dump err: {str(e)[:120]}")

            # Focus a worksheet by clicking a DATA MARK inside each viz zone,
            # then check whether 'Data' enables + Crosstab enumerates — a
            # focused sheet is the missing precondition.
            def _data_disabled():
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
                viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-'
                            'download"]').click()
                page.wait_for_timeout(1200)
                di = viz.locator('[data-tb-test-id="download-flyout-'
                                 'download-data-MenuItem"]')
                dis = di.get_attribute("aria-disabled") if di.count() else "?"
                page.keyboard.press("Escape")
                return dis

            # Nuke onboarding / guided-walkthrough / data-guide overlays that
            # sit on top of the viz and swallow clicks. Report what was removed.
            try:
                removed = viz.locator(":root").evaluate(
                    """() => {
                        const pats = ['walkthrough','onboarding','data-guide',
                            'dataGuide','coachmark','tooltip-overlay','f-overlay',
                            'ftdue','pendo','beacon'];
                        let n = 0; const hits = [];
                        for (const el of Array.from(document.querySelectorAll('*'))) {
                            const id=(el.id||'')+' '+(el.className&&el.className.baseVal!==undefined?el.className.baseVal:(el.className||''));
                            const low=id.toLowerCase();
                            if (pats.some(p=>low.includes(p))) {
                                const r=el.getBoundingClientRect();
                                if (r.width>50&&r.height>50){hits.push(id.slice(0,40));el.remove();n++;}
                            }
                        }
                        return {n, hits: hits.slice(0,8)};
                    }""")
                rec(f"overlay nuke: {removed}")
            except Exception as e:
                rec(f"overlay nuke err: {str(e)[:120]}")

            zone_ids = ["#tabZoneId9", "#tabZoneId6"]
            for zid in zone_ids:
                try:
                    z = viz.locator(zid)
                    if not z.count():
                        rec(f"focus {zid}: absent"); continue
                    bb = z.bounding_box()
                    ifr = page.locator(
                        'iframe[title="Data Visualization"]').bounding_box()
                    # click several points down the grid to hit a text mark
                    for dy in (60, 140, 240):
                        page.mouse.click(ifr["x"] + bb["x"] + 120,
                                         ifr["y"] + bb["y"] + dy)
                        page.wait_for_timeout(700)
                    rec(f"focus {zid}: Data disabled now = {_data_disabled()}")
                    # with a focused sheet, reopen crosstab
                    _open_dialog()
                    if _dialog_state(f"after-focus {zid}") > 0:
                        rec(f"*** crosstab thumbs after focusing {zid} ***")
                        break
                except Exception as e:
                    rec(f"focus {zid}: err {str(e)[:120]}")

            # If Data is now enabled, drive the full-data download flow.
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
                viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-'
                            'download"]').click()
                page.wait_for_timeout(1200)
                di = viz.locator('[data-tb-test-id="download-flyout-'
                                 'download-data-MenuItem"]')
                if di.count() and di.get_attribute("aria-disabled") == "false":
                    with page.context.expect_page(timeout=15000) as popinfo:
                        di.first.click()
                    pop = popinfo.value
                    pop.wait_for_load_state("domcontentloaded")
                    rec(f"data window opened: {pop.url[:120]}")
                    ptxt = pop.locator("body").inner_text(timeout=15000)[:300]
                    rec("DATA-WIN| " + ptxt.replace("\n", " ⏎ "))
                else:
                    rec(f"data still disabled: "
                        f"{di.get_attribute('aria-disabled') if di.count() else 'absent'}")
            except Exception as e:
                rec(f"data-flow err: {str(e)[:150]}")
    except Exception as e:  # noqa: BLE001
        rec(f"PROBE ERROR: {str(e)[:300]}")
    _write_diag(lines)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="vantura_churn")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute + reconcile + print; write nothing")
    ap.add_argument("--probe", action="store_true",
                    help="diagnostics only: load the filtered Order Log view "
                         "and dump what it shows to the control sheet")
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
    args = ap.parse_args(argv)

    log = lambda *a: print(*a, flush=True)  # noqa: E731
    today = (dt.date.fromisoformat(args.today) if args.today
             else dt.date.today())
    if args.probe:
        return _probe(today, log)
    owners = [o for o in OWNER_CFG
              if args.owner in ("both", o[0])]

    # ---------------------------------------------------------- downloads
    files: dict[str, Path] = {}
    churnrates_path = None
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
        from automations.shared.tableau_patchright import tableau_session
        out_dir = Path(tempfile.gettempdir()) / "vantura_churn"
        out_dir.mkdir(exist_ok=True)
        with tableau_session(verbose=False) as page:
            for key, *_ in owners:
                if key in files:
                    continue
                log(f"▶ Order Log ({key}, {today - dt.timedelta(days=60)}"
                    f"..{today})…")
                files[key] = pull.download_orderlog(
                    key, today, out_dir / f"orderlog_{key}.xlsx", page=page)
            if not args.skip_reconcile:
                log("▶ Churn Rates dashboard…")
                churnrates_path = pull.download_churnrates(
                    out_dir / "churnrates.xlsx", page=page)

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
        fill.update_churn_tab(sh.worksheet(tab), results[key]["summary"]["base"],
                              results[key]["helper"], log=log)
        if has_act and not args.skip_activations:
            log(f"▶ updating '{fill.TAB_ACTIVATIONS}'…")
            act = compute.activations_rows(results[key]["lines"], today)
            fill.update_activations(sh.worksheet(fill.TAB_ACTIVATIONS), act,
                                    log=log)

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
