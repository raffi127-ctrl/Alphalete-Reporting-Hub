"""NDS CHURN -- Carlos's 0-30 day churn + activations report on his own NDS
code, the LUCY CHURN (B2B) report remade (Carlos 2026-11-09).

Flow, the B2B one: pull the NDS-SN ORDERLOG (nds_metrics.pull, 60 days,
Owner & Office = CARLOS HIDALGO) -> compute 0-30 bases / disconnects by
activation date, the three rolloff tables (wireless non-BYOD / BYODs /
Air, since 11/15), the activation rates -> RECONCILE the wireless 0-30 count against the NDS workbook's own
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
# Rich output goes to a tab on the control sheet (the queue's Result cell
# holds ~470 chars; logtail cuts lines at 200) -- read it back from the mini.
CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
DIAG_TAB = "NDS Churn Diag"          # --dry-run
PROBE_TAB = "NDS Churn Probe"        # --probe (its own tab, so a dry run never overwrites it)


def write_diag(lines, log=print, tab: str = DIAG_TAB) -> None:
    """Replace the tab's contents with these lines (one per row)."""
    try:
        from automations.recruiting_report.fill import _retry, open_by_key
        sh = open_by_key(CONTROL_SHEET_ID)
        try:
            ws = sh.worksheet(tab)
        except Exception:  # noqa: BLE001 -- first time: make it
            ws = sh.add_worksheet(tab, rows=600, cols=4)
        _retry(lambda: ws.clear())
        rows = [[dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "written by nds_churn"]]
        rows += [[str(x)[:49000]] for x in lines]
        if len(rows) > ws.row_count:
            _retry(lambda: ws.add_rows(len(rows) - ws.row_count + 20))
        _retry(lambda: ws.batch_update([{"range": f"A1:B{len(rows)}",
                                         "values": [r + [""] * (2 - len(r)) for r in rows]}],
                                       value_input_option="RAW"))
        log(f"[nds_churn] diag -> control sheet tab {tab!r} ({len(lines)} line(s))")
    except Exception as e:  # noqa: BLE001 -- a diag write never fails the run
        log(f"[nds_churn] diag tab write failed: {type(e).__name__}: {e}")


def pull(today: dt.date, log=print) -> Path:
    from automations.nds_metrics.run import pull as _pull
    return _pull(today, log=log)


def view_counts(today: dt.date, log=print, fresh: bool = False) -> Optional[dict]:
    """Wireless 0-30 disconnects / activated for Carlos on the NDS workbook's
    CHURNRATES view (the per-rep ChurnALlExp cut every NDS office reads),
    summed over his reps -- the reconcile target, cached per day.
    fresh=True ignores today's cache (see reconcile)."""
    from automations.office_metrics import nds_churn as NC
    NC._SLICE_OWNER = VIEW_OWNER
    out = OUT_DIR / f"nds_churn_view_{today.isoformat()}.csv"
    if fresh or not (out.exists() and out.stat().st_size > 200):
        NC._fetch(out, verbose=False)
    parsed = NC._parse(out)
    reps = parsed.get("reps") or {}
    if not reps:
        return None
    num = denom = 0.0
    got = False
    detail = {}
    for rep_name, slots in reps.items():
        s = slots.get("0-30") or {}
        if s.get("denom") is not None:
            denom += s["denom"]
            got = True
        if s.get("num") is not None:
            num += s["num"]
        detail[rep_name] = (s.get("num"), s.get("denom"), s.get("pct"))
    if not got:
        return None
    return {"disc": int(round(num)), "base": int(round(denom)),
            "reps": len(reps), "detail": detail}


# The gate exists to catch a broken or stale pull, not a one-line roster
# quibble: disconnects must match exactly, the base may differ by this many
# lines (2026-11-09: the view carried 126 port lines to our 127 -- one rep's
# single line sat outside its owner slice -- with disconnects equal at 16).
BASE_TOLERANCE = 2


def _rep_diff(lines, today, view: dict) -> str:
    ours = _our_rep_units(lines, today)
    out = []
    for name in sorted(set(ours) | set(view.get("detail", {}))):
        vd = view.get("detail", {}).get(name)
        v = (int(vd[0] or 0), int(vd[1] or 0)) if vd else None
        o = ours.get(name)
        if v != o:
            out.append(f"{name}: view {v} ours {o}")
    return "; ".join(out) or "per rep identical"


def reconcile(lines, today: dt.date, summary: dict, log=print
              ) -> Tuple[Optional[bool], str]:
    """True = matches (disconnects exact, base within BASE_TOLERANCE),
    False = mismatch (do not write), None = unverifiable.

    A mismatch against the CACHED view re-pulls it once before failing
    (2026-11-12: the 06:08 pull caught the view mid-refresh -- 8/85 after
    16/130 on 11/10 and 17/139 on 11/11 -- and the per-day cache made every
    re-run that day compare against the same bad snapshot)."""
    ok, detail = _reconcile_once(lines, today, summary, log, fresh=False)
    if ok is False:
        log(f"RECONCILE: mismatch on the cached view ({detail[:160]}) -- "
            "re-pulling the view once")
        ok2, detail2 = _reconcile_once(lines, today, summary, log, fresh=True)
        if ok2 is not None:     # a failed re-pull keeps the known mismatch
            ok, detail = ok2, detail2
    return ok, detail


def _reconcile_once(lines, today: dt.date, summary: dict, log, fresh: bool
                    ) -> Tuple[Optional[bool], str]:
    global _LAST_VIEW
    try:
        v = view_counts(today, log, fresh=fresh)
    except Exception as e:  # noqa: BLE001
        return None, f"view pull failed ({type(e).__name__}: {str(e)[:120]})"
    _LAST_VIEW = v
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
    for label, base, disc in cands:
        if disc == v["disc"] and abs(base - v["base"]) <= BASE_TOLERANCE:
            return True, (f"view {v['disc']}/{v['base']} vs ours {disc}/{base} "
                          f"({label}) -- within tolerance; "
                          + _rep_diff(lines, today, v))
    return False, (f"view {v['disc']}/{v['base']} ({v['reps']} reps) vs ours "
                   + "; ".join(f"{l} {d}/{b}" for l, b, d in cands)
                   + " -- " + _rep_diff(lines, today, v))


_LAST_VIEW = None


def _our_rep_units(lines, today):
    """Per rep: (disconnected, activated) 0-30 wireless units -- to set against
    the view's per-rep rows when the totals disagree."""
    out = {}
    for u in C.churn_units(lines, today):
        if u["prod"] != "Wireless":
            continue
        d, a = out.get(u["rep"], (0, 0))
        out[u["rep"]] = (d + (1 if u["status"].lower() in C.DISCONNECTED else 0), a + 1)
    return out


def _fmt_rates(office: dict) -> str:
    parts = []
    for b in C.BUCKETS:
        s = office[b]
        r = f"{s['rate']:.1%}" if s["rate"] is not None else "n/a"
        parts.append(f"{b} {s['activated']}/{s['sold']} = {r}")
    return "   ".join(parts)


def view_probe(today: dt.date, log=print) -> int:
    """What Smart Circle's all-owners Churn Rates view (ChurnALlExp) carries,
    off today's cached pull (a fresh pull when none): header, first rows,
    the distinct colour / measure values, every Average row, and whether
    anything on it says BYOD or Air -- to the probe tab (Carlos 2026-11-14:
    a national average per BYOD / non-BYOD / Air table, if the view has it)."""
    import collections
    from automations.office_metrics import nds_churn as NC
    path = OUT_DIR / f"nds_churn_view_{today.isoformat()}.csv"
    if not (path.exists() and path.stat().st_size > 200):
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        NC._fetch(path, verbose=False)
    rows = NC._decode(path)
    out = [f"VIEW PROBE {today} {path.name}: {len(rows)} row(s)"]
    if rows:
        out.append("header: " + " | ".join(rows[0]))
    for r in rows[1:16]:
        out.append("row: " + " | ".join(r))
    c2 = collections.Counter((r[2] or "").strip() for r in rows[1:] if len(r) > 3)
    c3 = collections.Counter((r[3] or "").strip() for r in rows[1:] if len(r) > 3)
    out.append("col2 (colour) values: " + ", ".join(f"{k or '(blank)'}={v}" for k, v in c2.most_common(12)))
    out.append("col3 (measure) values: " + ", ".join(f"{k or '(blank)'}={v}" for k, v in c3.most_common(12)))
    for r in rows[1:]:
        if any("average" in (c or "").lower() for c in r[:2]):
            out.append("AVERAGE row: " + " | ".join(r))
    byod = sum(1 for r in rows if any("byod" in (c or "").lower() for c in r))
    air = sum(1 for r in rows if any(" air" in (" " + (c or "")).lower() for c in r))
    owners = {(r[0] or "").strip() for r in rows[1:] if len(r) > 1 and (r[0] or "").strip()}
    out.append(f"rows mentioning BYOD: {byod}; Air: {air}; distinct owner cells: {len(owners)}")
    print("\n".join(out))
    write_diag(out, log=log, tab=PROBE_TAB)
    print("=== view probe done ===", flush=True)
    return 0


def rep_lines(lines, today: dt.date, name: str, log=print) -> int:
    """One rep's lines posted in the 0-60 window, each with what the churn math
    decides about it -- to find WHICH lines a view leaves out when RECONCILE
    names that rep (2026-11-16: Esmeralda Gonzalez, view (0, 8) ours (2, 10)).
    Read-only; only dates/product/status/kind, never customer fields."""
    # "Esmeralda_Gonzalez" too: a queued rerun's args split on spaces.
    want = " ".join(name.replace("_", " ").split()).lower()
    base = {id(u) for u in C.churn_units(lines, today)}
    cutoff = today - dt.timedelta(days=60)
    out = [f"REP {name} -- {today.isoformat()} (0-30 base = in_base)"]
    keep = ("posted", "prod", "product", "status", "tn_type")
    for ln in sorted(lines, key=lambda x: (x.get("posted") or dt.date.min)):
        if (ln.get("rep") or "").strip().lower() != want:
            continue
        if ln.get("posted") and ln["posted"] < cutoff:
            continue
        extra = {k: v for k, v in ln.items() if k not in keep
                 and k not in ("customer", "tn", "spe", "spm", "rep", "raw")
                 and isinstance(v, (str, int, float, dt.date)) and v not in ("", None)}
        out.append(" | ".join([str(ln.get(k)) for k in keep]
                              + [f"kind={C.line_kind(ln)}",
                                 f"in_base={id(ln) in base}",
                                 str(extra)[:400]]))
    print("\n".join(out), flush=True)
    write_diag(out, log=log, tab=PROBE_TAB)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nds_churn")
    ap.add_argument("--today", default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--setup", action="store_true",
                    help="create / repair NDS CHURN + NDS Activations, then stop")
    ap.add_argument("--probe", action="store_true",
                    help="print the export header, the column mapping and "
                         "value counts; write nothing")
    ap.add_argument("--view-probe", action="store_true",
                    help="dump Smart Circle's all-owners Churn Rates view (header, "
                         "rows, measures, Average rows, BYOD/Air mentions) to the probe tab")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute + reconcile + print; write nothing")
    ap.add_argument("--skip-reconcile", action="store_true",
                    help="write even when the CHURNRATES view disagrees")
    ap.add_argument("--from-file", default=None, metavar="CSV",
                    help="use this export instead of pulling Tableau")
    ap.add_argument("--rep", default=None, metavar="NAME",
                    help="list one rep's 0-30 lines (date, product, status, kind; "
                         "no customer data) to the probe tab, then stop -- for a "
                         "RECONCILE mismatch that names a rep")
    ap.add_argument("--dm", default=None, metavar="U...",
                    help="after writing, DM the tab's picture to this user "
                         "(with --captain: a comma-separated list)")
    ap.add_argument("--captain", default=None, metavar="OWNER_KEY",
                    help="one owner of Khalil's captainship (captain_report.OWNERS: "
                         "zaid, atef, isaiah, juan, khalil, maxamad, carlos): the "
                         "non-BYOD 0-30 + 90 Day churn picture, no tab written")
    ap.add_argument("--url-extra", default="", metavar="PARAMS",
                    help="with --captain: extra query parameters for the ORDERLOG "
                         "export URL (a Tableau URL filter), e.g. IF%%2FOOF=IF%%2COOF")
    ap.add_argument("--search-range", default="", metavar="LABEL",
                    help="with --captain: the export's 'Search Date Range' value, URL-encoded "
                         "(default Order%%20Date), e.g. Activation%%20Date")
    a = ap.parse_args(argv)
    log = print
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    if a.captain:
        from automations.nds_churn import captain_report as CR
        return CR.run(a.captain, today, dry_run=a.dry_run, from_file=a.from_file,
                      dm=a.dm, skip_reconcile=a.skip_reconcile, url_extra=a.url_extra,
                      search_range=a.search_range, log=log)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    from automations.recruiting_report.fill import _retry, worksheet_ci
    from automations.vantura_churn import fill as VF

    if a.setup:
        sh = S.open_board()
        ws, made = S.ensure_churn_tab(sh, log)
        if made:
            # A fresh LUCY CHURN duplicate only: its theme first (it paints the
            # B2B chart's four-column titles), then rows 4-12 the NDS way. On
            # the live tab the daily run owns that block -- the theme would
            # paint over it.
            try:
                VF.apply_theme(ws, log=log)
            except Exception as e:  # noqa: BLE001 -- cosmetics never block setup
                log(f"  ⚠ theme skipped: {e}")
            S.write_top_block(ws, None, None, None, log=log)
        VF.hide_helper_columns(ws, log=log)
        log(f"=== setup done ({'created' if made else 'kept'} {S.TAB}) ===")
        return 0

    if a.view_probe:
        return view_probe(today, log=log)
    path = Path(a.from_file) if a.from_file else pull(today, log)
    header, ix, lines = C.load_owner_lines(path, log=log)
    if a.rep:
        return rep_lines(lines, today, a.rep, log=log)
    if a.probe:
        text = C.probe_text(header, ix, lines, today)
        print(text)
        write_diag(["PROBE " + today.isoformat()] + text.split("\n"), log=log,
                   tab=PROBE_TAB)
        print("=== probe done ===", flush=True)
        return 0

    summary = C.churn_summary(lines, today)
    office, reps = C.activation_rates(lines, today)
    rates = C.box_activation_rates(lines, today)
    ts = C.tier_status(summary, today)
    status = C.status_line(ts)
    um = C.unmapped_products(lines, today)
    if um:
        log(f"⚠ product labels in the 0-30 window the map ignores: {um}")
    pend = C.pending_orders(lines, today)
    log(f"PENDING 0-30 (sold, not activated, not canceled): {pend['total']} "
        f"(W {pend['Wireless']} / Air {pend['Air']} / Int {pend['Internet']}"
        f"{' / Other %d' % pend['Other'] if pend['Other'] else ''}; "
        f"canceled {pend['canceled']}; tablets/wearables/upgrades not counted "
        f"{pend['excluded']}; statuses {pend['statuses']})")
    log(f"NOT ORDERS (0-30, by kind): {C.excluded_orders(lines, today)}")
    box = C.product_box(lines, today)
    log("BOX: " + "; ".join(f"{k} act {v['act']} disc {v['disc']} pend {v['pend']}"
                            for k, v in box.items()))
    tables = C.class_tables(lines, today, box)
    log("TABLES: " + "; ".join(
        f"{t['title']} {len(t['rows'])} group(s) / "
        f"{sum(r[C.T_LINES] for r in t['rows'])} of {t['disc']} disconnected line(s)"
        for t in tables))
    if box["internet"]["disc"]:
        log(f"NOTE: {box['internet']['disc']} Internet disconnect(s) have no table "
            "(the old All Orders list left Internet out too)")
    log(f"CHURN 0-30 (by activation date): base {summary['base']} "
        f"disc {summary['disc']}  wireless split {summary['split']}")
    log(f"RATES: {_fmt_rates(office)}   ({len(reps)} reps)")
    log("BOX RATES: " + "; ".join(f"{k} {_fmt_rates(v)}" for k, v in rates.items()))
    log("STATUS: " + status)
    if a.skip_reconcile:
        ok, detail = None, "skipped (--skip-reconcile)"
    else:
        ok, detail = reconcile(lines, today, summary, log)
    log(f"RECONCILE: {'OK' if ok else 'UNVERIFIED' if ok is None else 'MISMATCH'}"
        f" — {detail}")

    if a.dry_run:
        rows_txt = []
        for t in tables:
            rows_txt.append(S.band_text(t))
            rows_txt += [("   " + " | ".join("" if v is None else str(v) for v in r))
                         for r in t["rows"]] or ["   (none)"]
        for t in rows_txt:
            log("   " + t)
        write_diag(["DRY-RUN " + today.isoformat(),
                    f"CHURN 0-30: base {summary['base']} disc {summary['disc']} split {summary['split']}",
                    f"RATES: {_fmt_rates(office)} ({len(reps)} reps)",
                    f"RECONCILE: {ok} -- {detail}",
                    "STATUS: " + status,
                    f"PENDING: {pend}",
                    f"BOX: {box}",
                    f"BOX RATES: {rates}",
                    f"UNMAPPED: {um}",
                    "TABLES:"] + rows_txt
                   + ["VIEW REPS (0-30 disc / activated / pct):"]
                   + ([f"{k}: {v}" for k, v in sorted((_LAST_VIEW or {}).get("detail", {}).items())]
                      or ["(no view rows)"])
                   + ["OUR REPS (0-30 wireless disc / activated):"]
                   + [f"{k}: {v}" for k, v in sorted(_our_rep_units(lines, today).items())]
                   + ["RATES BY REP:"] + [f"{k}: {v}" for k, v in sorted(reps.items())], log=log)
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
    # 2026-11-15: the three rolloff tables replace the single FILTER list
    # (Carlos: "let's make into tables one for wireless no BYODs, BYODs, &
    # airs") -- plain values, so none of vantura_churn.fill's helper-block
    # machinery runs here any more; migrate_filter_list retires it once.
    S.migrate_filter_list(ws, log=log)
    S.write_subtitle(ws, log=log)
    layout = S.write_class_tables(ws, tables, log=log)
    try:                                  # rose on disconnects from the last 7 days
        S.ensure_recent_highlight(ws, log=log)
    except Exception as e:  # noqa: BLE001 -- a colour never blocks the numbers
        log(f"  ⚠ recent-disconnect highlight skipped: {e}")
    S.write_rep_list(ws, office, reps, log=log)      # office total + reps (Carlos 11/14)
    S.write_status(ws, status + "  " + S.BOX_NOTE, log=log)
    # Rows 4-12 in one batch: the box (a row per product -- Disconnects |
    # Activations | Pending | Churn % | the two activation rates, Carlos
    # 11/17) and the tier charts. A rate bucket with no sales stays blank,
    # not 0.0% (NDS started 10/19, so 31-60 has nothing to rate until
    # mid-November).
    S.write_top_block(ws, box, rates, ts, log=log)
    try:                                  # tables bordered for the gridline-less shot
        S.ensure_borders(ws, layout, log=log)
    except Exception as e:  # noqa: BLE001 -- a border never blocks the numbers
        log(f"  ⚠ borders skipped: {e}")
    if a.dm:
        from automations.shared import slack_metrics_post as smp
        from automations.vantura_churn import shot
        png = shot.render(ws, OUT_DIR / f"nds_churn_{today.isoformat()}.png",
                          S.report_range(ws))
        smp.dm_user_with_file(
            Path(png), user=a.dm, file_name=Path(png).name,
            comment="🐺 *NDS Customer Churn* — preview of the NDS CHURN tab on the "
                    "Vantura board (not posted anywhere).")
        log(f"  ✓ DM'd {png}")
    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
