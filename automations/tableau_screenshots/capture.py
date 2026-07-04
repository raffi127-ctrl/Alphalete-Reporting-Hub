"""Capture a Tableau view as a full-board PNG on an authenticated patchright page.

Approach (revised 2026-07-04): drive Tableau's own **Download -> Image** rather
than screenshotting the browser. Why: the Tableau viz renders inside an
`iframe[title="Data Visualization"]` and paints its big tables in an INTERNAL
scroll box, so a page/full_page screenshot clips the bottom rows of the tall
boards (the D2D pagers, the consolidated board). Tableau's image export renders
the ENTIRE dashboard at its authored size -- full rows, no toolbar, no cutoff --
which is what makes Jolie's posts look complete.

Reuses the Download-dialog machinery proven in recruiting_report.opt_phase
(the iframe selector, the toolbar Download button, the error-toast clear). The
only differences vs the crosstab path: pick the **Image** menu item, and there's
no worksheet picker -- Image downloads the whole dashboard directly.

Fallback: if image-export fails (button disabled / menu missing), fall back to a
full_page screenshot so a run still yields something, flagged in the log.
"""
from __future__ import annotations

from pathlib import Path

_IFRAME = 'iframe[title="Data Visualization"]'
_DL_BTN = '[data-tb-test-id="viz-viewer-toolbar-button-download"]'
# By analogy with the confirmed crosstab item id
# ('download-flyout-download-crosstab-MenuItem'); text fallback below in case the
# id shifts across Tableau versions.
_IMAGE_ITEM = '[data-tb-test-id="download-flyout-download-image-MenuItem"]'


def _sanitize(name: str) -> str:
    import re
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


def _click_image_item(viz, page, verbose: bool) -> None:
    """Click the Download flyout's 'Image' item -- by test-id, then by text."""
    item = viz.locator(_IMAGE_ITEM)
    try:
        if item.count() > 0:
            item.first.click(timeout=5_000)
            return
    except Exception:
        pass
    # Text fallback: the flyout item literally reads 'Image'.
    viz.get_by_text("Image", exact=True).first.click(timeout=5_000)


def _download_image(page, spec: dict, out_path: Path, *,
                    hydrate_ms: int, verbose: bool) -> Path:
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

    # Image downloads the whole dashboard directly (no worksheet picker).
    with page.expect_download(timeout=180_000) as dl_info:
        _click_image_item(viz, page, verbose)
    dl_info.value.save_as(str(out_path))
    if verbose:
        print(f"   saved {out_path.name} "
              f"({out_path.stat().st_size // 1024} KB, Download→Image)", flush=True)
    return out_path


def _fallback_screenshot(page, out_path: Path, verbose: bool) -> Path:
    """Last resort so a run isn't empty: full_page screenshot (may clip tall
    boards -- logged so we know it happened)."""
    if verbose:
        print("   ⚠ image-export failed — falling back to full_page screenshot "
              "(may clip tall boards)", flush=True)
    page.screenshot(path=str(out_path), full_page=True)
    return out_path


def capture_page(page, spec: dict, out_dir: Path, *,
                 hydrate_ms: int = 20_000,
                 force_crop: str | None = None,   # accepted for CLI compat; unused
                 verbose: bool = True) -> Path:
    """Navigate `page` to spec['url'] and save the full board as a PNG via
    Tableau's Download → Image (screenshot fallback). Returns the written path.

    Raises only if BOTH image-export and the screenshot fallback fail, so the
    caller can skip+flag that tracker.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_sanitize(spec['title'])}.png"
    if verbose:
        print(f"-> [{spec['id']}] {spec['url']}", flush=True)
    try:
        return _download_image(page, spec, out_path,
                               hydrate_ms=hydrate_ms, verbose=verbose)
    except Exception as e:
        if verbose:
            print(f"   image-export error: {type(e).__name__}: "
                  f"{str(e).splitlines()[0][:120]}", flush=True)
        return _fallback_screenshot(page, out_path, verbose)
