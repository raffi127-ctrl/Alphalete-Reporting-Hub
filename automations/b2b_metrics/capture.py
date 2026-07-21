"""Capture functions for the B2B Metrics runner — one per item KIND.

Each returns a Path to the artifact (PNG, or the .xlsx for the order log), or
raises (the runner's continue-on-failure logs + skips). These are thin adapters
over modules that already exist, so the runner is orchestration only:

  churn_tab_image   -> vantura_churn.shot  (Sheets export; runs anywhere)
  order_log_workbook-> att_order_log.run pull + xlsx.build  (Tableau; Lucy 2)
  payout_image      -> att_order_log.payout + box_order_log.png  (Lucy 2 for data)
  tableau_image     -> a Download->Image capture of a custom view  (Lucy 2)

Sheet-order-log data (order_log + payout) is pulled ONCE and cached on the
office for the run, so the 120MB ORDERLOG export isn't fetched twice.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from automations.b2b_metrics.offices import B2BOffice


# --- #4 / #5 : screenshots of the LUCY CHURN tab ---------------------------
def churn_tab_image(o: B2BOffice, which: str, out_dir: Path, log=print) -> Path:
    """#4 customer_churn = the tab's main block; #5 activation_by_rep = the rep
    chart at AE:AF. Both via the Sheets export endpoint (vantura_churn.shot)."""
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
    lines = clean.load_rows(csv, owner_prefix=o.owner.split()[0].upper()
                            if False else o.owner)
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


# --- #8 : the Activation-report-overview image -----------------------------
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
    bpng.render(tables, out,
                subtitle="Activated & Cancelled are for that posted week — pay "
                         "follows. Still Open = not yet posted, any week.")
    return out


# --- #1 / #2 / #3 / #9 : Tableau Download->Image ---------------------------
def tableau_image(o: B2BOffice, view_key: str, out_dir: Path,
                  owner_filter: bool = False, log=print) -> Path:
    """Capture one of the office's Tableau custom views as an image. LUCY 2 —
    Carlos's login carries the custom view's filters/sort. Reuses the same
    real-Chrome CDP session + Download->Image the other B2B captures use."""
    import time

    from patchright.sync_api import sync_playwright
    from urllib.parse import quote

    from automations.shared import tableau_patchright as tp
    from automations.tableau_screenshots.capture import capture_page
    from automations.vantura_churn import cdp_pull

    url = o.tableau_views[view_key]
    if owner_filter and o.metrics_filter_field.strip():
        base = url.split("?")[0]
        url = "{}?{}={}".format(base, quote(o.metrics_filter_field.strip()),
                                quote(o.sales_metrics_owner))
    out = out_dir / "{}.png".format(view_key)
    spec = {"id": view_key, "title": view_key, "url": url}

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
            capture_page(page, spec, out_dir, verbose=False)
        return out
    finally:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        cdp_pull._kill_ours()
