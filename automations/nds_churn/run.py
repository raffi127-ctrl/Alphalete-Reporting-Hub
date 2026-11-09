"""NDS CHURN -- Carlos's 0-30 day churn + activations report on his own NDS
code, the LUCY CHURN (B2B) report remade (Carlos 2026-11-09).

Flow, the B2B one: pull the NDS-SN ORDERLOG (nds_metrics.pull, 60 days,
Owner & Office = CARLOS HIDALGO) -> compute 0-30 bases / disconnects by
activation date, the rolloff rows, the activations rows, the activation
rates -> RECONCILE the wireless 0-30 count against the NDS workbook's own
CHURNRATES view sliced to Carlos (office_metrics.nds_churn's ChurnALlExp
pull) -> only then write the NDS CHURN tab on the Vantura Master Sales
Board. A mismatch writes nothing and exits 1; a view with no rows for Carlos
writes UNVERIFIED and says so. The per-order view stays the existing 'NDS
Order Log' tab (no activations tab here -- see sheet.py).

  python -m automations.nds_churn.run --setup             # create / repair the tab (once)
  python -m automations.nds_churn.run --probe             # export header, mapping, counts; no write
  python -m automations.nds_churn.run --dry-run           # compute + reconcile + print
  python -m automations.nds_churn.run                     # live
  python -m automations.nds_churn.run --dm U046G04P5LG    # live + DM the picture

Runs on Lucy 2 daily (schedule_config nds_churn, 07:00, before the 07:30 NDS
Metrics thread, whose customer_churn section shoots the tab).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Optional, Tuple

from automations.nds_churn import compute as C
from automations.nds_churn import sheet as S

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "nds_churn"
VIEW_OWNER = "Carlos Hidalgo"
CARLOS = "U046G04P5LG"


def pull(today: dt.date, log=print) -> Path:
    from automations.nds_metrics.run import pull as _pull
    return _pull(today, log=log)


def view_counts(today: dt.date, log=print) -> Optional[dict]:
    """Wireless 0-30 disconnects / activated for Carlos on the NDS workbook's
    CHURNRATES view (the per-rep ChurnALlExp cut every NDS office reads),
    summed over his reps -- the reconcile target, cached per day."""
    from automations.office_metrics import nds_churn as NC
    NC._SLICE_OWNER = VIEW_OWNER
    out = OUT_DIR / f"nds_churn_view_{today.isoformat()}.csv"
    if not (out.exists() and out.stat().st_size > 200):
        NC._fetch(out, verbose=False)
    parsed = NC._parse(out)
    reps = parsed.get("reps") or {}
    if not reps:
        return None
    num = denom = 0.0
    got = False
    for slots in reps.values():
        s = slots.get("0-30") or {}
        if s.get("denom") is not None:
            denom += s["denom"]
            got = True
        if s.get("num") is not None:
            num += s["num"]
    if not got:
        return None
    return {"disc": int(round(num)), "base": int(round(denom)),
            "reps": len(reps)}


def reconcile(lines, today: dt.date, summary: dict, log=print
              ) -> Tuple[Optional[bool], str]:
    """True = matches, False = mismatch (do not write), None = unverifiable."""
    try:
        v = view_counts(today, log)
    except Exception as e:  # noqa: BLE001
        return None, f"view pull failed ({type(e).__name__}: {str(e)[:120]})"
    if not v:
        return None, "the NDS CHURNRATES view has no rows for Carlos yet"
    cands = []
    for label, s in (("today", summary),
                     ("yesterday's window",
                      C.churn_summary(lines, today - dt.timedelta(days=1)))):
        cands.append((f"{label}, wireless", s["base"]["Wireless"],
                      s["disc"]["Wireless"]))
        cands.append((f"{label}, all products", s["base_total"],
                      s["disc_total"]))
    for label, base, disc in cands:
        if base == v["base"] and disc == v["disc"]:
            return True, f"view {v['disc']}/{v['base']} = ours ({label})"
    return False, (f"view {v['disc']}/{v['base']} ({v['reps']} reps) vs ours "
                   + "; ".join(f"{l} {d}/{b}" for l, b, d in cands))


def _fmt_rates(office: dict) -> str:
    parts = []
    for b in C.BUCKETS:
        s = office[b]
        r = f"{s['rate']:.1%}" if s["rate"] is not None else "n/a"
        parts.append(f"{b} {s['activated']}/{s['sold']} = {r}")
    return "   ".join(parts)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nds_churn")
    ap.add_argument("--today", default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--setup", action="store_true",
                    help="create / repair NDS CHURN + NDS Activations, then stop")
    ap.add_argument("--probe", action="store_true",
                    help="print the export header, the column mapping and "
                         "value counts; write nothing")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute + reconcile + print; write nothing")
    ap.add_argument("--skip-reconcile", action="store_true",
                    help="write even when the CHURNRATES view disagrees")
    ap.add_argument("--from-file", default=None, metavar="CSV",
                    help="use this export instead of pulling Tableau")
    ap.add_argument("--dm", default=None, metavar="U...",
                    help="after writing, DM the tab's picture to this user")
    a = ap.parse_args(argv)
    log = print
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    from automations.recruiting_report.fill import worksheet_ci
    from automations.vantura_churn import fill as VF

    if a.setup:
        sh = S.open_board()
        ws, made = S.ensure_churn_tab(sh, log)
        S.write_tier_tables(ws, None, log=log)
        try:
            VF.apply_theme(ws, log=log)
        except Exception as e:  # noqa: BLE001 -- cosmetics never block setup
            log(f"  ⚠ theme skipped: {e}")
        VF.hide_helper_columns(ws, log=log)
        log(f"=== setup done ({'created' if made else 'kept'} {S.TAB}) ===")
        return 0

    path = Path(a.from_file) if a.from_file else pull(today, log)
    header, ix, lines = C.load_owner_lines(path, log=log)
    if a.probe:
        print(C.probe_text(header, ix, lines, today))
        print("=== probe done ===", flush=True)
        return 0

    summary = C.churn_summary(lines, today)
    helper = C.helper_block(lines, today)
    office, reps = C.activation_rates(lines, today)
    ts = C.tier_status(summary, today)
    status = C.status_line(ts)
    um = C.unmapped_products(lines, today)
    if um:
        log(f"⚠ product labels in the 0-30 window the map ignores: {um}")
    log(f"CHURN 0-30 (by activation date): base {summary['base']} "
        f"disc {summary['disc']}  wireless split {summary['split']}")
    log(f"ROLLOFF rows: {len(helper)}")
    log(f"RATES: {_fmt_rates(office)}   ({len(reps)} reps)")
    log("STATUS: " + status)
    if a.skip_reconcile:
        ok, detail = None, "skipped (--skip-reconcile)"
    else:
        ok, detail = reconcile(lines, today, summary, log)
    log(f"RECONCILE: {'OK' if ok else 'UNVERIFIED' if ok is None else 'MISMATCH'}"
        f" — {detail}")

    if a.dry_run:
        for r in helper:
            log("   " + " | ".join("" if v is None else str(v) for v in r))
        log("[dry-run] no writes performed.")
        print("=== done ===", flush=True)
        return 0
    if ok is False:
        log("✗ computed churn does not match the NDS CHURNRATES view — "
            "nothing written (--skip-reconcile overrides)")
        return 1

    sh = S.open_board()
    ws = worksheet_ci(sh, S.TAB)
    log(f"▶ updating '{ws.title}'…")
    for step in (VF.repair_viewing_dropdown, VF.hide_helper_columns):
        try:
            step(ws, log=log)
        except Exception as e:  # noqa: BLE001 -- never block the daily write
            log(f"  ⚠ {step.__name__} skipped: {e}")
    VF.update_churn_tab(ws, summary["base"], helper, log=log)
    for b in C.BUCKETS:                       # the writer logs rate:.1%
        if office[b]["rate"] is None:
            office[b]["rate"] = 0.0
            log(f"  ⚠ no {b} sales yet — office rate shown as 0.0%")
    VF.update_activation_rates(ws, office, reps, log=log)
    S.write_tier_tables(ws, ts, log=log)
    S.write_status(ws, status, log=log)
    if a.dm:
        from automations.shared import slack_metrics_post as smp
        from automations.vantura_churn import shot
        png = shot.render_report(
            ws, OUT_DIR / f"nds_churn_{today.isoformat()}.png", log=log)
        smp.dm_user_with_file(
            Path(png), user=a.dm, file_name=Path(png).name,
            comment="🐺 *NDS Customer Churn* — preview of the new NDS CHURN "
                    "tab on the Vantura board (not posted anywhere).")
        log(f"  ✓ DM'd {png}")
    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
