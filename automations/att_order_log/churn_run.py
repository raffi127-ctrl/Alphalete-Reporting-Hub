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
#
# ONE VIEW FOR EVERYTHING since 2026-08-30. It used to be one view PER PRODUCT,
# because the crosstab carried an owner column (so owners split in code) but no
# product column (so products could only be separated by the view's own filter).
# That stopped being true: ATTTRACKER-B2B gained a "Product Type (Broken Out)"
# row dimension, which took Rep's place in the three ALLTEAM* per-product views
# and broke all 12 feeds on 8/29 — churn_shape could not find 'Rep' at all.
#
# ALLTEAMSEXP ("all teams, expanded") carries Owner AND Rep AND Product Type in
# one sheet, so the product now splits in code exactly like the owner does, and
# the same argument that gave us one pull for N offices gives us one pull for N
# products: 1 pull/day total, down from 3. Probed live before wiring (see
# churn_shape.PRODUCT_TYPES for the value mapping and how it was verified).
# Same three tab names on every office board, so tab lives here, not per office.
EXPANDED_URL = (_T + "ATTTRACKER-B2B/CHURNRATES/"
                "982d0e4e-d8ed-4574-8a4c-86fdbc345b5c/ALLTEAMSEXP?:iid=1")

PRODUCTS = {
    "wireless": {"label": "Wireless Churn", "tab": "Lucy Wireless Churn",
                 "url": EXPANDED_URL},
    "new_int": {"label": "New Internet Churn", "tab": "Lucy New INT Churn",
                "url": EXPANDED_URL},
    "air": {"label": "AIR Churn", "tab": "Lucy AIR Churn",
            "url": EXPANDED_URL},
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


def _merge_onboarded():
    """Add B2B offices onboarded via office_onboarding (the same committed JSON
    b2b_metrics.offices merges). owner is the UPPER bare name the D2D parser
    matches; verify a new office with `--probe-owners` before trusting it.
    STRICT NO-OP when the file is absent."""
    import json as _json
    from pathlib import Path as _Path
    f = _Path(__file__).resolve().parents[1] / "b2b_metrics" / "onboarded_offices.json"
    if not f.exists():
        return
    try:
        rows = _json.loads(f.read_text())
    except Exception:
        return
    for r in rows:
        key = (r.get("key") or "").strip()
        if not key or key in OFFICES:
            continue
        owner = (r.get("owner") or "").strip().upper()
        sid = r.get("sheet_id") or ""
        if owner and sid:
            OFFICES[key] = {"label": r.get("label") or key.title(),
                            "owner": owner, "sheet_id": sid}


_merge_onboarded()


def _probe_columns(page, tag: str, spec: dict, log=print) -> None:
    """READ-ONLY: download the crosstab and print its shape, ONE FIELD PER LINE.

    Why one per line: these logs are read remotely through `lucy logtail`, which
    truncates every line to 200 chars. On 2026-08-29 that truncation hid the
    back half of the header twice while att_churn was being diagnosed, and the
    visible half was misleading on its own. A column per line is unhidable.

    Writes nothing but its own temp csv - no Sheet, no Slack, no manifest.
    """
    from automations.recruiting_report.opt_phase import drive_crosstab_dialog

    from . import churn_shape

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    raw = WORK_DIR / "{}_probe_raw.csv".format(tag)
    sheet = spec.get("crosstab_sheet") or CROSSTAB_SHEET
    log("  [{}] crosstab download (probe) — sheet {!r}...".format(tag, sheet))
    drive_crosstab_dialog(page, spec["url"], sheet, raw, verbose=False)

    rows = churn_shape.read_crosstab(raw)
    hdr = [str(h or "").strip().lstrip("\ufeff") for h in rows[0]]
    log("  [{}] HEADER - {} column(s), {} data row(s)".format(
        tag, len(hdr), max(0, len(rows) - 1)))
    for i, h in enumerate(hdr):
        log("    col[{:02d}] {!r}".format(i, h))

    for ri, row in enumerate(rows[1:4], 1):
        log("    --- sample row {} ---".format(ri))
        for i, v in enumerate(row):
            log("      [{:02d}] {!r}".format(i, str(v or "")[:60]))

    # Distinct values of the leading (dimension) columns - this is what tells us
    # whether Rep and Product Type are really in here and how they are spelled.
    for ci in range(min(4, len(hdr))):
        seen = []
        for row in rows[1:]:
            if ci >= len(row):
                continue
            val = str(row[ci] or "").split("\n")[0].strip()
            if val and val not in seen:
                seen.append(val)
            if len(seen) >= 15:
                break
        log("    distinct col[{:02d}] {!r} ({}{}):".format(
            ci, hdr[ci], len(seen), "+" if len(seen) >= 15 else ""))
        for val in seen:
            log("        {!r}".format(val))


def _download_raw(page, url: str, dest: Path, log=print) -> Path:
    """Crosstab-download ONE view. Split out from the adapt step because the
    expanded view now serves every product, so the pull happens once per RUN
    while the adapt happens once per PRODUCT."""
    from automations.recruiting_report.opt_phase import drive_crosstab_dialog

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    log("  crosstab download…")
    drive_crosstab_dialog(page, url, CROSSTAB_SHEET, dest, verbose=False)
    return dest


def _adapt_raw(raw: Path, tag: str, log=print) -> Path:
    """Select `tag`'s product out of a pulled crosstab and rename its header to
    D2D naming. No browser, no network — pure file work."""
    from . import churn_shape

    adapted = WORK_DIR / "{}_adapted.csv".format(tag)
    info = churn_shape.adapt(raw, adapted,
                             keep=churn_shape.PRODUCT_TYPES.get(tag))
    log("  [{}] {} rows; periods {}".format(
        tag, info["rows"], info["periods"]))
    return adapted


def _pull_and_adapt(page, tag: str, spec: dict, log=print) -> Path:
    """Download + adapt in one step (the single-product path)."""
    raw = WORK_DIR / "{}_raw.csv".format(tag)
    _download_raw(page, spec["url"], raw, log=log)
    return _adapt_raw(raw, tag, log=log)


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
    ap.add_argument("--crosstab-sheet", default=None, metavar="NAME",
                    dest="crosstab_sheet",
                    help="probe a DIFFERENT worksheet than %r. Only meaningful "
                         "with --probe-columns: it lets the probe point at any "
                         "ATTTRACKER-B2B view, not just the churn ones (e.g. "
                         "B2BCancelRates' 'Cancel Rates Sheet')." % CROSSTAB_SHEET)
    ap.add_argument("--dry-run", action="store_true", dest="dry_run",
                    help="pull + parse + report, write NOTHING. Overrides "
                         "--fill, so it can preview a scheduled run: `lucy "
                         "rerun att_churn` appends flags AFTER base_args, and "
                         "att_churn's base_args are ['--fill'].")
    ap.add_argument("--probe-columns", action="store_true", dest="probe_columns",
                    help="READ-ONLY: print the crosstab's real header, sample "
                         "rows and distinct dimension values, one field per "
                         "line, then stop. Writes nothing.")
    ap.add_argument("--probe-owners", action="store_true", dest="probe_owners",
                    help="pull each TEAM view once and print the distinct owners "
                         "it contains (no slice, no write) — confirm an office's "
                         "owner spelling before wiring it")
    ap.add_argument("--url", default=None, metavar="URL",
                    help="pull this view URL instead of the wired one, for the "
                         "product named by --only. Lets a CANDIDATE view be "
                         "checked with --probe-owners before anything is "
                         "rewired (a wrong URL in PRODUCTS would poison the "
                         "next daily run for that product).")
    ap.add_argument("--today", default=None, metavar="YYYY-MM-DD")
    args = ap.parse_args(argv)

    # The probe is READ-ONLY, and it has to stay that way even when it is
    # invoked through `lucy rerun att_churn`, which appends its flags AFTER the
    # scheduled base_args (["--fill"]). Without this, a probe run would reach
    # _write_manifest and mark the source manifest clean.
    if args.probe_columns:
        args.fill = False
        args.png = False

    # --dry-run BEATS --fill wherever it appears. Same reason as above: the
    # scheduled base_args carry --fill, so without an explicit override there is
    # no way to preview this report on the machine that actually runs it.
    if args.dry_run:
        if args.fill or args.png:
            print("--dry-run overrides --fill/--png: nothing will be written")
        args.fill = False
        args.png = False
    if args.png:
        args.fill = True          # render reads the tab the fill just wrote

    today = (dt.date.fromisoformat(args.today) if args.today
             else dt.date.today())
    products = ({args.only: PRODUCTS[args.only]} if args.only else PRODUCTS)
    if args.url:
        if not args.only:
            ap.error("--url needs --only <product>, so it is unambiguous which "
                     "view is being replaced")
        products = {args.only: dict(PRODUCTS[args.only], url=args.url)}
    if args.crosstab_sheet:
        products = {k: dict(v, crosstab_sheet=args.crosstab_sheet)
                    for k, v in products.items()}
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
    gaps = {}             # "office_product" -> owner the view no longer carries
    raw_by_url = {}       # view url -> the ONE raw csv pulled for it THIS run

    # Pull each ALL-TEAM product view ONCE (its own fresh browser + one retry —
    # the CDP Chrome on Lucy 2 dies mid-run intermittently, so isolating each pull
    # keeps one death from stranding the rest), then slice every office's owner out
    # of that single pull IN CODE. 3 pulls total for N offices; no per-office view.
    with cdp_pull._cdp_lock(label="att_order_log churn", log=log), sync_playwright() as p:
        for pkey, pv in products.items():
            log("")
            log("=== {} ({}) ===".format(pv["label"], pkey))
            adapted = None
            # The expanded view serves every product, so once it has been pulled
            # the remaining products are pure file work — no second Chrome. Keyed
            # per RUN (never by "the file exists"), so a stale csv from an
            # earlier day can never be mistaken for today's pull.
            cached_raw = raw_by_url.get(pv["url"])
            if cached_raw is not None:
                try:
                    log("  [{}] reusing this run's {} pull".format(
                        pkey, CROSSTAB_SHEET))
                    adapted = _adapt_raw(cached_raw, pkey, log=log)
                except Exception:  # noqa: BLE001 — one product must not kill the rest
                    log("  {} adapt FAILED:".format(pkey))
                    for ln in traceback.format_exc().splitlines()[-12:]:
                        log("    " + ln[:200])
            # Already served from this run's pull? Then there is nothing to
            # download and no browser to launch.
            attempts = () if cached_raw is not None else (1, 2)
            for attempt in attempts:
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
                    if args.probe_columns:
                        _probe_columns(page, pkey, pv, log=log)
                        adapted = "probed"   # sentinel: not a real pull
                        break
                    raw = WORK_DIR / "{}_raw.csv".format(pkey)
                    _download_raw(page, pv["url"], raw, log=log)
                    raw_by_url[pv["url"]] = raw
                    adapted = _adapt_raw(raw, pkey, log=log)
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

            if args.probe_columns:
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
                    # Is this office simply NOT IN the view any more? These are
                    # Carlos's TEAM views (8 owners), not the whole site: an
                    # office that leaves his captaincy drops out of them
                    # overnight. That is what happened to Atef — he split off on
                    # 2026-08-18 and every one of his feeds came back empty on
                    # 8/19 with "parsed 0 reps". It is a SOURCE gap, not a break
                    # in this code, and it lasts until someone saves an all-team
                    # view — so failing the whole report every morning would
                    # leave a permanently red card that stops meaning anything
                    # ([[feedback_dead-source-pings-not-fails-the-card]]). Ping
                    # once per run, by name, and keep the exit code clean.
                    try:
                        owners = _distinct_owners(adapted)
                    except Exception:  # noqa: BLE001 — can't tell: treat as break
                        owners = {}
                    if owners and office["owner"] not in owners:
                        log("  {} SOURCE GAP — {!r} is not in this view; it "
                            "carries {} owner(s): {}".format(
                                tag, office["owner"], len(owners),
                                ", ".join(sorted(owners))))
                        gaps[tag] = office["owner"]
                        continue
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
        _write_manifest(results, fill=args.fill, gaps=gaps, log=log)
    return rc


def _split_tag(tag: str) -> tuple:
    """'carlos_new_int' -> ('carlos', 'new_int'). Matched against the OFFICES keys
    rather than split on '_', because product keys contain underscores too."""
    for okey in OFFICES:
        if tag.startswith(okey + "_"):
            return okey, tag[len(okey) + 1:]
    return None, None


# The gap manifest gets its OWN id. The orchestrator VERIFIES att_churn against
# the "att_churn" manifest (verify: {type: manifest}), and run_manifest keys its
# file by report_id alone — writing the gap under the same id would overwrite the
# feed manifest and tell reconcile the run filled nothing.
SOURCE_MANIFEST_ID = "att_churn_source"


def _write_source_manifest(gaps: dict, *, log=print) -> None:
    """An office the pulled view no longer carries: ping once, card stays green.

    Cleared (mark_clean) the moment every office is back in its view, so the
    `drop-att_churn_source` thread closes itself instead of sitting open."""
    try:
        from automations.shared import run_manifest
    except Exception as e:  # noqa: BLE001 — bookkeeping never fails a run
        log("source manifest skipped ({}: {})".format(type(e).__name__, str(e)[:120]))
        return
    if not gaps:
        try:
            run_manifest.mark_clean(SOURCE_MANIFEST_ID, kind="source")
        except Exception:  # noqa: BLE001
            pass
        return
    owners = sorted(set(gaps.values()))
    tags = sorted(gaps)
    try:
        run_manifest.write_manifest(
            SOURCE_MANIFEST_ID, failed=tags, retry_args=[], kind="source",
            note="{} feed(s) had nothing to slice: {} is not in the churn "
                 "view(s) this report pulls".format(len(tags), ", ".join(owners)),
            remediation=run_manifest.make_remediation(
                reason="{} has no rows in the CarlosTEAM* CHURNRATES views. "
                       "Those views carry Carlos's team only, so an office that "
                       "leaves his captaincy drops out of them the next morning "
                       "(Atef split off 2026-08-18; his feeds went empty 8/19). "
                       "The pull and the parser are fine — there is simply "
                       "nothing of theirs in the crosstab.".format(
                           ", ".join(owners)),
                fix="In Tableau, under the identity that owns these views "
                    "(Carlos, on Lucy 2), save one custom view per product off "
                    "ATTTRACKER-B2B/CHURNRATES with the product filter kept and "
                    "the captain/team filter CLEARED, then point PRODUCTS[*]"
                    "['url'] in automations/att_order_log/churn_run.py at them. "
                    "Filtering by the office's own team is not an option yet: "
                    "SmartCircle has not created \"Atef's Team\" in the "
                    "B2B Captain's Teams (SFDC) field.",
                link=PRODUCTS["wireless"]["url"],
                message="The B2B churn views we pull (CarlosTEAMWireless / "
                        "CarlosTEAMNewINTEXP / CarlosTEAMAIREXP) only contain "
                        "Carlos's team. Since Atef left that captaincy his reps "
                        "are not in them, so his Wireless / New INT / AIR churn "
                        "tabs cannot be filled. Could we get an all-team version "
                        "of each of those three views (same product filter, no "
                        "team filter)?"),
        )
        log("source gap: {} feed(s) — {} (card stays green; pinged once)".format(
            len(tags), ", ".join(tags)))
    except Exception as e:  # noqa: BLE001
        log("source manifest skipped ({}: {})".format(type(e).__name__, str(e)[:120]))


def _write_manifest(results: dict, *, fill: bool, gaps: dict = None,
                    log=print) -> None:
    """Record per-feed outcomes so the orchestrator can RECONCILE this run instead
    of trusting exit 0 (Megan 2026-07-30 — att_churn had verify:null, so a run that
    exited clean having filled nothing read as DONE).

    Only a --fill run writes the manifest: a dry-run touches no tab, so letting it
    stamp `ok=true` would hand reconcile a clean bill for a run that wrote nothing
    (and reconcile's freshness gate keys on the date, so a 10am dry-run would
    otherwise overwrite the 4am fill's real result).

    Best-effort — a manifest problem must never change this run's exit code."""
    if not fill:
        return
    _write_source_manifest(gaps or {}, log=log)
    if not results:
        return
    try:
        from automations.shared import run_manifest

        failed = sorted(t for t, v in results.items() if v != "ok")
        ok_units = sorted(t for t, v in results.items() if v == "ok")
        # Narrow the retry to exactly what failed. args_override REPLACES base_args
        # in the orchestrator, so --fill must be carried explicitly or the retry
        # would dry-run and write nothing.
        retry = ["--fill"]
        offs = {o for o, _ in (_split_tag(t) for t in failed) if o}
        prods = {p for _, p in (_split_tag(t) for t in failed) if p}
        if len(offs) == 1:
            retry += ["--office", next(iter(offs))]
        if len(prods) == 1:
            retry += ["--only", next(iter(prods))]

        run_manifest.write_manifest(
            "att_churn", failed=failed, succeeded=ok_units, kind="feed",
            retry_args=retry,
            note=("all {} feed(s) filled".format(len(ok_units)) if not failed else
                  "{} of {} feed(s) failed: {}".format(
                      len(failed), len(results), ", ".join(failed))),
        )
        log("manifest: {}/{} feed(s) ok{}".format(
            len(ok_units), len(results),
            "" if not failed else " · retry args {}".format(" ".join(retry))))
    except Exception as e:  # noqa: BLE001 — never let bookkeeping fail the run
        log("manifest write skipped ({}: {})".format(type(e).__name__, str(e)[:120]))


if __name__ == "__main__":
    raise SystemExit(main())
