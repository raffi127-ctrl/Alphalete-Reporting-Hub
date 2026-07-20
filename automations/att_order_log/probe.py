"""Schema probe for Carlos's ATT B2B Order Log — RUN ON LUCY 2.

Why a probe and not just building the report: Carlos's spec arrived as a Loom
walkthrough plus a screenshot. The screenshot shows ~17 columns and a handful of
DTR statuses, but "everything that should stay on here" (his words) is a claim
about the FULL export, not about the visible rows. Guessing the column set from a
screenshot is how you ship a log that silently drops a column nobody noticed was
missing until a month later. So: pull the real crosstab once, print what is
actually in it, then write the renderer against that.

WHAT IT REPORTS
  * the exact header row (index + name), so run.py can look columns up by LABEL
    (CLAUDE.md: no hardcoded indices — templates change, labels survive)
  * distinct `DTR Status (enriched)` values + counts. This is the load-bearing
    one: Carlos gave a colour rule for six statuses (Posted / Delivered /
    Shipped / Porting Issue / Cancelled / Disconnected). Any status in the export
    that is NOT in that list has no colour and would render blank-on-white, which
    reads as "no status" rather than "unmapped". We need the real list to know
    whether his six are exhaustive.
  * which of the merged row-header columns actually arrive blank on continuation
    rows, to confirm vantura_churn.compute._GROUP_COLS forward-fills the right
    set. Carlos: "it's just for these three" (Order Date / Customer Name / SPM) —
    _GROUP_COLS fills seven. Filling a column that is genuinely blank per-line
    would invent data, so this prints per-column blank counts to settle it.

LUCY 2 ONLY. The view is Carlos's custom view (CarlosLocalOfficeEXPANDEDCHURN)
and Lucy 2 is the machine signed in as Carlos; on Lucy 1 / the laptop the export
comes back as somebody else's slice (same trap documented in
vantura_churn/cdp_pull.probe_activation_rates). Do NOT run this on the laptop —
a laptop scrape also evicts the mini's ownerville session holder.

    lucy --machine "Lucy 2" rerun att_order_log_probe

Findings land on the 'ATT Order Log Diag' tab of the Vantura diag sheet, so they
are readable from any machine without shelling into the mini.
"""
from __future__ import annotations

import collections
import datetime as dt
import traceback
from pathlib import Path

# Carlos's own view, from his 2026-07-19 Slack message. The base ORDERLOG view
# takes Start/End Date URL params (vantura_churn.pull), but Carlos pointed at
# THIS custom view and said "this tab is everything that should stay on here" —
# so the probe reads his view, and run.py can decide later whether the base view
# + a date window reproduces it exactly (cheaper + not Lucy-2-bound if so).
VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER-B2B/ORDERLOG/415114d7-6d65-4415-a61c-3658fab96f6b/"
    "CarlosLocalOfficeEXPANDEDCHURN?:iid=2"
)
CROSSTAB_SHEET = "Order Log"

# The colour rule from the Loom (0:59-1:45). Kept here, next to the probe that
# validates it, rather than in the renderer — the probe's job is to tell us
# whether this mapping covers the real data.
STATUS_COLOURS = {
    "Posted": "green",          # "if it could stay labeled as Posted, because
                                #  everything else calls it posted" — do NOT
                                #  rename to "Active".
    "Delivered": "yellow",      # "pending"
    "Shipped": "yellow",
    "Porting Issue": "yellow",
    "Cancelled": "red",
    "Disconnected": "red",
}

DIAG_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
DIAG_TAB = "ATT Order Log Diag"

# Where to hunt for the churn views. Carlos on the Loom (3:07-3:23): "why does
# this one have two wireless churns? I'm not sure what the difference is between
# these two… I would want the wireless churn 0-30 day, whichever one's the
# accurate one." He can't tell them apart and neither can we from a screenshot,
# so step one is enumerating candidates with their real URLs; step two is
# diffing their rep rows. Picking blind puts wrong churn numbers in his channel,
# which is the one failure mode that destroys trust in the whole report.
#
# SEARCH THE WHOLE SITE, not just ATTTRACKER-B2B (Megan 2026-07-19: "I think the
# churn for b2b lives somewhere else on tableau"). Precedent backs her up — the
# D2D churn is NOT in the D2D tracker's obvious spot either; office_metrics
# points at ATTTRACKER2_1-D2D/CHURN/INTAllTeams + WirelessAllTeams, which are
# all-teams views the per-office reports slice in Python. So a workbook-scoped
# listing could easily come back empty-handed and we'd wrongly conclude the
# view doesn't exist.
WORKBOOK_VIEWS_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/workbooks/"
    "ATTTRACKER-B2B/views"
)
# Site-wide view search. Tableau's search page takes the term in the URL, so we
# can pull the churn candidates across every workbook in one load.
SITE_SEARCH_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/search?searchString={term}"
)
SEARCH_TERMS = ("churn", "wireless churn", "b2b churn")


def _describe(grid, rec) -> None:
    """Print the schema of a loaded crosstab grid."""
    if not grid:
        rec("EMPTY GRID — the export came back with no rows.")
        return
    hdr = [str(h or "").strip().lstrip("﻿") for h in grid[0]]
    rows = grid[1:]
    rec("")
    rec("=== HEADER ({} columns, {} data rows) ===".format(len(hdr), len(rows)))
    for i, h in enumerate(hdr):
        rec("  [{:>2}] {}".format(i, h))

    # Distinct DTR statuses — the colour map's coverage check.
    rec("")
    rec("=== DTR Status (enriched) — distinct values ===")
    if "DTR Status (enriched)" in hdr:
        si = hdr.index("DTR Status (enriched)")
        counts = collections.Counter(
            str(r[si]).strip() for r in rows
            if si < len(r) and str(r[si] or "").strip())
        for val, n in counts.most_common():
            mapped = STATUS_COLOURS.get(val)
            flag = "  <-- UNMAPPED, no colour rule" if not mapped else ""
            rec("  {:>5}  {:<28} {}{}".format(n, val, mapped or "-", flag))
        missing = [s for s in STATUS_COLOURS if s not in counts]
        if missing:
            rec("  (colour rule covers, but export has none of: {})".format(
                ", ".join(missing)))
    else:
        rec("  !! column 'DTR Status (enriched)' NOT in this export")

    # Blank-rate per column: settles which columns really need forward-fill.
    rec("")
    rec("=== blank rate per column (merged row-headers show as high blank) ===")
    for i, h in enumerate(hdr):
        blanks = sum(1 for r in rows
                     if i >= len(r) or not str(r[i] or "").strip())
        pct = (100.0 * blanks / len(rows)) if rows else 0.0
        rec("  [{:>2}] {:<34} {:>5} blank  ({:>5.1f}%)".format(
            i, h[:34], blanks, pct))

    rec("")
    rec("=== first 12 data rows (raw, pre-fill) ===")
    for r in rows[:12]:
        cells = [str(c or "")[:18] for c in r[:12]]
        rec("  " + " | ".join("{:<18}".format(c) for c in cells))


def _list_views(page, rec) -> None:
    """Enumerate every view in the ATTTRACKER-B2B workbook, with its URL.

    Answers Carlos's "which of the two wireless churns is the accurate one" by
    first establishing that there ARE two and what they are actually called —
    the Loom only shows him scrolling past them. Names alone won't settle which
    is correct, but they give us the URLs to pull and diff.
    """
    rec("")
    rec("=== ATTTRACKER-B2B workbook views ===")
    page.goto(WORKBOOK_VIEWS_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(12_000)
    try:
        links = page.eval_on_selector_all(
            "a[href*='/views/ATTTRACKER-B2B/']",
            "els => els.map(e => [ (e.innerText||'').trim(), e.getAttribute('href') ])")
    except Exception as e:  # noqa: BLE001
        rec("  could not read the view list: {}".format(e))
        return
    seen = set()
    for name, href in links:
        if not href or href in seen:
            continue
        seen.add(href)
        rec("  {:<38} {}".format((name or "(unnamed)")[:38], href))
    if not seen:
        rec("  (no view links found — the workbook page may not have rendered)")
    churny = [(n, h) for n, h in links
              if "churn" in "{} {}".format(n or "", h or "").lower()]
    rec("")
    rec("  --- churn-looking views in ATTTRACKER-B2B ({}) ---".format(len(churny)))
    for name, href in churny:
        rec("    {:<36} {}".format((name or "(unnamed)")[:36], href))

    # Site-wide sweep — the B2B churn may not live in the B2B workbook at all.
    rec("")
    rec("=== SITE-WIDE churn search (all workbooks) ===")
    for term in SEARCH_TERMS:
        rec("")
        rec("  --- search: {!r} ---".format(term))
        try:
            page.goto(SITE_SEARCH_URL.format(term=term.replace(" ", "%20")),
                      wait_until="domcontentloaded")
            page.wait_for_timeout(10_000)
            hits = page.eval_on_selector_all(
                "a[href*='/views/']",
                "els => els.map(e => [ (e.innerText||'').trim(),"
                " e.getAttribute('href') ])")
        except Exception as e:  # noqa: BLE001 — one bad search must not kill the probe
            rec("    search failed: {}".format(e))
            continue
        shown = set()
        for name, href in hits:
            if not href or href in shown:
                continue
            shown.add(href)
            rec("    {:<36} {}".format((name or "(unnamed)")[:36], href))
        if not shown:
            rec("    (no view hits)")


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="att_order_log.probe")
    ap.add_argument("--from-file", default=None, metavar="XLSX",
                    help="skip the Tableau pull and describe an existing "
                         "export (for offline iteration on the parser)")
    ap.add_argument("--no-upload", action="store_true",
                    help="print only; don't write the diag tab")
    ap.add_argument("--list-views", action="store_true",
                    help="also enumerate every ATTTRACKER-B2B view + URL "
                         "(settles which wireless-churn views exist)")
    args = ap.parse_args(argv)

    buf = []

    def rec(msg=""):
        print(msg, flush=True)
        buf.append(str(msg))

    rec("ATT Order Log schema probe @ {}".format(
        dt.datetime.now().isoformat(timespec="seconds")))
    rec("view: {}".format(VIEW_URL))

    rc = 0
    try:
        from automations.vantura_churn import compute

        if args.from_file:
            path = Path(args.from_file)
            rec("reading local export: {}".format(path))
        else:
            from automations.vantura_churn import cdp_pull
            path = Path("/tmp/att_order_log_probe.xlsx")
            rec("pulling via real-Chrome CDP (Carlos's Tableau identity)")
            cdp_pull.probe(VIEW_URL, CROSSTAB_SHEET, path,
                           dt.date.today(), log=rec)

        # _load_grid does the merged-cell / blanked-continuation back-fill for
        # BOTH export formats. Describing the grid AFTER that fill would hide
        # the blanks we want to measure, so read the raw file for blank rates
        # and note that the fill is applied downstream.
        grid = compute._load_grid(path)
        _describe(grid, rec)

        if args.list_views:
            _run_list_views(rec)
    except Exception:  # noqa: BLE001 — a probe must report, not crash silently
        rec("")
        rec("TRACEBACK:")
        for ln in traceback.format_exc().splitlines()[-15:]:
            rec("  " + ln[:200])
        rc = 1

    if not args.no_upload:
        try:
            _upload(buf)
            rec("")
            rec("findings -> '{}' tab".format(DIAG_TAB))
        except Exception as e:  # noqa: BLE001 — never fail the probe on upload
            print("diag upload failed: {}".format(e), flush=True)
    return rc


def _run_list_views(rec) -> None:
    """Open a real-Chrome CDP session (Carlos's identity) just to enumerate the
    workbook's views. Separate session from the crosstab pull because
    cdp_pull.probe owns its own browser lifecycle end-to-end."""
    import time

    from patchright.sync_api import sync_playwright

    from automations.shared import tableau_patchright as tp
    from automations.vantura_churn import cdp_pull

    cdp_pull._kill_ours()
    proc = cdp_pull._launch()
    rec("[cdp] real Chrome pid={}; waiting 20s".format(proc.pid))
    time.sleep(20)
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(
                "http://127.0.0.1:{}".format(cdp_pull.CDP_PORT))
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            tp._ensure_tableau_authenticated(page, verbose=False,
                                             allow_form_login=True)
            _list_views(page, rec)
    finally:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        cdp_pull._kill_ours()


def _upload(lines) -> None:
    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(DIAG_SHEET_ID)
    try:
        ws = sh.worksheet(DIAG_TAB)
    except Exception:  # noqa: BLE001 — tab may not exist yet
        ws = sh.add_worksheet(title=DIAG_TAB, rows=600, cols=1)
    ws.clear()
    ws.update("A1", [[ln[:900]] for ln in lines[:600]])


if __name__ == "__main__":
    raise SystemExit(main())
