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
    shared team view with ?<field>=<value> appended (drops :iid, a tab index),
    where the field is the view's own filter_field ("Owner Name" for Sales/OOB,
    "Owner & Office" for churn/activation) and the value is the office's matching
    slice value."""
    if o.is_override(view_key):
        return o.view_url(view_key)
    from urllib.parse import quote
    field = VIEW_META.get(view_key, {}).get("filter_field", OWNER_FIELD)
    value = o.slice_value(field)
    base = o.view_url(view_key).split("?")[0]
    return "{}?{}={}".format(base, quote(field), quote(value))


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


def _crop_to_last_colored_row(png: Path, leading: bool = False,
                              verbose: bool = False) -> bool:
    """Trim the image to END on the last rep row with data, cutting the empty gap
    + the uncoloured table below the rep list. Two modes (reports differ):

      leading=False (CHURN): last rep with a coloured cell in ANY period. Sparse
        products like INT have reps whose only activity is a later column — a
        leading-only rule would drop them (Megan 2026-07-21, Kendrick McClain).
      leading=True (ACTIVATION): last rep with data in the LEADING (0-7 Day)
        column only. The view is sorted 0-7 desc, so reps with no 0-7 activity
        sort to the bottom and should be trimmed (Megan 2026-07-21, end at Aylin).

    Best-effort: any doubt -> keep full."""
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

        if leading:
            # For each row, the x of its LEFTMOST coloured cell. Reps WITH
            # leading-column (0-7) data start their colour in that column; reps
            # without it (sorted to the bottom) start further right. The leading
            # column's x is the MODE of those leftmost-x values (most reps have
            # data there) — robust to the misaligned National-Average band (one
            # row, never the mode). Trim to the last row that starts at that x.
            from collections import Counter
            row_left = {}
            for y in range(0, H, 2):
                for x in range(0, W, 3):
                    if sat(px[x, y]):
                        row_left[y] = x
                        break
            if not row_left:
                return False
            buckets = Counter(round(x / 8) * 8 for x in row_left.values())
            x0 = buckets.most_common(1)[0][0]
            last = 0
            for y, lx in row_left.items():
                if abs(lx - x0) <= 12 and y > last:
                    last = y
        else:
            # Last row with a real RUN of coloured pixels (any column).
            last = 0
            for y in range(H):
                if sum(1 for x in range(0, W, 3) if sat(px[x, y])) > 8:
                    last = y
        if last <= 0:
            return False
        cut = min(H, last + 10)            # +10 keeps the cell's bottom border
        if cut >= H - 4:
            return False                    # nothing meaningful to trim
        im.crop((0, 0, W, cut)).save(png)
        if verbose:
            print("   ✂ cropped to last {} row ({} -> {}px)".format(
                "leading-col" if leading else "coloured", H, cut), flush=True)
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
    from automations.b2b_quality.run import apply_sort, _IFRAME

    meta = VIEW_META.get(view_key, {})
    url = _sliced_url(o, view_key)
    out = out_dir / "{}.png".format(view_key)
    spec = {"id": view_key, "title": view_key, "url": url}

    def after_load(page):
        # Activation carries no saved sort; click its measure sort glyph high->low
        # before the shot. Churn's saved view sorts itself.
        hdr = meta.get("sort_header")
        if not hdr:
            return
        # Wait for the rep table's sort column to RENDER before clicking — on a
        # cold load after_load fires before the viz hydrates, so the click misses
        # the header and the table shoots in default (alphabetical) order.
        try:
            page.frame_locator(_IFRAME).locator(
                'div.tab-vizHeader >> text="{}"'.format(hdr)).first.wait_for(
                state="visible", timeout=45_000)
            page.wait_for_timeout(1_500)   # let it settle before the click
        except Exception:  # noqa: BLE001 — apply_sort is still best-effort below
            pass
        apply_sort(page, hdr, clicks=meta.get("sort_clicks", 1), verbose=True)

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
            _crop_to_last_colored_row(
                out, leading=(meta.get("crop_mode") == "leading"), verbose=True)
        return out
    finally:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        cdp_pull._kill_ours()
