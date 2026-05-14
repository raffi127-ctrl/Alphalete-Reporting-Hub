"""Passive watcher: attach to debug-port Chrome, snapshot every change.

You run the Tableau report flow in your browser like you normally would —
applying filters, clicking Download, saving the file. This script polls
the Tableau tab every ~1.5s, captures a screenshot + URL + HTML whenever
something meaningfully changes (URL, page title, or top-level DOM hash),
and logs any download events.

Output: output/_phase3_watch/<timestamp>/ with frames named NN_<event>.png
+ NN_<event>.html. Plus a watch_log.txt with the chronological event log.

Run:
    .venv/bin/python -m automations.focus_office_att._watch
    Ctrl+C when done.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import signal
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

POLL_INTERVAL_S = 1.2  # how often we sample state
OUT_ROOT = Path(__file__).resolve().parents[2] / "output" / "_phase3_watch"


def dom_fingerprint(page) -> str:
    """Cheap hash of the visible DOM so we can detect 'page changed' even
    when URL stays put. Hashes BOTH the main page body AND any Tableau viz
    iframe body — Tableau renders menus/dialogs inside the iframe, so missing
    that means missing every meaningful interaction.
    """
    parts: list[str] = []
    try:
        main = page.evaluate("() => document.body ? document.body.outerHTML.slice(0, 5000) : ''")
        parts.append(main)
    except Exception:
        pass
    for fr in page.frames:
        if fr == page.main_frame:
            continue
        # Only fingerprint Tableau viz frames; ignore about:blank etc.
        if "tableau" not in fr.url and "embed=y" not in fr.url:
            continue
        try:
            body = fr.evaluate("() => document.body ? document.body.outerHTML.slice(0, 5000) : ''")
            parts.append(body)
        except Exception:
            pass
    blob = "||".join(parts).encode("utf-8", errors="ignore")
    return hashlib.md5(blob).hexdigest()[:10]


def main() -> int:
    session = OUT_ROOT / dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    session.mkdir(parents=True, exist_ok=True)
    log_path = session / "watch_log.txt"
    log = log_path.open("w")

    def emit(msg: str) -> None:
        line = f"[{dt.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}"
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()

    def shutdown(*_):
        emit("Stopping watcher (Ctrl+C received).")
        log.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
        except Exception as e:
            emit(f"FAIL: could not connect to Chrome on :9222 — {e}")
            return 1

        pages = [pg for ctx in browser.contexts for pg in ctx.pages]
        tableau_pages = [pg for pg in pages if "tableau.com" in pg.url]
        if not tableau_pages:
            emit("FAIL: no tableau.com tab open. Open the report tab and rerun.")
            return 2

        page = tableau_pages[0]
        emit(f"Watching: {page.url}")
        emit(f"Output dir: {session}")

        # Wire download listener — every browser context can fire downloads
        def on_download(dl):
            saved = session / f"download_{dl.suggested_filename}"
            try:
                dl.save_as(str(saved))
                emit(f"DOWNLOAD captured: {dl.suggested_filename} -> {saved}")
            except Exception as e:
                emit(f"DOWNLOAD ({dl.suggested_filename}) failed to save: {e}")

        for ctx in browser.contexts:
            ctx.on("page", lambda new_pg: emit(f"NEW PAGE: {new_pg.url}"))
            # Downloads fire on page, not context
        for pg in pages:
            pg.on("download", on_download)

        last_url = None
        last_title = None
        last_dom = None
        step = 0

        emit("Ready. Run your Tableau report flow in the browser now.")
        emit("Press Ctrl+C in this terminal when you're done.")

        while True:
            try:
                cur_url = page.url
                cur_title = page.title()
                cur_dom = dom_fingerprint(page)
            except Exception as e:
                emit(f"poll error: {e}")
                time.sleep(POLL_INTERVAL_S)
                continue

            changed = (cur_url != last_url) or (cur_title != last_title) or (cur_dom != last_dom)
            if changed:
                step += 1
                label = f"{step:02d}"
                if cur_url != last_url:
                    label += "_urlchange"
                elif cur_title != last_title:
                    label += "_titlechange"
                else:
                    label += "_domchange"

                emit(f"CHANGE {label}: title='{cur_title}' url={cur_url}")
                try:
                    page.screenshot(path=str(session / f"{label}.png"), full_page=True)
                    (session / f"{label}.html").write_text(page.content(), encoding="utf-8")
                    # Dump main viz iframe too (where Tableau toolbar lives)
                    for i, fr in enumerate(page.frames):
                        if fr == page.main_frame:
                            continue
                        if "embed=y" in fr.url or "tableau" in fr.url:
                            try:
                                (session / f"{label}.frame{i}.html").write_text(fr.content(), encoding="utf-8")
                            except Exception:
                                pass
                except Exception as e:
                    emit(f"  snapshot error: {e}")

                last_url, last_title, last_dom = cur_url, cur_title, cur_dom

            time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    sys.exit(main())
