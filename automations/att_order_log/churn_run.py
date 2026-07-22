"""B2B Churn — fills each B2B office's 'Lucy New INT / Wireless / AIR Churn' tabs.

Megan 2026-07-19: the churn tabs "should act like the metrics report one we do
for the fiber d2d offices". So this reuses that machinery wholesale rather than
reimplementing it — new_internet_churn.fill is a 1,890-line, label-driven,
four-section filler that already inserts a dated column pair each morning, adds
missing reps, sorts, colours, and hides dark reps. None of that is rewritten
here.

ALL-TEAM + OFFICE-DRIVEN (2026-07-22): pull the three ALL-TEAM product views
(PRODUCTS) ONCE each, then slice every office's owner out of that single pull IN
CODE — the same CHURN_SLICE_OWNER path office_metrics uses against the D2D
INTAllTeams / WirelessAllTeams. So 3 pulls/day for ANY number of offices, and
adding a B2B office (Carlos, Atef, …) is one OFFICES row (owner + board) with NO
new Tableau view. Confirm a new office's owner spelling first with --probe-owners.

WHAT IS B2B-SPECIFIC, and all of it is config or the header adapter:

  * the views  — three ALL-TEAM ATTTRACKER-B2B/CHURNRATES views, one per product
                 (CarlosTEAMWireless / CarlosTEAMNewINTEXP / CarlosTEAMAIREXP).
                 They MUST be pulled through the CROSSTAB DIALOG: the direct .csv
                 ignores custom views, and since the export has an owner column
                 but NO product column, owner splits in code while product needs
                 one view each.
  * the header — churn_shape.adapt(); see that module. A rename, not a reshape.
  * PRODUCTS   — product_key -> {label, tab, url} (the shared TEAM views).
  * OFFICES    — office_key -> {label, owner, sheet_id}. One row per office.

RUNS ON LUCY 2 (Carlos's Tableau identity — these are his custom views).

DRY-RUN BY DEFAULT. --fill writes the tabs. Slack posting is deliberately NOT
wired here: the B2B thread is assembled separately and stays gated.

    python -m automations.att_order_log.churn_run                    # all offices, pull + report
    python -m automations.att_order_log.churn_run --fill             # all offices, write tabs
    python -m automations.att_order_log.churn_run --office carlos --only wireless --fill
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import traceback
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

CROSSTAB_SHEET = "ICD Churn"

REPO_ROOT = Path(__file__).resolve().parents[2]
WORK_DIR = REPO_ROOT / "output" / "att_churn"

_T = "https://us-east-1.online.tableau.com/#/site/sci/views/"

# THREE ALL-TEAM PRODUCT VIEWS, pulled ONCE each per run, then sliced per office
# by owner IN CODE (the new_internet_churn parser's CHURN_SLICE_OWNER mode — the
# same one office_metrics uses against the D2D INTAllTeams / WirelessAllTeams).
# WHY per-product-but-not-per-office: the CHURNRATES crosstab carries an OWNER
# column (so owners split in code) but NO product column (so products can only be
# separated by the view's own filter — hence one TEAM view per product). Net:
# 3 pulls/day for ANY number of offices, and adding an office needs no new view.
# Same three tab names on every office board, so tab lives here, not per office.
PRODUCTS = {
    "wireless": {
        "label": "Wireless Churn", "tab": "Lucy Wireless Churn",
        "url": _T + "ATTTRACKER-B2B/CHURNRATES/"
               "e5d34696-30de-4db7-a27e-2654dbf9babd/CarlosTEAMWireless?:iid=1",
    },
    "new_int": {
        "label": "New Internet Churn", "tab": "Lucy New INT Churn",
        "url": _T + "ATTTRACKER-B2B/CHURNRATES/"
               "2365c727-4967-4bfc-a3c5-01015ea98278/CarlosTEAMNewINTEXP?:iid=2",
    },
    "air": {
        "label": "AIR Churn", "tab": "Lucy AIR Churn",
        "url": _T + "ATTTRACKER-B2B/CHURNRATES/"
               "66dd0946-c47b-488e-990c-cf67f04de4c0/CarlosTEAMAIREXP?:iid=1",
    },
}

# ONE ROW PER B2B OFFICE — owner + board, nothing else. Adding an office is a new
# row here: no new Tableau view (it's sliced out of the shared TEAM views above).
#   owner    — EXACTLY as the adapted crosstab spells the owner after
#              churn_shape.normalize_owner() strips "<NAME> [company]" to the
#              bare name; the D2D parser matches by EXACT (upper) equality. Verify
#              the spelling with `--probe-owners` before trusting a new office.
#   sheet_id — the office's board (holds its Lucy Wireless/New INT/AIR Churn tabs).
OFFICES = {
    "carlos": {
        "label": "Carlos",
        "owner": "CARLOS HIDALGO",
        "sheet_id": "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY",  # Vantura Master Sales Board
    },
    "atef": {
        "label": "Atef (Domin8)",
        "owner": "ATEF CHOUDHURY",   # PROVISIONAL — confirm via --probe-owners
        "sheet_id": "15YUHkAcG2AfiF6KRhCiOBKGDdS9nnjxdfvIXr7oRX30",  # All In One - Atef
    },
}


def _pull_and_adapt(page, tag: str, spec: dict, log=print) -> Path:
    """Crosstab-download one view and rename its header to D2D naming.

    `tag` is the unique office_product handle (e.g. "carlos_wireless") — it names
    the temp files so two offices' same-product pulls never overwrite each other.
    """
    from automations.recruiting_report.opt_phase import drive_crosstab_dialog

    from . import churn_shape

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    raw = WORK_DIR / "{}_raw.csv".format(tag)
    adapted = WORK_DIR / "{}_adapted.csv".format(tag)

    log("  [{}] crosstab download…".format(tag))
    drive_crosstab_dialog(page, spec["url"], CROSSTAB_SHEET, raw, verbose=False)
    info = churn_shape.adapt(raw, adapted)
    log("  [{}] {} rows; periods {}".format(
        tag, info["rows"], info["periods"]))
    return adapted


def _parse(adapted: Path, owner: str, log=print) -> dict:
    """Parse via the D2D parser, sliced to `owner`.

    CHURN_SLICE_OWNER is set around the call rather than globally so this can
    never leak into another module's environment (or another office's owner)
    mid-process.
    """
    from automations.new_internet_churn import pull as ni_pull

    prev = os.environ.get("CHURN_SLICE_OWNER")
    os.environ["CHURN_SLICE_OWNER"] = owner
    try:
        parsed = ni_pull.parse(adapted)
    finally:
        if prev is None:
            os.environ.pop("CHURN_SLICE_OWNER", None)
        else:
            os.environ["CHURN_SLICE_OWNER"] = prev

    reps = parsed.get("reps") or {}
    if not reps:
        # The D2D parser returns an empty dict rather than raising when it
        # cannot find its columns. Left alone that fills nothing and reports
        # success, so turn it into a hard failure here.
        raise RuntimeError(
            "parsed 0 reps for {!r} — the crosstab schema moved, or the owner "
            "slice matched nothing.".format(owner))
    log("  parsed {} reps; office total periods {}".format(
        len(reps), sorted((parsed.get("office_total") or {}).keys())))
    return parsed


def _fill(tag: str, spec: dict, parsed: dict, today: dt.date, sheet_id: str,
          log=print) -> None:
    """Write one tab through the D2D fill, pointed at `sheet_id` (the office's board).

    Targets the board by SETTING THE MODULE'S CONSTANTS DIRECTLY rather than via
    env-then-reload. The old path set os.environ + importlib.reload and trusted
    the module to re-read at reload time; that is exactly the kind of implicit
    coupling that fails silently, and all three feeds sat unfilled through
    several runs. Setting the two attributes the fill actually reads
    (SHEET_ID, TAB_LOCAL_OFFICE) leaves no room for a reload to be skipped or
    for import order to matter. One shared fill module serves all three feeds —
    wireless_churn.fill only re-exports new_internet_churn.fill, so there is no
    per-product code to pick.
    """
    from automations.new_internet_churn import fill as fill_mod

    fill_mod.SHEET_ID = sheet_id
    fill_mod.TAB_LOCAL_OFFICE = spec["tab"]

    ws = fill_mod.open_ws()
    sections = fill_mod.find_sections(ws)
    log("  [{}] tab {!r}: {} sections {}".format(
        tag, spec["tab"], len(sections), sorted(sections)))
    if not sections:
        raise RuntimeError(
            "no churn sections found in {!r} — the scaffold's column-A labels "
            "do not match (expected '... 0-30 DAYS' etc.)".format(spec["tab"]))

    # SEQUENCE + ARG ORDER mirror the proven D2D caller (automations/churn/run.py)
    # exactly. My first version reordered these and passed write_today(ws,
    # sections, PARSED, TODAY) — the args swapped — which crashed with
    # "'datetime.date' object has no attribute 'get'" and left all three tabs
    # empty. The D2D order is load-bearing: insert_missing_reps runs BEFORE the
    # column insert, and sections are RE-FOUND after the row inserts (they shift
    # lower sections down and leave the in-memory header rows stale).
    already = fill_mod.today_already_filled(ws, sections, today)
    fill_mod.insert_missing_reps(ws, sections, parsed, logfn=log)
    if not already:
        fill_mod.insert_two_cols_at_b(ws, sections)
        fill_mod._merge_section_headers(ws, sections)
    sections = fill_mod.find_sections(ws)          # re-resolve after inserts
    fill_mod.write_today(ws, sections, today, parsed, logfn=log)
    log("  [{}] wrote {}".format(tag, fill_mod._date_label(today)))

    # POST-WRITE PASS — the reason the first fill landed data but no
    # red/yellow/green (Megan 2026-07-20, wireless tab all-purple). write_today
    # only puts the numbers down; the D2D runner (automations/churn/run.py) then
    # runs this whole sequence to sort, format, and COLOUR the pct cells. Same
    # order, all re-exported by the fill module. Skipping it is why the churn
    # % cells had no threshold colour.
    fill_mod.unhide_all_rep_rows(ws, sections, logfn=log)
    sections = fill_mod.find_sections(ws)          # unhide can shift nothing,
    fill_mod.apply_rep_row_format(ws, sections, logfn=log)   # but be safe
    fill_mod.apply_pct_direct_colors(ws, sections, parsed, logfn=log)
    fill_mod.apply_units_white_override(ws, sections, logfn=log)
    fill_mod.clear_empty_cell_backgrounds(ws, sections, logfn=log)
    fill_mod.hide_blanks_today(ws, sections, logfn=log)
    fill_mod.hide_after_5_zero_pulls(ws, sections, logfn=log)
    log("  [{}] formatted (sort + threshold colours + hide)".format(tag))
    return ws, fill_mod.find_sections(ws)


def _render(key: str, ws, sections: dict, today: dt.date, log=print) -> dict:
    """Render this product's populated sections to PNGs (reuses the D2D
    renderers). Returns {period: png_path}."""
    from . import churn_render

    pngs = churn_render.render(key, ws, sections, today, WORK_DIR)
    for period, path in sorted(pngs.items()):
        log("  [{}] png {} -> {}".format(key, period, path.name))
    if not pngs:
        log("  [{}] no populated sections to render".format(key))
    return pngs


def _distinct_owners(adapted: Path) -> dict:
    """Read the adapted crosstab's (normalised) owner column -> {owner: row_count},
    sorted. Rows not reps — a rep spans several metric rows — but the SET of owners
    is what --probe-owners needs: it shows who a TEAM view actually contains and
    exactly how each owner is spelled, so a new office's `owner` can be matched."""
    import csv as _csv
    from collections import Counter

    from . import churn_shape
    # The adapted crosstab is UTF-16-LE (Tableau's export encoding) — must match
    # new_internet_churn.pull.parse, or every char's high NUL byte trips the
    # CSV reader ("line contains NUL").
    with open(adapted, encoding="utf-16-le", newline="") as fh:
        rows = list(_csv.reader(fh, delimiter="\t"))
    if not rows:
        return {}
    hdr = [h.strip() for h in rows[0]]
    if churn_shape.OWNER_WIDE not in hdr:
        return {}
    oi = hdr.index(churn_shape.OWNER_WIDE)
    c = Counter(r[oi].strip() for r in rows[1:]
                if oi < len(r) and r[oi].strip())
    return dict(sorted(c.items()))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="att_order_log.churn_run")
    ap.add_argument("--fill", action="store_true",
                    help="write the tabs (default: pull + report only)")
    ap.add_argument("--png", action="store_true",
                    help="render each product's sections to PNGs (implies "
                         "--fill; the render reads the freshly-filled tab)")
    ap.add_argument("--office", choices=sorted(OFFICES), default=None,
                    help="run one office (default: all offices)")
    ap.add_argument("--only", choices=sorted(PRODUCTS), default=None,
                    metavar="PRODUCT",
                    help="run one product (default: all three)")
    ap.add_argument("--probe-owners", action="store_true", dest="probe_owners",
                    help="pull each TEAM view once and print the distinct owners "
                         "it contains (no slice, no write) — confirm an office's "
                         "owner spelling before wiring it")
    ap.add_argument("--today", default=None, metavar="YYYY-MM-DD")
    args = ap.parse_args(argv)
    if args.png:
        args.fill = True          # render reads the tab the fill just wrote

    today = (dt.date.fromisoformat(args.today) if args.today
             else dt.date.today())
    products = ({args.only: PRODUCTS[args.only]} if args.only else PRODUCTS)
    offices = ({args.office: OFFICES[args.office]} if args.office else OFFICES)
    log = print
    if args.probe_owners:
        log("B2B Churn OWNER PROBE — {} — products: {}".format(
            today, ", ".join(products)))
    else:
        log("B2B Churn — {} — products: {} × offices: {}".format(
            today, ", ".join(products), ", ".join(offices)))

    import time

    from patchright.sync_api import sync_playwright

    from automations.shared import tableau_patchright as tp
    from automations.vantura_churn import cdp_pull

    rc = 0
    results = {}          # "office_product" -> "ok" | "FAILED"

    # Pull each ALL-TEAM product view ONCE (its own fresh browser + one retry —
    # the CDP Chrome on Lucy 2 dies mid-run intermittently, so isolating each pull
    # keeps one death from stranding the rest), then slice every office's owner out
    # of that single pull IN CODE. 3 pulls total for N offices; no per-office view.
    with sync_playwright() as p:
        for pkey, pv in products.items():
            log("")
            log("=== {} ({}) ===".format(pv["label"], pkey))
            adapted = None
            for attempt in (1, 2):
                proc = None
                try:
                    cdp_pull._kill_ours()
                    proc = cdp_pull._launch()
                    log("  [cdp] {} attempt {}: real Chrome pid={}; waiting 20s"
                        .format(pkey, attempt, proc.pid))
                    time.sleep(20)
                    browser = p.chromium.connect_over_cdp(
                        "http://127.0.0.1:{}".format(cdp_pull.CDP_PORT))
                    ctx = (browser.contexts[0] if browser.contexts
                           else browser.new_context())
                    page = ctx.pages[0] if ctx.pages else ctx.new_page()
                    tp._ensure_tableau_authenticated(page, verbose=False,
                                                     allow_form_login=True)
                    log("  [cdp] auth OK")
                    adapted = _pull_and_adapt(page, pkey, pv, log=log)
                    break
                except Exception:  # noqa: BLE001 — one product/attempt must not kill the rest
                    log("  {} pull attempt {} FAILED:".format(pkey, attempt))
                    for ln in traceback.format_exc().splitlines()[-12:]:
                        log("    " + ln[:200])
                finally:
                    if proc is not None:
                        try:
                            proc.terminate()
                        except Exception:  # noqa: BLE001
                            pass
                    cdp_pull._kill_ours()

            if adapted is None:
                # The pull failed after its retry — every office fails for this
                # product (nothing to slice), but the OTHER products still run.
                for okey in offices:
                    results["{}_{}".format(okey, pkey)] = "FAILED"
                rc = 1
                continue

            if args.probe_owners:
                owners = _distinct_owners(adapted)
                log("  {} distinct owners: {}".format(
                    len(owners),
                    ", ".join("{}({})".format(o, n) for o, n in owners.items())
                    or "NONE"))
                for okey, office in offices.items():
                    hit = "PRESENT" if office["owner"] in owners else "MISSING"
                    log("    office {!r} owner {!r}: {}".format(
                        okey, office["owner"], hit))
                continue

            # Slice every office out of this ONE pull (CPU + gspread, no browser).
            for okey, office in offices.items():
                tag = "{}_{}".format(okey, pkey)
                try:
                    parsed = _parse(adapted, office["owner"], log=log)
                    if args.fill:
                        ws, sections = _fill(tag, pv, parsed, today,
                                             office["sheet_id"], log=log)
                        if args.png:
                            # renderer is keyed by PRODUCT (pkey). Multi-office
                            # --png shares WORK_DIR png names — fine for the usual
                            # one-office manual render; not used by the daily run.
                            _render(pkey, ws, sections, today, log=log)
                    else:
                        log("  [{}] DRY RUN — {} reps; not writing {!r}".format(
                            tag, len(parsed.get("reps") or {}), pv["tab"]))
                    results[tag] = "ok"
                except Exception:  # noqa: BLE001 — one office must not kill the rest
                    log("  {} slice/fill FAILED:".format(tag))
                    for ln in traceback.format_exc().splitlines()[-12:]:
                        log("    " + ln[:200])
                    results[tag] = "FAILED"
                    rc = 1

    log("")
    if args.probe_owners:
        log("owner probe done.")
    else:
        log("feed results: " + ", ".join(
            "{}={}".format(k, v) for k, v in results.items()))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
