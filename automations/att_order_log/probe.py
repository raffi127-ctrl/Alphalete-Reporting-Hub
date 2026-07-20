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

# SETTLED (Megan 2026-07-19): "This is Carlos' wireless churn view." So the two
# candidates Carlos couldn't tell apart on the Loom are resolved by fiat — this
# is the one. It IS in ATTTRACKER-B2B after all, under the CHURNRATES workbook,
# as a custom view named CarloWireless. The site-wide sweep above stays anyway:
# it costs one page load and it's what tells us whether a SECOND, near-identical
# wireless-churn view exists that someone could later point a report at by
# mistake. Knowing both is how the ambiguity stops recurring.
#
# CUSTOM VIEW => LUCY 2 ONLY, same trap as b2b_quality: a custom view carries
# its owner's filters/sort for its owner. Under Raf's login this is a different
# slice, silently.
# Both of Carlos's churn views, Megan-supplied 2026-07-19. ONE table rather than
# two constants: these two are structurally identical (same CHURNRATES workbook,
# same custom-view mechanics, same destination shape) and differ only in which
# product they measure. The repo's own lesson — office_metrics/offices.py, and
# wireless_churn/fill.py being a 40-line re-point of new_internet_churn — is that
# near-identical feeds handled as separate copies drift. Each entry maps to the
# scaffold tab Carlos already built in the Vantura Master Sales Board.
CHURN_VIEWS = {
    "wireless": {
        "label": "Wireless Churn",
        "tab": "Lucy Wireless Churn",          # gid 2062141872
        "url": ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                "ATTTRACKER-B2B/CHURNRATES/"
                "1767636f-875a-40ac-ad39-a42cb894e428/CarloWireless?:iid=1"),
    },
    "new_int": {
        "label": "New Internet Churn",
        "tab": "Lucy New INT Churn",           # gid 916425770
        "url": ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                "ATTTRACKER-B2B/CHURNRATES/"
                "ae1e808c-0fa1-4385-8657-9d59c3c02813/CarlosNewINT?:iid=1"),
    },
}
# Note the view names are NOT spelled consistently upstream —  "CarloWireless"
# (no 's') vs "CarlosNewINT". Keep them verbatim; they are URL path segments,
# not labels, and "fixing" the typo would 404.
# The worksheet to pick in Download -> Crosstab. vantura_churn pulls this same
# CHURNRATES workbook with "ICD Churn", so that is the informed first guess; if
# the dialog rejects it, its error lists the real worksheet names.
CHURN_CROSSTAB_SHEET = "ICD Churn"

# For reference while reading the probe's output: vantura_churn already pulls
# this same CHURNRATES workbook, via its ALLTEAMCHURN view with crosstab sheet
# "ICD Churn", and gets per-ICD rows. Carlos's scaffold tabs need per-REP rows.
# _probe_churn's REP BREAKOUT line is what settles whether these custom views
# give us that.


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
    ap.add_argument("--churn-only", action="store_true",
                    help="skip the order log + direct-csv stages; pull just "
                         "the two churn crosstabs (fast: no 120MB export)")
    ap.add_argument("--cancel-only", action="store_true",
                    help="probe ONLY the B2B cancel-rates view (for the "
                         "Ongoing Cancel report Carlos asked for)")
    args = ap.parse_args(argv)

    buf = []

    def rec(msg=""):
        print(msg, flush=True)
        buf.append(str(msg))

    rec("ATT Order Log schema probe @ {}".format(
        dt.datetime.now().isoformat(timespec="seconds")))
    rec("view: {}".format(VIEW_URL))

    # STAGE ISOLATION. The 21:44 run proved why this matters: the order-log
    # load raised, and because every stage sat inside ONE try, the churn probes
    # and the view listing never ran at all — one avoidable failure cost us the
    # whole run's other answers. Each stage now reports its own traceback and
    # the rest continue.
    rc = 0

    def stage(name, fn, *a):
        nonlocal rc
        try:
            fn(*a)
        except Exception:  # noqa: BLE001 — a probe must report, not crash
            rec("")
            rec("!! STAGE FAILED: {}".format(name))
            for ln in traceback.format_exc().splitlines()[-12:]:
                rec("   " + ln[:200])
            rc = 1

    if args.from_file:
        stage("order log (local file)", _describe_file, Path(args.from_file), rec)
        return _finish(buf, rec, args, rc)

    # ONE CDP session for every stage. Chrome launch + Tableau auth costs ~40s,
    # so paying it once and reusing the page beats a session per probe.
    import time as _time

    from patchright.sync_api import sync_playwright

    from automations.shared import tableau_patchright as tp
    from automations.vantura_churn import cdp_pull

    cdp_pull._kill_ours()
    proc = cdp_pull._launch()
    rec("[cdp] real Chrome pid={}; waiting 20s".format(proc.pid))
    _time.sleep(20)
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(
                "http://127.0.0.1:{}".format(cdp_pull.CDP_PORT))
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            tp._ensure_tableau_authenticated(page, verbose=False,
                                             allow_form_login=True)
            rec("[cdp] auth OK")

            if args.cancel_only:
                stage("cancel rates", _probe_cancel, page, rec)
                return _finish(buf, rec, args, rc)
            if not args.churn_only:
                stage("order log", _probe_orderlog, page, rec)
                stage("cancel rates", _probe_cancel, page, rec)
            for key, spec in CHURN_VIEWS.items():
                # Crosstab FIRST — it is the one that decides whether the churn
                # fills are buildable at all. The direct-.csv probe stays as
                # the contrast case (it is what proved the custom view is
                # ignored there), but it must not gate the crosstab result.
                stage("crosstab:{}".format(key), _probe_churn_crosstab,
                      page, rec, key, spec)
                if not args.churn_only:
                    stage("csv:{}".format(key), _probe_churn,
                          page, rec, key, spec)
            if args.list_views:
                stage("view listing", _list_views, page, rec)
    except Exception:  # noqa: BLE001
        rec("")
        rec("SESSION FAILED:")
        for ln in traceback.format_exc().splitlines()[-12:]:
            rec("   " + ln[:200])
        rc = 1
    finally:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        cdp_pull._kill_ours()

    return _finish(buf, rec, args, rc)


def _finish(buf, rec, args, rc) -> int:
    if not args.no_upload:
        try:
            _upload(buf)
            rec("")
            rec("findings -> '{}' tab".format(DIAG_TAB))
        except Exception as e:  # noqa: BLE001 — never fail the probe on upload
            print("diag upload failed: {}".format(e), flush=True)
    return rc


def _describe_file(path, rec) -> None:
    """Offline path: describe an export already on disk."""
    from automations.vantura_churn import compute
    rec("reading local export: {}".format(path))
    _describe(compute._load_grid(path), rec)


def _probe_orderlog(page, rec) -> None:
    """Pull the order log via the DIRECT authenticated .csv export.

    Not cdp_pull.probe(): that helper ignores its url/out arguments entirely —
    it hardcodes the bare ORDERLOG view and writes /tmp/vantura_default.csv —
    so passing Carlos's custom-view URL to it silently probed the wrong thing
    and then failed on a file it never wrote (21:44 run). The direct .csv is
    also what actually succeeded there: status=200, 47 columns, every
    compute.COLS caption present.
    """
    import csv
    import io

    today = dt.date.today()
    start = today - dt.timedelta(days=60)      # match vantura_churn's window
    host = "https://us-east-1.online.tableau.com"
    url = ("{}/t/sci/views/ATTTRACKER-B2B/ORDERLOG.csv?:refresh=yes"
           "&Start%20Date={}&End%20Date={}").format(
               host, start.isoformat(), today.isoformat())
    rec("")
    rec("=== ORDER LOG (direct .csv, {} .. {}) ===".format(start, today))
    r = page.context.request.get(url, timeout=300_000)
    body = r.body() or b""
    rec("  status={} bytes={}".format(r.status, len(body)))
    if r.status != 200 or len(body) < 1000:
        rec("  head={!r}".format(body[:200].decode("utf-8", "replace")))
        return
    rows = list(csv.reader(io.StringIO(body.decode("utf-8-sig", "replace"))))
    _describe(rows, rec)
    _describe_measure_pivot(rows, rec)


def _describe_measure_pivot(rows, rec) -> None:
    """Quantify the measure pivot.

    The 21:44 run found group sizes of 4 and 8 with only 'Measure Names' /
    'Measure Values' varying — i.e. each real order line is emitted ONCE PER
    MEASURE (Unit Count / Total Volume / Total Activations / Sales (All)...).
    That is not the merged-cell problem Carlos described on the Loom and it is
    not what _GROUP_COLS forward-fill addresses; it needs an un-pivot, or the
    log renders every sale four times. This measures it so the renderer can be
    written against the real multiplicity rather than an assumed one.
    """
    if not rows:
        return
    hdr = [str(h or "").strip().lstrip("﻿") for h in rows[0]]
    rec("")
    rec("=== measure pivot ===")
    if "Measure Names" not in hdr:
        rec("  no 'Measure Names' column — export is NOT measure-pivoted")
        return
    mi = hdr.index("Measure Names")
    names = collections.Counter(
        str(r[mi]).strip() for r in rows[1:] if mi < len(r))
    rec("  rows per measure:")
    for n, c in names.most_common():
        rec("    {:>8}  {}".format(c, n or "(blank)"))
    rec("  => divide raw row count by {} for real order lines".format(
        len(names) or 1))


def _probe_churn(page, rec, key, spec) -> None:
    """Describe one of Carlos's churn views (Megan-supplied, authoritative).

    THE question this answers: does it carry a per-REP breakout? The scaffold
    tabs Carlos set up have a 'Rep' column and one row per rep, but
    vantura_churn learned the hard way that a CHURNRATES dashboard export can
    flatten to Owner & Office only. If it flattens, the churn fill needs a
    worksheet-level pull instead, and finding that out now is the difference
    between a re-point and a rewrite.
    """
    import csv
    import io

    rec("")
    rec("=== {} ({}) ===".format(spec["label"], key))
    rec("  view: {}".format(spec["url"]))
    rec("  dest: {!r}".format(spec["tab"]))
    # Load the custom view first so it is materialised before we ask for its
    # data (an export of a never-rendered custom view can come back as the
    # Original — the trap vantura_churn.cdp_pull documents for activations).
    try:
        page.goto(spec["url"], wait_until="domcontentloaded")
        page.wait_for_timeout(20_000)
        rec("  custom view rendered")
    except Exception as e:  # noqa: BLE001
        rec("  could not render the view: {}".format(e))
        return

    host = "https://us-east-1.online.tableau.com"
    url = "{}/t/sci/views/ATTTRACKER-B2B/CHURNRATES.csv?:refresh=yes".format(host)
    try:
        r = page.context.request.get(url, timeout=300_000)
        body = r.body() or b""
        rec("  [csv] status={} bytes={}".format(r.status, len(body)))
        if r.status != 200 or len(body) < 500:
            rec("  [csv] head={!r}".format(body[:180].decode("utf-8", "replace")))
            rec("  NOTE: direct .csv hits the DEFAULT view, not the custom one."
                " If this looks like all-teams rather than Carlos, the fill"
                " needs the crosstab-dialog path against CarloWireless.")
            return
        rows = list(csv.reader(io.StringIO(body.decode("utf-8-sig", "replace"))))
    except Exception as e:  # noqa: BLE001
        rec("  [csv] export failed: {}".format(e))
        return

    if not rows:
        rec("  [csv] empty")
        return
    hdr = [h.strip() for h in rows[0]]
    rec("  [csv] {} data rows, {} columns".format(len(rows) - 1, len(hdr)))
    rec("  columns:")
    for i, h in enumerate(hdr):
        rec("    [{:>2}] {}".format(i, h))

    # The decisive check.
    rep_cols = [h for h in hdr if "rep" in h.lower()]
    rec("")
    rec("  REP BREAKOUT: {}".format(
        "YES -> {}".format(rep_cols) if rep_cols else
        "NO — flattens to owner/ICD level; churn fill needs a worksheet pull"))
    bucket_cols = [h for h in hdr if "day" in h.lower() or "churn" in h.lower()]
    rec("  bucket-looking columns: {}".format(bucket_cols or "(none found)"))
    rec("")
    rec("  first 8 rows:")
    for r_ in rows[1:9]:
        rec("    " + " | ".join(str(c or "")[:20] for c in r_[:10]))


def _probe_churn_crosstab(page, rec, key, spec) -> None:
    """Pull a churn custom view through the CROSSTAB DIALOG and describe it.

    THE question: does the custom view's product filter survive the download?
    The direct .csv does NOT respect custom views — CarloWireless and
    CarlosNewINT both returned byte-identical all-teams data (2026-07-19), and
    the export carries no product column, so the wireless/new-internet split
    exists ONLY inside the view's filter. If the crosstab dialog preserves it,
    each view yields its own product and the churn fills are viable; if not,
    there is no way to tell the two products apart and the whole approach needs
    rethinking.

    ALSO records the SHAPE. The D2D crosstab is WIDE (one column per period:
    "0-30 Day Churn", "30 Day Churn", ...) and new_internet_churn.pull looks
    those up by name. The B2B dashboard export was LONG (a "Churn Buckets"
    column holding those values). Against a long export the D2D parser finds no
    period columns and returns EMPTY rather than raising — a silent wrong
    answer. This prints the header so we know which transform to write.
    """
    from pathlib import Path as _P

    from automations.recruiting_report.opt_phase import drive_crosstab_dialog

    rec("")
    rec("=== CROSSTAB {} ({}) ===".format(spec["label"], key))
    out = _P("/tmp/att_churn_{}.csv".format(key))
    try:
        drive_crosstab_dialog(page, spec["url"], CHURN_CROSSTAB_SHEET, out,
                              verbose=False)
    except Exception as e:  # noqa: BLE001
        rec("  crosstab download FAILED: {}".format(str(e)[:200]))
        rec("  (worksheet name may be wrong — the dialog lists the real ones)")
        return

    from automations.att_order_log import clean
    grid = clean.load_grid(out)
    if not grid:
        rec("  empty export")
        return
    hdr = [str(h or "").strip().lstrip("﻿") for h in grid[0]]
    rows = grid[1:]
    rec("  {} rows, {} columns".format(len(rows), len(hdr)))
    for i, h in enumerate(hdr):
        rec("    [{:>2}] {}".format(i, h))

    # WIDE or LONG?
    wide = [h for h in hdr if h.lower().endswith("day churn")]
    rec("")
    rec("  SHAPE: {}".format(
        "WIDE — period columns {} (D2D parser works as-is)".format(wide)
        if wide else
        "LONG — periods are row values; needs a long->wide transform"))
    for label in ("Churn Buckets", "OWNER & OFFICE", "ICD Owner Name (rep)",
                  "Rep", "rep.Full Name"):
        if label in hdr:
            vals = {str(r[hdr.index(label)]).strip() for r in rows[:400]
                    if hdr.index(label) < len(r)}
            rec("  {:<22} {} distinct, e.g. {}".format(
                label, len(vals), sorted(v for v in vals if v)[:4]))

    # Did the OWNER filter survive? If this is Carlos-only the custom view's
    # filters came through; if it spans many owners they did not.
    for ocol in ("OWNER & OFFICE", "ICD Owner Name (rep)"):
        if ocol in hdr:
            oi = hdr.index(ocol)
            owners = {str(r[oi]).split("\n")[0].strip() for r in rows
                      if oi < len(r) and str(r[oi]).strip()}
            rec("")
            rec("  OWNER FILTER: {} distinct owner(s)".format(len(owners)))
            rec("    -> {}".format(
                "SURVIVED (Carlos only)" if len(owners) <= 1
                else "NOT applied — all-teams export, product split lost"))
            rec("    {}".format(sorted(owners)[:5]))
            break
    rec("")
    rec("  first 6 rows:")
    for r in rows[:6]:
        rec("    " + " | ".join(str(c or "")[:18] for c in r[:9]))


CANCEL_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER-B2B/B2BCancelRates?:iid=1"
)
# The D2D module's worksheet name, tried first. If B2B names it differently the
# dialog's error lists the real options.
CANCEL_WORKSHEETS = ("Internet Cancel Rates (Daily)", "B2B Cancel Rates",
                     "Cancel Rates")


def _probe_cancel(page, rec) -> None:
    """Schema-probe the B2B cancel-rates view for the Ongoing Cancel report.

    Carlos asked for this on the Loom (2:21-2:45): "the ongoing cancel
    report... if they could live on my spreadsheet, that'd be great."

    automations/ongoing_cancel is env-driven (ONGOING_CANCEL_VIEW_URL +
    _SLICE_OWNER) but its parser is tied to Raf's D2D workbook — worksheet
    "Internet Cancel Rates (Daily)", metrics "Running Sum of Canceled Internet
    Orders along sp.Order Date" / "... Internet Sales ...". Whether the B2B
    workbook carries the same worksheet and the same measure captions decides
    whether this is another header-adapter job (like the churn) or a real
    parser. Guessing either way wastes a Lucy 2 round-trip, so: look.

    NOTE none of Carlos's four ATTTRACKER-B2B custom views is a cancel view
    (they are Carlo Wireless, CARLOS LOCAL EXPANDED, Carlos metrics, Carlos New
    INT), so unlike the churn there is no per-owner view to ride — this will
    need slicing to him in Python, the way office_metrics slices AllExpanded.
    """
    from pathlib import Path as _P

    from automations.recruiting_report.opt_phase import drive_crosstab_dialog

    from . import clean

    rec("")
    rec("=== B2B CANCEL RATES ===")
    rec("  view: {}".format(CANCEL_VIEW_URL))
    out = _P("/tmp/att_cancel_probe.csv")
    got = None
    for ws_name in CANCEL_WORKSHEETS:
        try:
            drive_crosstab_dialog(page, CANCEL_VIEW_URL, ws_name, out,
                                  verbose=False)
            got = ws_name
            break
        except Exception as e:  # noqa: BLE001
            rec("  worksheet {!r}: {}".format(ws_name, str(e)[:140]))
    if not got:
        rec("  NO worksheet matched — see the errors above for the real names")
        return
    rec("  worksheet: {!r}".format(got))

    grid = clean.load_grid(out)
    if not grid:
        rec("  empty export")
        return
    hdr = [str(h or "").strip().lstrip("﻿") for h in grid[0]]
    rows = grid[1:]
    rec("  {} rows, {} columns".format(len(rows), len(hdr)))
    for i, h in enumerate(hdr):
        rec("    [{:>2}] {}".format(i, h))

    # Does the D2D parser's contract hold?
    from automations.ongoing_cancel import pull as oc_pull
    rec("")
    rec("  D2D metric captions present?")
    joined = " | ".join(hdr) + " | " + " | ".join(
        str(c) for r in rows[:200] for c in r)
    for cap in (oc_pull.RATE_METRIC, oc_pull.CANCELS_METRIC,
                oc_pull.SALES_METRIC):
        rec("    {:<62} {}".format(cap[:62], "YES" if cap in joined else "no"))

    for label in ("Owner & Office", "ICD Owner Name (rep)", "Rep", "Rep Name"):
        if label in hdr:
            i = hdr.index(label)
            vals = {str(r[i]).split("\n")[0].strip() for r in rows
                    if i < len(r) and str(r[i]).strip()}
            rec("")
            rec("  {}: {} distinct".format(label, len(vals)))
            rec("    carlos present: {}".format(
                any(v.upper().startswith("CARLOS HIDALGO") for v in vals)))
            rec("    e.g. {}".format(sorted(vals)[:5]))
    rec("")
    rec("  first 6 rows:")
    for r in rows[:6]:
        rec("    " + " | ".join(str(c or "")[:20] for c in r[:8]))


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
            for key, spec in CHURN_VIEWS.items():
                _probe_churn(page, rec, key, spec)
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
