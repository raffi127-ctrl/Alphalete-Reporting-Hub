"""Capture a Tableau view as a full-board PNG via Tableau's own Download → Image.

Target framing (Jolie's posts, confirmed 2026-07-04): the ENTIRE dashboard — its
blue title bar, the filter/parameter row, and every table/rep row — with NO
browser chrome, NO Tableau viewer toolbar, NO gray canvas, and no clipping.
That is exactly what Tableau's Download → Image produces, so this module drives
that menu and saves the resulting PNG. There is deliberately NO screenshot
fallback: a page/full_page screenshot drags in the browser + toolbar + gray
canvas ("too much") and clips the tall boards, so on failure we RAISE and let the
caller skip+flag that tracker rather than post a wrong-looking image.

The viz lives inside `iframe[title="Data Visualization"]`. We reuse the Download
machinery proven in recruiting_report.opt_phase (toolbar button, error-toast
clear) and add a retry + a tolerant Image-menu / export-dialog path.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

_IFRAME = 'iframe[title="Data Visualization"]'
_DL_BTN = '[data-tb-test-id="viz-viewer-toolbar-button-download"]'
# Confirmed sibling id is 'download-flyout-download-crosstab-MenuItem'; Image is
# the analogous item. Text fallback below in case the id shifts across versions.
_IMAGE_ITEM = '[data-tb-test-id="download-flyout-download-image-MenuItem"]'

MAX_ATTEMPTS = 3
BACKOFF_S = 4


def _sanitize(name: str) -> str:
    return re.sub(r"[/\\:*?\"<>|]+", "-", name).strip()


def _clear_error_toast(viz, page, verbose: bool) -> None:
    """Dismiss a Tableau viz error toast that overlays + intercepts the toolbar
    (mirrors opt_phase._clear_error_toast). No-op when there's no toast."""
    toast = viz.locator('[data-tb-test-id^="banner-error-toast"]')
    try:
        if toast.count() == 0:
            return
    except Exception:
        return
    try:
        msg = toast.first.inner_text(timeout=2_000).strip()
    except Exception:
        msg = "(toast text unreadable)"
    if verbose:
        print(f"   ⚠ Tableau error toast over Download: {msg!r} — dismissing",
              flush=True)
    for sel in ('button[aria-label*="lose" i]', 'button[aria-label*="ismiss" i]',
                '[data-tb-test-id*="dismiss" i]', '[data-tb-test-id*="close" i]'):
        try:
            btn = toast.locator(sel)
            if btn.count() > 0:
                btn.first.click(timeout=3_000)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue
    try:
        toast.first.evaluate(
            "el => { (el.closest('.tab-shared-widget-toaster') || el).remove(); }")
    except Exception:
        pass
    page.wait_for_timeout(500)


def _click_image_item(viz, page) -> None:
    """Click the Download flyout's 'Image' item — by test-id, then by text."""
    item = viz.locator(_IMAGE_ITEM)
    try:
        if item.count() > 0:
            item.first.click(timeout=5_000)
            return
    except Exception:
        pass
    viz.get_by_text("Image", exact=True).first.click(timeout=5_000)


def _maybe_click_export_dialog(viz, page) -> None:
    """Some Tableau builds pop an 'Image' export dialog with its OWN Download
    button after the menu item; others download directly. Poll briefly for a
    dialog Download button and click it if present. No-op on the direct-download
    path (the menu click already fired the download)."""
    deadline = time.time() + 6
    while time.time() < deadline:
        for loc in (
            viz.locator('[data-tb-test-id*="export-image" i] button'),
            viz.locator('[role="dialog"]').get_by_role(
                "button", name=re.compile(r"^\s*download\s*$", re.I)),
            viz.get_by_role("button", name=re.compile(r"^\s*download\s*$", re.I)),
        ):
            try:
                if loc.count() > 0 and loc.first.is_visible(timeout=500):
                    loc.first.click(timeout=3_000)
                    return
            except Exception:
                continue
        page.wait_for_timeout(500)


def _download_once(page, spec: dict, out_path: Path, *, hydrate_ms: int,
                   verbose: bool) -> Path:
    try:
        page.goto("about:blank", timeout=10_000)
    except Exception:
        pass
    page.goto(spec["url"], wait_until="domcontentloaded")

    viz = page.frame_locator(_IFRAME)
    dl_btn = viz.locator(_DL_BTN)
    dl_btn.wait_for(state="visible", timeout=120_000)
    page.wait_for_timeout(hydrate_ms)          # let the data hydrate behind the viz

    _clear_error_toast(viz, page, verbose)
    dl_btn.click()
    page.wait_for_timeout(1800)                # flyout opens

    with page.expect_download(timeout=180_000) as dl_info:
        _click_image_item(viz, page)
        _maybe_click_export_dialog(viz, page)
    dl_info.value.save_as(str(out_path))
    return out_path


def _dims(path: Path) -> str:
    try:
        from PIL import Image
        with Image.open(path) as im:
            return f"{im.width}x{im.height}"
    except Exception:
        return "?x?"


def inspect_view(page, spec: dict, *, verbose: bool = True) -> dict:
    """Read-only structure probe: navigate to the view, then dump the dashboard
    TAB strip names and the Download → Image dialog contents, so we can see how
    to target a SINGLE page (separate tab URL vs 'This View' vs a sheet picker).
    No download."""
    import json
    try:
        page.goto("about:blank", timeout=10_000)
    except Exception:
        pass
    page.goto(spec["url"], wait_until="domcontentloaded")
    viz = page.frame_locator(_IFRAME)
    viz.locator(_DL_BTN).wait_for(state="visible", timeout=120_000)
    page.wait_for_timeout(15_000)
    info: dict = {"id": spec["id"], "url": spec["url"], "tabs": [], "dialog": ""}

    # Dashboard tab strip (the "PAGE 1 / PAGE 2 / PAGE 3" tabs, if any).
    for sel in ('[role="tab"]', '[data-tb-test-id*="Tabs" i] [role="tab"]',
                '.tabTabControl [role="tab"]', '.tab-tabs [role="tab"]'):
        try:
            loc = viz.locator(sel)
            n = loc.count()
            if n:
                info["tabs"] = [loc.nth(i).inner_text()[:60] for i in range(min(n, 20))]
                info["tabs_sel"] = sel
                break
        except Exception:
            continue

    # Open Download → Image and dump the dialog (radio options / sheet picker).
    try:
        _clear_error_toast(viz, page, verbose)
        viz.locator(_DL_BTN).click()
        page.wait_for_timeout(1500)
        _click_image_item(viz, page)
        page.wait_for_timeout(3000)
        for sel in ('[role="dialog"]', '[data-tb-test-id*="dialog" i]',
                    '[data-tb-test-id*="export" i]'):
            try:
                dlg = viz.locator(sel)
                if dlg.count() > 0:
                    info["dialog"] = dlg.first.inner_text(timeout=3000)[:900]
                    info["dialog_sel"] = sel
                    break
            except Exception:
                continue
    except Exception as e:
        info["dialog_err"] = f"{type(e).__name__}: {str(e)[:120]}"

    print("INSPECT " + json.dumps(info, ensure_ascii=False), flush=True)
    return info


def capture_page(page, spec: dict, out_dir: Path, *,
                 hydrate_ms: int = 20_000,
                 force_crop: str | None = None,   # accepted for CLI compat; unused
                 verbose: bool = True) -> Path:
    """Navigate to spec['url'] and save the full board via Download → Image.
    Retries on transient Tableau flakes. Raises after MAX_ATTEMPTS — NO screenshot
    fallback (a screenshot would be 'too much' + clipped), so the caller skip+flags.
    Returns the written path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_sanitize(spec['title'])}.png"
    if verbose:
        print(f"-> [{spec['id']}] {spec['url']}", flush=True)
    last = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            _download_once(page, spec, out_path, hydrate_ms=hydrate_ms,
                           verbose=verbose)
            kb = out_path.stat().st_size // 1024
            if verbose:
                print(f"   ✓ Download→Image  {out_path.name}  "
                      f"{_dims(out_path)}px  {kb} KB", flush=True)
            return out_path
        except Exception as e:
            last = e
            if verbose:
                print(f"   attempt {attempt}/{MAX_ATTEMPTS} failed: "
                      f"{type(e).__name__}: {str(e).splitlines()[0][:110]}",
                      flush=True)
            if attempt < MAX_ATTEMPTS:
                time.sleep(BACKOFF_S)
    raise RuntimeError(
        f"{spec['id']}: Download→Image failed after {MAX_ATTEMPTS} attempts "
        f"({type(last).__name__}: {str(last).splitlines()[0][:120]})")
