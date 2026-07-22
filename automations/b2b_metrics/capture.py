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
                   default=15)
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
    from automations.att_order_log import xlsx
    lines = _order_lines(o, out_dir, log=log)
    out = out_dir / "ATT Order Log {}.xlsx".format(
        dt.date.today().strftime("%m-%d-%Y"))
    xlsx.build(lines, out, today=dt.date.today())
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
    """The shared team view with ?Owner Name=<owner> appended (drops :iid — a
    tab index, irrelevant to the slice)."""
    from urllib.parse import quote
    base = o.view_url(view_key).split("?")[0]
    return "{}?{}={}".format(base, quote(OWNER_FIELD), quote(o.owner))


def tableau_image(o: B2BOffice, view_key: str, out_dir: Path, log=print) -> Path:
    """Capture one shared team view, sliced to this office by Owner Name. LUCY 2
    — Carlos's login carries the team custom view; the URL slice narrows it to
    the office. Reuses the real-Chrome CDP session + Download->Image the other
    B2B captures use, plus b2b_quality's sort + crop for Activation/Churn."""
    import time

    from patchright.sync_api import sync_playwright

    from automations.shared import tableau_patchright as tp
    from automations.tableau_screenshots.capture import capture_page
    from automations.vantura_churn import cdp_pull
    from automations.b2b_quality.run import apply_sort, crop_to_last_data_row

    meta = VIEW_META.get(view_key, {})
    url = _sliced_url(o, view_key)
    out = out_dir / "{}.png".format(view_key)
    spec = {"id": view_key, "title": view_key, "url": url}

    def after_load(page):
        # Activation carries no saved sort; click its measure sort glyph high->low
        # (the manual step the VA does) before the shot. Churn's view sorts itself.
        if meta.get("sort_header"):
            apply_sort(page, meta["sort_header"], verbose=True)

    cdp_pull._kill_ours()
    proc = cdp_pull._launch()
    time.sleep(20)
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(
                "http://127.0.0.1:{}".format(cdp_pull.CDP_PORT))
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            tp._ensure_tableau_authenticated(page, verbose=False,
                                             allow_form_login=True)
            capture_page(page, spec, out_dir, after_load=after_load, verbose=False)
        # Crop to the last populated rep row (Activation + Churn); best-effort.
        if meta.get("data_cols"):
            crop_to_last_data_row(out, meta["data_cols"], verbose=True)
        return out
    finally:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        cdp_pull._kill_ours()
