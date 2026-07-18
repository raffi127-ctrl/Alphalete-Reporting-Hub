"""Real-Chrome-over-CDP Tableau downloader for vantura_churn.

WHY: the B2B ORDERLOG view is a dashboard whose Download→Crosstab dialog
returns "No sheets to select" under patchright's stealth Chromium (proven
~11 ways). A REAL Google Chrome renders Tableau normally, so the crosstab
dialog enumerates the worksheet and the existing downloader works. This
mirrors the technique the resume-pushing module uses, but is COMPLETELY
SEPARATE from it: its own module, its own profile dir, its own debug port,
its own process. It never imports, runs, or affects resume_pushing.

Isolation invariants (do not change to collide with resume_pushing):
  * profile dir  /tmp/vantura_cdp_profile   (resume uses /tmp/rp_cdp_profile)
  * debug port   9246                        (resume uses 9245)
  * pkill filter matches ONLY 'vantura_cdp_profile'
  * FRESH profile — we do NOT copy Carlos's everyday Chrome profile; auth is
    seeded via the shared ownerville storage_state + SSO (works in real
    Chrome), so nothing of Carlos's own Chrome is touched.
"""
from __future__ import annotations

import datetime as dt
import subprocess
import time
from pathlib import Path

CDP_PROFILE = "/tmp/vantura_cdp_profile"
CDP_PORT = "9246"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _kill_ours() -> None:
    subprocess.run(["pkill", "-f", "vantura_cdp_profile"], capture_output=True)
    time.sleep(2)


def _copy_default_profile() -> str:
    """Copy Carlos's REAL everyday Chrome Default profile — which is logged
    into Tableau AS HIM (the identity that actually sees the Order Log rows,
    unlike the ownerville-SSO service identity) — to our own NON-default dir
    so Chrome honours the debug port (Chrome 136+ blocks it on the true
    default dir). READ-ONLY on the source: nothing of Carlos's own Chrome is
    modified. Separate dest dir from resume_pushing's, so the two never
    collide. Skips cache dirs for speed."""
    import os
    home = os.path.expanduser("~")
    src = f"{home}/Library/Application Support/Google/Chrome"
    dst = CDP_PROFILE
    _kill_ours()
    subprocess.run(["rm", "-rf", dst], capture_output=True)
    os.makedirs(f"{dst}/Default", exist_ok=True)
    subprocess.run(["rsync", "-a", f"{src}/Local State",
                    f"{dst}/Local State"], capture_output=True)
    subprocess.run(
        ["rsync", "-a",
         "--exclude", "Cache", "--exclude", "Code Cache", "--exclude", "GPUCache",
         "--exclude", "DawnCache", "--exclude", "GraphiteDawnCache",
         "--exclude", "Application Cache",
         "--exclude", "Service Worker/CacheStorage",
         f"{src}/Default/", f"{dst}/Default/"],
        capture_output=True)
    return dst


def _launch(url: str = "about:blank"):
    """Launch the REAL Google Chrome on a fresh dedicated profile with the
    debug port. Returns the Popen."""
    launch = [
        CHROME, f"--user-data-dir={CDP_PROFILE}",
        f"--remote-debugging-port={CDP_PORT}",
        "--no-first-run", "--no-default-browser-check",
        "--restore-last-session=false", "--disable-session-crashed-bubble",
        "--disable-infobars", "--window-size=1600,1000", url,
    ]
    return subprocess.Popen(launch, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def _upload_png(png_bytes: bytes, tab="Vantura Shot") -> None:
    """base64-chunk a PNG into a sheet tab for remote viewing (decode locally
    with the mini's creds)."""
    import base64
    from automations.recruiting_report import fill as _fill
    b64 = base64.b64encode(png_bytes).decode()
    chunks = [b64[i:i + 45000] for i in range(0, len(b64), 45000)]
    sh = _fill._client().open_by_key(
        "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw")
    try:
        t = sh.worksheet(tab)
    except Exception:
        t = sh.add_worksheet(title=tab, rows=100, cols=1)
    t.clear()
    t.update([[c] for c in chunks], "A1")


def _select_worksheet(page, log) -> bool:
    """Give a dashboard worksheet focus so Download→Crosstab can enumerate it.
    CDP mouse clicks are TRUSTED events (unlike patchright's synthetic ones
    Tableau ignored), so clicking a data mark actually selects the sheet.
    Returns True once the Download→Data item enables (the focus signal)."""
    viz = page.frame_locator('iframe[title="Data Visualization"]')
    ifr = page.locator('iframe[title="Data Visualization"]').bounding_box()
    if not ifr:
        log("[select] no viz iframe"); return False

    def _data_enabled():
        try:
            page.keyboard.press("Escape"); page.wait_for_timeout(500)
            viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-'
                        'download"]').click(); page.wait_for_timeout(1000)
            di = viz.locator('[data-tb-test-id="download-flyout-'
                             'download-data-MenuItem"]')
            en = di.count() and di.get_attribute("aria-disabled") == "false"
            page.keyboard.press("Escape"); page.wait_for_timeout(300)
            return en
        except Exception:
            return False

    # Walk a grid of points across the viz body; trusted-click each until a
    # worksheet takes focus (Data enables).
    zone = viz.locator('.tabZone-viz').first
    zb = None
    try:
        zb = zone.bounding_box()
    except Exception:
        pass
    box = zb or {"x": 8, "y": 250, "width": ifr["width"] - 16,
                 "height": ifr["height"] - 260}
    for fy in (0.15, 0.35, 0.55, 0.75):
        for fx in (0.15, 0.45, 0.75):
            x = ifr["x"] + box["x"] + box["width"] * fx
            y = ifr["y"] + box["y"] + box["height"] * fy
            page.mouse.click(x, y)
            page.wait_for_timeout(500)
        if _data_enabled():
            log(f"[select] worksheet focused (row fy={fy})")
            return True
    log("[select] no worksheet took focus")
    return False


def _probe_exports(page, today, log) -> None:
    """Direct URL exports with the page's authenticated cookies — if any of
    these return data, the whole render-then-crosstab-dialog dance is
    unnecessary. The CHURNRATES custom view is included as a KNOWN-GOOD
    control (that URL pattern already downloads fine via the dialog), so a
    failure there means the technique is wrong, not the view."""
    from urllib.parse import quote
    host = "https://us-east-1.online.tableau.com"
    start = today - dt.timedelta(days=60)
    dates = (f"Start%20Date={start.isoformat()}"
             f"&End%20Date={today.isoformat()}")
    tests = [
        ("dash",       f"{host}/t/sci/views/ATTTRACKER-B2B/ORDERLOG.csv"
                       "?:refresh=yes"),
        ("dash+dates", f"{host}/t/sci/views/ATTTRACKER-B2B/ORDERLOG.csv"
                       f"?:refresh=yes&{dates}"),
        ("sheet",      f"{host}/t/sci/views/ATTTRACKER-B2B/"
                       f"{quote('Order Log')}.csv?:refresh=yes"),
        ("cv-control", f"{host}/t/sci/views/ATTTRACKER-B2B/CHURNRATES/"
                       "429cb06d-a32e-4d0e-bf06-9acb77587afd/ALLTEAMCHURN.csv"
                       "?:refresh=yes"),
    ]
    for label, u in tests:
        try:
            r = page.context.request.get(u, timeout=90_000)
            body = r.body() or b""
            head = body[:180].decode("utf-8", "replace").replace("\n", " ⏎ ")
            log(f"[export {label}] status={r.status} bytes={len(body)}"
                f" head={head!r}")
        except Exception as ex:  # noqa: BLE001 — each test independent
            log(f"[export {label}] ERR {str(ex)[:120]}")


def _probe_custom_views(page, viz, log) -> None:
    """Open the toolbar's 'View: …' flyout and record the saved custom views.
    CHURNRATES already downloads via a custom-view URL, and the bare ORDERLOG
    Original view renders empty (several quick filters sit at '(None)'), so
    the daily manual flow very likely lives in a custom view whose URL slug
    this reveals. Text via the flyout DOM; screenshot as backup."""
    try:
        btn = viz.locator('[data-tb-test-id*="custom-view"], '
                          'button:has-text("View:")').first
        btn.click()
        page.wait_for_timeout(2500)
        texts = []
        for sel in ('[data-tb-test-id*="custom-view"]', '[role="dialog"]',
                    '[class*="flyout"]', '[class*="CustomView"]'):
            try:
                for el in viz.locator(sel).all()[:6]:
                    t = (el.inner_text(timeout=3000) or "").strip()
                    if t and t not in texts:
                        texts.append(t)
            except Exception:
                continue
        if texts:
            for t in texts:
                for ln in t.splitlines()[:25]:
                    if ln.strip():
                        log(f"[views] {ln.strip()[:120]}")
        else:
            log("[views] flyout text not found via DOM (see screenshot)")
        try:
            _upload_png(page.screenshot(full_page=False), tab="Vantura Shot")
            log("[views] flyout screenshot -> 'Vantura Shot'")
        except Exception:
            pass
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception as ex:  # noqa: BLE001
        log(f"[views] ERR {str(ex)[:120]}")


def probe(url, sheet, out, today, log=print) -> dict:
    """Diagnostics: load the BARE ORDER LOG, then (1) list its saved custom
    views, (2) try direct authenticated .csv exports (dashboard / sheet /
    known-good custom-view control), (3) attempt the default crosstab
    download. Findings → 'Vantura Diag' + 'Vantura Shot'."""
    from patchright.sync_api import sync_playwright
    from automations.shared import tableau_patchright as tp
    from automations.recruiting_report.opt_phase import drive_crosstab_dialog
    from automations.vantura_churn import compute
    _kill_ours()
    proc = _launch()
    log(f"[cdp] real Chrome pid={proc.pid}; waiting 20s")
    time.sleep(20)
    info = {}
    bare = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
            "ATTTRACKER-B2B/ORDERLOG?:iid=1")
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            tp._ensure_tableau_authenticated(page, verbose=False,
                                             allow_form_login=True)
            page.goto(bare, wait_until="domcontentloaded")
            viz = page.frame_locator('iframe[title="Data Visualization"]')
            try:
                viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-'
                            'download"]').wait_for(state="visible", timeout=150_000)
            except Exception:
                pass
            page.wait_for_timeout(15_000)
            _probe_exports(page, today, log)
            _probe_custom_views(page, viz, log)
            dst = Path("/tmp/vantura_default.csv")
            try:
                drive_crosstab_dialog(page, bare, sheet, dst, verbose=False,
                                      skip_nav=True)
                log(f"downloaded default {dst.stat().st_size} bytes")
                grid = compute._load_grid(dst)
                hdr = [str(h or "").strip() for h in grid[0]]
                oi = hdr.index(compute.COLS["owner"]) if compute.COLS["owner"] in hdr else 0
                odi = hdr.index(compute.COLS["order_date"]) if compute.COLS["order_date"] in hdr else -1
                carlos = 0; odates = []
                for r in grid[1:]:
                    if len(r) <= oi: continue
                    if str(r[oi] or "").split(chr(10))[0].strip().upper().startswith("CARLOS HIDALGO"):
                        carlos += 1
                    if odi >= 0 and odi < len(r):
                        d = compute._parse_date(r[odi])
                        if d: odates.append(d)
                log(f"[default] total rows {len(grid)-1}  CARLOS {carlos}")
                if odates:
                    log(f"[default] order-date range {min(odates)} .. {max(odates)}")
            except Exception as ex:
                log(f"[default] download err {str(ex)[:100]}")
    except Exception as ex:
        import traceback
        log("ERR " + str(ex)[:120])
        for x in traceback.format_exc().splitlines()[-6:]:
            log(x[:150])
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        _kill_ours()
    return info


def _select_owner(page, owner_name, log):
    """Filter the Order Log to ONE owner via the Owner & Office quick-filter,
    then Apply — the field can DISPLAY an owner while no checkbox is actually
    ticked (so the filter is empty and the grid stays blank). Open the panel,
    tick the owner, click Apply. Keeping it to one owner also keeps the result
    small enough for the worksheet to render."""
    viz = page.frame_locator('iframe[title="Data Visualization"]')
    vp = page.evaluate("() => ({w:window.innerWidth,h:window.innerHeight})")
    W, H = vp["w"], vp["h"]
    # open the Owner & Office dropdown (caret in the 2nd filter row)
    page.mouse.click(W * 0.155, H * 0.327)
    page.wait_for_timeout(2500)
    # the rows are canvas — can't click by text. Use the panel's SEARCH box to
    # filter to just this owner, then click "(All)" (selects the filtered set =
    # the one owner), which is position-stable regardless of list order.
    page.mouse.click(W * 0.225, H * 0.356)          # search box
    page.wait_for_timeout(700)
    page.keyboard.type(owner_name, delay=40)
    page.wait_for_timeout(2500)
    page.mouse.click(W * 0.0987, H * 0.386)         # "(All)" checkbox (filtered)
    page.wait_for_timeout(1500)
    log(f"[owner] searched+selected {owner_name}")
    # click Apply (right button at the panel bottom)
    page.mouse.click(W * 0.29, H * 0.975)
    log("[owner] apply clicked; waiting for query")
    # If auto-updates got paused (observed 'Resume' in the toolbar), the
    # filter changes are queued but never rendered — resume + refresh so the
    # query actually runs.
    try:
        pb = viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-'
                         'pause-updates"]')
        lbl = pb.get_attribute("aria-label") or ""
        log(f"[owner] pause-btn label={lbl!r}")
        if "Resume" in lbl:
            pb.click()
            log("[owner] clicked Resume (auto-updates were paused)")
            page.wait_for_timeout(6000)
    except Exception as ex:
        log(f"[owner] resume err {str(ex)[:50]}")
    try:
        viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-'
                    'refresh"]').first.click()
    except Exception:
        pass
    _wait_query(page, viz, log)


def _wait_query(page, viz, log):
    """Wait for the 'Working on it / Computing models' overlay to APPEAR and
    then CLEAR — polling for absence alone races the query start (the loop can
    exit before the overlay even shows)."""
    msgs = ("Working on it", "Computing models", "Processing request",
            "Preparing result")
    appeared = False
    for _ in range(70):
        page.wait_for_timeout(3000)
        try:
            body = viz.locator("body").inner_text(timeout=8000)
        except Exception:
            continue
        busy = any(m in body for m in msgs)
        if busy:
            appeared = True
        elif appeared:
            log("[query] overlay cleared")
            break
    page.wait_for_timeout(8_000)


def _prime_orderlog(page, url, today, log):
    """The B2B ORDER LOG dashboard loads with an EMPTY worksheet until its date
    parameters actually CHANGE and re-query — so the crosstab dialog has no
    sheet to export. The URL pre-fills the date fields with the target values,
    so re-typing the SAME value is a no-op that never fires the query. Force a
    real change: type a throwaway date, Enter, then the correct date, Enter —
    for BOTH fields. That runs the 60-day query and populates the worksheet."""
    import datetime as _dt
    page.goto(url, wait_until="domcontentloaded")
    viz = page.frame_locator('iframe[title="Data Visualization"]')
    try:
        viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-'
                    'download"]').wait_for(state="visible", timeout=150_000)
    except Exception:
        pass
    page.wait_for_timeout(18_000)
    start = today - _dt.timedelta(days=60)
    start_s = f"{start.month}/{start.day}/{start.year}"
    end_s = f"{today.month}/{today.day}/{today.year}"
    vp = page.evaluate("() => ({w:window.innerWidth,h:window.innerHeight})")
    W, H = vp["w"], vp["h"]

    def _set_date(fx, val):
        # Escape first to kill any open calendar popup that would swallow the
        # click; then select-all + retype + Enter; Escape again to close the
        # calendar the edit re-opens.
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        page.mouse.click(W * fx, H * 0.255, click_count=3)
        page.wait_for_timeout(500)
        page.keyboard.press("Backspace")
        page.keyboard.type(val, delay=45)
        page.keyboard.press("Enter")
        page.wait_for_timeout(2000)
        page.keyboard.press("Escape")
        page.wait_for_timeout(600)

    # Two rules make the edits stick: (1) ALTERNATE fields — two consecutive
    # writes to the SAME field leave the 2nd rejected, so never edit the same
    # field twice in a row; (2) keep start <= end at EVERY step — an inverted
    # range is rejected. Each field is bumped to a throwaway (real change) then
    # to its target, ending at exactly the 60-day window (small → renders).
    later = today + _dt.timedelta(days=31)
    earlier = start - _dt.timedelta(days=31)
    later_s = f"{later.month}/{later.day}/{later.year}"
    earlier_s = f"{earlier.month}/{earlier.day}/{earlier.year}"
    for fx, val in [(0.213, later_s),    # End → later  (start < later)
                    (0.13, earlier_s),   # Start → earlier (earlier < later)
                    (0.213, end_s),      # End → target (earlier < end)
                    (0.13, start_s)]:    # Start → target (start < end)
        try:
            _set_date(fx, val)
        except Exception as ex:
            log(f"[prime] date err {str(ex)[:50]}")
    # The date edits fire the query — WAIT for the "Working on it / Computing
    # models" overlay to clear before the worksheet is exportable. Poll up to
    # ~150s.
    for _ in range(50):
        page.wait_for_timeout(3000)
        try:
            body = viz.locator("body").inner_text(timeout=8000)
        except Exception:
            continue
        if not any(m in body for m in ("Working on it", "Computing models",
                                       "Processing request", "Preparing result")):
            break
    page.wait_for_timeout(4_000)


def download_views(specs, today=None, verbose=True, log=print):
    """Download each (view_url, crosstab_sheet, out_path) via one real-Chrome
    CDP session. Auth seeded once (ownerville storage_state → Tableau SSO).
    ORDER LOG views are primed first (see _prime_orderlog) so their worksheet
    has data before the crosstab export. Returns {out_path: Path}."""
    import datetime as _dt
    from patchright.sync_api import sync_playwright
    from automations.shared import tableau_patchright as tp
    from automations.shared.tableau_patchright import download_crosstab_patchright
    from automations.recruiting_report.opt_phase import drive_crosstab_dialog

    if today is None:
        today = _dt.date.today()
    # Mirror every log line to the 'Vantura Diag' tab so failures are visible
    # remotely (the mini-control Result cell truncates hard).
    _buf = []
    _orig_log = log

    def dlog(msg):
        _orig_log(msg)
        _buf.append(str(msg))
    log = dlog

    _kill_ours()
    proc = _launch()
    log(f"[cdp] launched real Chrome pid={proc.pid}; waiting 20s")
    time.sleep(20)
    results = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            # NB: do NOT set Browser.setDownloadBehavior — it makes Chrome save
            # the file directly and bypasses Playwright's expect_download, which
            # drive_crosstab_dialog uses to capture + save_as (→ 0-byte files).

            log("[cdp] authenticating (ownerville storage_state → Tableau SSO)…")
            tp._ensure_tableau_authenticated(page, verbose=verbose,
                                             allow_form_login=True)
            log("[cdp] auth OK; starting downloads")

            for url, sheet, out in specs:
                out = Path(out)
                if "ATTTRACKER-B2B/ORDERLOG" in url:
                    # Prime the empty worksheet, then export from the CURRENT
                    # primed state — skip_nav=True so we DON'T re-navigate
                    # (which would reset the query back to empty). Re-prime
                    # once on failure since the trigger is timing-sensitive.
                    last = None
                    for attempt in (1, 2):
                        log(f"[cdp] priming ORDER LOG {out.name} (try {attempt})…")
                        _prime_orderlog(page, url, today, log)
                        try:
                            drive_crosstab_dialog(page, url, sheet, out,
                                                  verbose=verbose, skip_nav=True)
                            last = None
                            break
                        except Exception as ex:
                            last = ex
                            log(f"[cdp] export retry: {str(ex)[:90]}")
                    if last is not None:
                        raise last
                else:
                    download_crosstab_patchright(url, sheet, out, page=page,
                                                 verbose=verbose)
                results[str(out)] = out
                log(f"[cdp] saved {sheet} → {out} "
                    f"({out.stat().st_size:,} bytes)")
    except Exception:
        import traceback
        _buf.append("TRACEBACK:")
        _buf.extend(traceback.format_exc().splitlines()[-14:])
        raise
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        _kill_ours()
        try:
            _upload_lines(_buf, tab="Vantura Diag")
        except Exception:
            pass
    return results


def _upload_lines(lines, tab="Vantura Diag"):
    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(
        "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw")
    try:
        t = sh.worksheet(tab)
    except Exception:
        t = sh.add_worksheet(title=tab, rows=400, cols=1)
    t.clear()
    t.update([[x[:900]] for x in (lines[-380:] or ["(empty)"])], "A1")
