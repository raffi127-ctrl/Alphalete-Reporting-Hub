"""One-off PREVIEW of the consolidated CHURNRATES board (Carlos 2026-09-05).

Tableau restructured churn: the view where wireless churn used to live now
shows BYOD wireless / non-BYOD wireless / AIR / internet churn together, and
the three per-product saved views have been rendering BLANK since 9/03. Carlos:
"if you don't filter when pulling the churn rates and you just have everything
selected, you can see everything and take one screenshot" — and he wants to SEE
that screenshot before the thread capture is rewired.

So this captures the churn view with NOTHING appended — no owner slice, no
product param, no crop — exactly as it opens, and base64-chunks the PNG into
the 'B2B Shot' tab of the Mini Control sheet (the vantura_churn 'Vantura Shot'
channel, different tab) for the mini to decode and hand to Carlos.

READ-ONLY apart from that tab. Runs on Lucy 2 (Carlos's login carries the
views) under the shared CDP-9246 lock like every other ATTTRACKER capture.

  lucy rerun b2b_churn_preview                # default: the old wireless URL
  ... --url <view url>                        # point somewhere else
  ... --owner JAMIS                           # drive the Owner & Office
                                              # dropdown to the one member
                                              # containing this (case-insens)
                                              # substring, logging EVERY member
                                              # spelling on the way — built
                                              # 2026-09-05 because the
                                              # restructured board blanks on
                                              # every URL Owner & Office value
                                              # we know, so the member list
                                              # itself is the ground truth.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "b2b_metrics_preview"
SHOT_TAB = "B2B Shot"


def _drive_owner(page, want: str, log=print) -> bool:
    """Open the dashboard's Owner & Office quick filter, log every member, and
    leave ONLY the member containing `want` (case-insensitive) ticked.

    Modelled line-for-line on capture._select_week: menu items are matched via
    the dropdown's own id token so we never toggle another filter's list, and
    toggles are KEYBOARD ONLY (focus + Space) — Tableau's click-capture overlay
    swallows .click() while leaving aria-checked untouched. Returns True when
    the wanted member ends up ticked."""
    from automations.b2b_quality.run import _IFRAME
    fr = page.frame_locator(_IFRAME)
    boxes = fr.locator(".tabComboBox")
    n_boxes = min(boxes.count(), 12)

    def _open(i):
        """Open box i's menu; return (loc, texts, checked) or None. The ids on
        this dashboard are EMPTY (probed 2026-09-05), so the menu is read with
        the generic selectors and the CALLER decides if it's the right list."""
        for osel in (".tabComboBox", ".tabComboBoxButton", ".tabComboBoxName"):
            try:
                fr.locator(osel).nth(i).click(timeout=10_000)
            except Exception:  # noqa: BLE001
                try:
                    fr.locator(osel).nth(i).focus()
                    page.keyboard.press("Enter")
                except Exception:  # noqa: BLE001
                    continue
            page.wait_for_timeout(2_500)
            for sel in ('[role="checkbox"]', ".QFCheckbox", "[role='option']",
                        ".tabMenuItemName"):
                try:
                    loc = fr.locator(sel)
                    n = min(loc.count(), 300)
                except Exception:  # noqa: BLE001
                    continue
                if not n:
                    continue
                texts, checked = [], []
                for j in range(n):
                    try:
                        texts.append(" ".join(
                            (loc.nth(j).inner_text(timeout=2_000) or "")
                            .split()).lstrip("✓").strip())
                        checked.append(loc.nth(j).get_attribute("aria-checked")
                                       == "true")
                    except Exception:  # noqa: BLE001
                        texts.append("")
                        checked.append(False)
                if any(texts):
                    return loc, texts, checked
        return None

    # Find the Owner & Office box by CONTENT: it is the one whose members carry
    # the " [office]" suffix. Escape closes a wrong box's menu before moving on.
    for i in range(n_boxes):
        try:
            val = " ".join((boxes.nth(i).inner_text(timeout=5_000) or "").split())
        except Exception:  # noqa: BLE001
            val = "?"
        got = _open(i)
        if not got:
            log("   [owner] box[{}] value={!r}: no menu".format(i, val[:30]))
            continue
        loc, texts, checked = got
        sample = [t for t in texts if t][:6]
        is_owner = any("[" in t for t in texts)
        log("   [owner] box[{}] value={!r} {} items, owner_list={} sample: {}"
            .format(i, val[:30], len(texts), is_owner, " | ".join(sample)))
        if not is_owner:
            page.keyboard.press("Escape")
            page.wait_for_timeout(1_000)
            continue
        for j, t in enumerate(texts):
            if t:
                log("   [owner]   [{}] {}{!r}".format(
                    j, "[x] " if checked[j] else "[ ] ", t))
        picks = [j for j, t in enumerate(texts)
                 if t and want.lower() in t.lower()]
        if not picks:
            log("   [owner] NO member contains {!r} — real spellings above"
                .format(want))
            page.keyboard.press("Escape")
            return False
        pick = picks[0]

        def _set(j, on):
            el = loc.nth(j)
            try:
                if (el.get_attribute("aria-checked") == "true") == on:
                    return True
                el.focus()
                page.keyboard.press(" ")
                page.wait_for_timeout(800)
                return (el.get_attribute("aria-checked") == "true") == on
            except Exception:  # noqa: BLE001
                return False

        # Tick the target FIRST (clearing the last ticked value makes Tableau
        # re-select everything), then untick every other row — "(All)" too.
        ok = _set(pick, True)
        for j, t in enumerate(texts):
            if j != pick and t:
                _set(j, False)
        try:
            ap = fr.locator("button:has-text('Apply')")
            if ap.count():
                ap.first.click(timeout=5_000)
        except Exception:  # noqa: BLE001
            pass
        page.keyboard.press("Escape")
        page.wait_for_timeout(12_000)          # let the viz redraw
        log("   [owner] selected {!r} -> {}".format(texts[pick], ok))
        return ok
    log("   [owner] no combo box offered an owner-style member list")
    return False


def main(argv=None) -> int:
    from automations.b2b_metrics.offices import TEAM
    ap = argparse.ArgumentParser(prog="b2b_metrics.churn_preview")
    ap.add_argument("--url", default=TEAM["churn_wireless"],
                    help="view to capture as-is (default: the churn_wireless "
                         "team view — 'literally where the wireless churn "
                         "used to be')")
    ap.add_argument("--owner", default=None,
                    help="drive the Owner & Office dropdown to the one member "
                         "containing this substring (logs every member)")
    args = ap.parse_args(argv)

    from patchright.sync_api import sync_playwright
    from automations.shared import tableau_patchright as tp
    from automations.tableau_screenshots.capture import capture_page
    from automations.vantura_churn import cdp_pull

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    spec = {"id": "churn_preview", "title": "churn_preview", "url": args.url}
    print(f"capturing AS-IS (no slice, no crop): {args.url}", flush=True)

    with cdp_pull._cdp_lock(label="b2b churn_preview", log=print):
        cdp_pull._kill_ours()
        proc = cdp_pull._launch()
        try:
            with sync_playwright() as p:
                browser = None
                for attempt in range(10):
                    time.sleep(5)
                    try:
                        browser = p.chromium.connect_over_cdp(
                            "http://127.0.0.1:{}".format(cdp_pull.CDP_PORT))
                        break
                    except Exception:  # noqa: BLE001 — port not up yet
                        if attempt == 9:
                            raise
                ctx = (browser.contexts[0] if browser.contexts
                       else browser.new_context())
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                tp._ensure_tableau_authenticated(page, verbose=False,
                                                 allow_form_login=True)
                after = ((lambda pg: _drive_owner(pg, args.owner, log=print))
                         if args.owner else None)
                capture_page(page, spec, OUT_DIR, after_load=after,
                             verbose=True)
        finally:
            cdp_pull._kill_ours()
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass

    out = OUT_DIR / "churn_preview.png"
    if not out.exists() or out.stat().st_size < 5000:
        print(f"capture FAILED — {out} missing or tiny", flush=True)
        return 1
    cdp_pull._upload_png(out.read_bytes(), tab=SHOT_TAB)
    print(f"OK {out.stat().st_size} bytes -> sheet tab {SHOT_TAB!r}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
