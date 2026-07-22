"""Capture functions for the B2B Metrics runner — one per item KIND.

Each returns a Path to the artifact (PNG, or the .xlsx for the order log), or
raises (the runner's continue-on-failure logs + skips). These are thin adapters
over modules that already exist, so the runner is orchestration only:

  tableau_image     -> owner-sliced Download->Image of a shared TEAM view (Lucy 2)
  order_log_workbook-> att_order_log.run pull + xlsx.build  (Tableau; Lucy 2)
  payout_image      -> att_order_log.payout + box_order_log.png  (Lucy 2 for data)

Sheet-order-log data (order_log + payout) is pulled ONCE and cached on the
office for the run, so the 120MB ORDERLOG export isn't fetched twice.

ALL Tableau items (#1/#2/#3-5/#8) go through the SAME path: load the shared team
view with ?Owner Name=<owner> appended, then apply the per-view sort/crop from
offices.VIEW_META. The sort click + crop-to-last-data-row are reused from
b2b_quality (the module that proved them); this runner no longer routes through
b2b_quality's Carlos-hardcoded SPECS, so the owner slice actually takes effect.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from automations.b2b_metrics.offices import B2BOffice, OWNER_FIELD, VIEW_META


# --- #6 / #7 : screenshots of the LUCY CHURN tab ---------------------------
def churn_tab_image(o: B2BOffice, which: str, out_dir: Path, log=print) -> Path:
    """#6 customer_churn = the tab's main block (0-30 Day Rolloff List); #7
    activation_by_rep = the rep chart at AE:AF. Both via the Sheets export
    endpoint (vantura_churn.shot)."""
    from automations.recruiting_report.fill import open_by_key
    from automations.vantura_churn import shot

    ws = open_by_key(o.sheet_id).worksheet(o.churn_tab)
    if which == "customer_churn":
        rng = shot.visible_range(ws)
        out = out_dir / "customer_churn.png"
    elif which == "activation_by_rep":
        col = ws.get("AE1:AE200")
        last = max((i for i, r in enumerate(col, 1) if r and r[0].strip()),
                   default=0)
        # Rep rows sit BELOW the "Rep Name" header (row 15). If there's nothing
        # there, the churn board hasn't been written yet — DON'T post a 2-row
        # blank (2026-07-22: that "posted" empty and read as missing). Raise so
        # the runner skips + flags it for a rerun instead.
        if last <= 15:
            raise ValueError(
                "activation_by_rep: no rep rows on {!r} (churn board not "
                "written yet) — skip rather than post blank".format(o.churn_tab))
        rng = "AE14:AF{}".format(last)
        out = out_dir / "activation_by_rep.png"
    else:
        raise ValueError("unknown churn image {!r}".format(which))
    shot.render(ws, out, rng=rng)
    return out


# --- shared order data (pulled once) ---------------------------------------
_LINE_CACHE: dict = {}


def _order_lines(o: B2BOffice, out_dir: Path, log=print):
    """The un-pivoted AT&T sales lines for this owner — pulled ONCE per run
    (order_log + payout both need them)."""
    if o.key in _LINE_CACHE:
        return _LINE_CACHE[o.key]
    from automations.att_order_log import clean, run as al_run
    today = dt.date.today()
    csv = out_dir / "orderlog_{}.csv".format(today.isoformat())
    al_run._pull(today, csv, log=log)
    lines = clean.load_rows(csv, owner_prefix=o.owner)
    _LINE_CACHE[o.key] = lines
    return lines


# --- #6 : the order-log workbook -------------------------------------------
def order_log_workbook(o: B2BOffice, out_dir: Path, log=print) -> Path:
    from automations.att_order_log import pending, xlsx
    lines = _order_lines(o, out_dir, log=log)
    # Pending-by-Rep tab (Carlos 2026-07-22): unpaid pay-week orders from the
    # office's RAW tab. Additive — a Sheet hiccup skips the tab, never the book.
    pend = pending.read_for_key(o.sheet_id, log=log)
    out = out_dir / "ATT Order Log {}.xlsx".format(
        dt.date.today().strftime("%m-%d-%Y"))
    xlsx.build(lines, out, today=dt.date.today(), pending=pend)
    return out


# --- #7 : the Activation-report-overview image -----------------------------
def payout_image(o: B2BOffice, out_dir: Path, log=print) -> Path:
    """Two-week Activated/Cancelled/Still-Open per rep, rendered like BOX's
    payout image. Reuses box_order_log.png with the AT&T rows remapped to the
    keys that renderer expects."""
    from automations.att_order_log import payout as ap
    from automations.box_order_log import png as bpng

    lines = _order_lines(o, out_dir, log=log)
    tables = ap.build_week_tables(lines, dt.date.today())
    # box png's rows use keys: rep / posted / canceled / pending. Map ours.
    for wk in ("last", "this"):
        for r in tables[wk]["rows"]:
            r["posted"] = r.pop("activated")
            r["pending"] = r.pop("open")
    out = out_dir / "activation_overview.png"
    # Swap the box renderer's column HEADERS to AT&T's for this render — the
    # count key stays "posted" but the header reads "Posted" (Carlos 2026-07-20),
    # not BOX's "Accepted by Supplier". Restored after, so BOX's own report is
    # untouched.
    saved_cols = list(bpng.COLS)
    bpng.COLS[:] = [
        ("Rep Name", "rep", "left"),
        ("Posted", "posted", "center"),
        ("Cancelled", "canceled", "center"),
        ("Still Open", "pending", "center"),
    ]
    try:
        bpng.render(tables, out,
                    subtitle="Posted & Cancelled are for that posted week — pay "
                             "follows. Still Open = not yet posted, any week.")
    finally:
        bpng.COLS[:] = saved_cols
    return out


# --- #1 / #2 / #3-5 / #8 : Tableau Download->Image, owner-sliced ------------
def _sliced_url(o: B2BOffice, view_key: str) -> str:
    """The URL to capture. A per-office OVERRIDE view is a saved view already
    filtered to the owner — captured as-is, no slice appended. Otherwise it's the
    shared team view with ?Owner Name=<owner> appended (drops :iid, a tab index)."""
    if o.is_override(view_key):
        return o.view_url(view_key)
    from urllib.parse import quote
    base = o.view_url(view_key).split("?")[0]
    return "{}?{}={}".format(base, quote(OWNER_FIELD), quote(o.owner))


# Which views need the sort/crop rep-table handling (Activation + the 3 Churn
# products). All views capture the same way (cdp_pull Download→Image — the path
# that reliably auths via Carlos's warm Chrome on Lucy 2); these just get the
# extra sort (Activation) + crop-to-last-rep afterward.
_REP_TABLE_VIEWS = ("activation_rate", "churn_wireless", "churn_int", "churn_air")

# DIAGNOSTIC 2026-07-21: churn came back as National-Average-only. Download→Image
# exports the WHOLE dashboard, so the rep table should be in the PNG — meaning the
# crop is trimming it off. `runner --no-crop` sets B2B_SKIP_CROP=1 (read at call
# time) to capture uncropped and confirm.
import os as _os


def _crop_to_last_colored_row(png: Path, verbose: bool = False) -> bool:
    """Trim the image to END on the last rep that has data in the LEADING (0-30
    Day) column — matching Megan's rule "end with the last row that has data in
    the 0-30 day section". Reps whose 0-30 cell is blank (data only in later
    columns) sort to the bottom and are dropped, along with the empty gap and the
    uncoloured Disconnect-Reason table below the rep list.

    Robust to the National-Average band sitting at a DIFFERENT x than the rep
    columns: the leading rep column is found by FREQUENCY — the rep data columns
    are coloured in dozens of rows, the National Average in only one or two — so
    the leftmost high-frequency colour stripe is the rep 0-30 column. No
    fixed column count, no sort-check. Best-effort: any doubt -> keep full."""
    try:
        from PIL import Image
    except ImportError:
        return False
    try:
        im = Image.open(png).convert("RGB")
        W, H = im.size
        px = im.load()

        def sat(p):
            return max(p) - min(p) > 45 and max(p) > 90

        # How many rows is each column coloured in? Rep data columns light up in
        # dozens of rows; the small misaligned National-Average marker/band cells
        # in only a couple — so a column colored in MANY rows is a rep data
        # column, and the 0-30 Day column is the most-populated (nearly every rep
        # has a 0-30 value; a 0-30-sorted view puts the blanks last).
        col_rows = [0] * W
        for x in range(0, W, 2):
            c = 0
            for y in range(0, H, 2):
                if sat(px[x, y]):
                    c += 1
            col_rows[x] = c
        peak = max(col_rows)
        if peak < 20:                      # no real rep table found
            return False
        # Leftmost column that is substantially populated (>= half the peak) = the
        # 0-30 column; a NARROW window around it so we never bleed into the 30/60
        # columns (which would re-include the blank-0-30 reps we want to drop).
        lead = next(x for x in range(0, W, 2) if col_rows[x] >= 0.5 * peak)
        a, b = max(0, lead - 4), lead + 22

        last = 0
        for y in range(H):
            if any(sat(px[x, y]) for x in range(a, b, 2)):
                last = y
        if last <= 0:
            return False
        cut = min(H, last + 8)              # +8 keeps the cell's bottom border
        if cut >= H - 4:
            return False                    # nothing meaningful to trim
        im.crop((0, 0, W, cut)).save(png)
        if verbose:
            print("   ✂ cropped to last 0-30 rep row ({} -> {}px)".format(
                H, cut), flush=True)
        return True
    except Exception as e:  # noqa: BLE001 — a bad crop must never lose the image
        if verbose:
            print("   ⚠ crop failed ({}) — full length kept".format(
                type(e).__name__), flush=True)
        return False


def tableau_image(o: B2BOffice, view_key: str, out_dir: Path, log=print) -> Path:
    """Capture one Tableau view for this office (owner-sliced, or a per-office
    override view captured as-is). LUCY 2 — Carlos's login carries the views."""
    import time

    from patchright.sync_api import sync_playwright

    from automations.shared import tableau_patchright as tp
    from automations.tableau_screenshots.capture import capture_page
    from automations.vantura_churn import cdp_pull
    from automations.b2b_quality.run import apply_sort

    meta = VIEW_META.get(view_key, {})
    url = _sliced_url(o, view_key)
    out = out_dir / "{}.png".format(view_key)
    spec = {"id": view_key, "title": view_key, "url": url}

    def after_load(page):
        # Activation carries no saved sort; click its measure sort glyph high->low
        # before the shot. Churn's saved view sorts itself.
        if meta.get("sort_header"):
            apply_sort(page, meta["sort_header"], verbose=True)

    cdp_pull._kill_ours()
    proc = cdp_pull._launch()
    try:
        with sync_playwright() as p:
            # Chrome's remote-debugging port isn't up the instant _launch()
            # returns. A single fixed sleep(20) then one connect sometimes hit
            # ECONNREFUSED and DROPPED that item (activation_rate, 2026-07-22).
            # Poll instead — connect as soon as the port answers, up to ~50s — so
            # a slow start retries rather than failing the whole item.
            browser = None
            for attempt in range(10):
                time.sleep(5)
                try:
                    browser = p.chromium.connect_over_cdp(
                        "http://127.0.0.1:{}".format(cdp_pull.CDP_PORT))
                    break
                except Exception as e:  # noqa: BLE001 — retry a not-yet-up port
                    if attempt == 9:
                        raise
                    log("  [cdp] port not up yet (try {}/10): {}".format(
                        attempt + 1, type(e).__name__))
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            tp._ensure_tableau_authenticated(page, verbose=False,
                                             allow_form_login=True)
            capture_page(page, spec, out_dir, after_load=after_load, verbose=False)
        # Crop to the last populated rep row (Activation + Churn); best-effort.
        if meta.get("data_cols") and not _os.environ.get("B2B_SKIP_CROP"):
            _crop_to_last_colored_row(out, verbose=True)
        return out
    finally:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        cdp_pull._kill_ours()
