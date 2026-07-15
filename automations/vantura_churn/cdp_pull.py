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

import subprocess
import time
from pathlib import Path

CDP_PROFILE = "/tmp/vantura_cdp_profile"
CDP_PORT = "9246"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _kill_ours() -> None:
    subprocess.run(["pkill", "-f", "vantura_cdp_profile"], capture_output=True)
    time.sleep(2)


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


def probe(url, sheet, out, today, log=print) -> dict:
    """Diagnostic: load the view in real Chrome, screenshot it (→ 'Vantura
    Shot' tab), try to select the worksheet, and report crosstab thumbs."""
    from patchright.sync_api import sync_playwright
    from automations.shared import tableau_patchright as tp
    _kill_ours()
    proc = _launch()
    log(f"[cdp] real Chrome pid={proc.pid}; waiting 20s")
    time.sleep(20)
    info = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            tp._ensure_tableau_authenticated(page, verbose=False,
                                             allow_form_login=True)
            log("[cdp] auth OK; loading view")
            page.goto(url, wait_until="domcontentloaded")
            viz = page.frame_locator('iframe[title="Data Visualization"]')
            try:
                viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-'
                            'download"]').wait_for(state="visible",
                                                   timeout=180_000)
                log("[cdp] toolbar visible")
            except Exception as e:
                log(f"[cdp] toolbar NOT visible: {str(e)[:80]}")
            page.wait_for_timeout(30_000)
            try:
                _upload_png(page.screenshot(full_page=False))
                log("[cdp] screenshot → 'Vantura Shot' tab")
            except Exception as e:
                log(f"[cdp] screenshot err: {str(e)[:80]}")
            focused = _select_worksheet(page, log)
            info["focused"] = focused
            # open crosstab, count thumbs
            try:
                page.keyboard.press("Escape"); page.wait_for_timeout(500)
                viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-'
                            'download"]').click(); page.wait_for_timeout(1500)
                viz.locator('[data-tb-test-id="download-flyout-download-'
                            'crosstab-MenuItem"]').click()
                page.wait_for_timeout(5000)
                thumbs = viz.locator('[data-tb-test-id^="sheet-thumbnail-"]')
                n = thumbs.count()
                names = [thumbs.nth(i).inner_text().strip() for i in range(n)]
                info["thumbs"] = n
                info["names"] = names
                log(f"[cdp] crosstab thumbs={n} names={names}")
            except Exception as e:
                log(f"[cdp] crosstab err: {str(e)[:100]}")
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        _kill_ours()
    return info


def download_views(specs, verbose=True, log=print):
    """Download each (view_url, crosstab_sheet, out_path) via one real-Chrome
    CDP session. Auth is seeded once (ownerville storage_state → Tableau SSO,
    form-login self-heal). Returns {out_path: Path} for successes.

    Raises if the CDP session or auth fails; per-view failures propagate from
    download_crosstab_patchright (which already retries 3x)."""
    from patchright.sync_api import sync_playwright
    from automations.shared import tableau_patchright as tp
    from automations.shared.tableau_patchright import download_crosstab_patchright

    _kill_ours()
    proc = _launch()
    log(f"[cdp] launched real Chrome pid={proc.pid}; waiting 20s")
    time.sleep(20)
    results = {}
    dl_dir = Path("/tmp/vantura_dl")
    dl_dir.mkdir(exist_ok=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            # Make Chrome save downloads to a known dir (Playwright's
            # expect_download still intercepts, but this is the belt-and-braces
            # for CDP-attached contexts).
            try:
                client = ctx.new_cdp_session(page)
                client.send("Browser.setDownloadBehavior",
                            {"behavior": "allow", "downloadPath": str(dl_dir)})
            except Exception as e:
                log(f"[cdp] setDownloadBehavior warn: {str(e)[:80]}")

            log("[cdp] authenticating (ownerville storage_state → Tableau SSO)…")
            tp._ensure_tableau_authenticated(page, verbose=verbose,
                                             allow_form_login=True)
            log("[cdp] auth OK; starting downloads")

            for url, sheet, out in specs:
                out = Path(out)
                download_crosstab_patchright(url, sheet, out, page=page,
                                             verbose=verbose)
                results[str(out)] = out
                log(f"[cdp] saved {sheet} → {out} "
                    f"({out.stat().st_size:,} bytes)")
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        _kill_ours()
    return results
