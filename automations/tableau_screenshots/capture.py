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

# Diagnostic: per-tracker bottom-band structure, written to the sheet by run.py.
TRIM_DEBUG: dict = {}
# Diagnostic: per-tracker crop math (marker frac, top ref, pre/post-crop height),
# written to the sheet by run.py so the exact cut point is visible off-machine.
CROP_DEBUG: dict = {}

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


# These pager dashboards stack PAGE 1 (This Week) + a PAGE 2 (Last Week) + maybe a
# Trends page in one tall dashboard; Download→Image exports all of it. Jolie posts
# only PAGE 1, so we find the header that starts page 2 and crop the image to just
# above it. The page-2 header text differs per workbook, so each multi-page
# tracker sets spec['crop_before'] (a regex); the default catches the "PAGE 2"
# wording. Self-classifying: single-page trackers have no such header -> no crop.
_DEFAULT_CROP_MARKER = r"PAGE\s*2\b"

# Measure where page 2 starts as a fraction of the DASHBOARD CONTENT span (top of
# the PAGE-1 header -> bottom-most content), NOT of a scroll container (which can
# include the toolbar/tab-strip above the dashboard and shrink the fraction, so the
# crop cuts too high — the internet_only bug). Download→Image renders exactly this
# content span, so the fraction maps straight onto the image height.
_CROP_JS = r"""
({marker, topMarker}) => {
  const re = new RegExp(marker, 'i');
  const tre = new RegExp(topMarker, 'i');
  const leaves = [...document.querySelectorAll('*')]
      .filter(e => e.children.length === 0 && (e.textContent||'').trim());
  const hit = leaves.find(e => re.test(e.textContent.trim()));
  if (!hit) return null;
  // Top reference = the dashboard TITLE (topMarker), NOT the toolbar. Without it,
  // min-leaf-top is the Tableau toolbar (above the dashboard) and the fraction is
  // wrong for any dashboard whose title isn't "PAGE 1" (nds, b2b).
  const topEl = leaves.find(e => tre.test(e.textContent.trim()));
  const rects = leaves.map(e => e.getBoundingClientRect())
      .filter(r => r.width > 0 && r.height > 0);
  if (!rects.length) return null;
  const top = topEl ? topEl.getBoundingClientRect().top
                    : Math.min(...rects.map(r=>r.top));
  const bottom = Math.max(...rects.map(r=>r.bottom));
  const hy = hit.getBoundingClientRect().top;
  const span = bottom - top;
  if (span <= 0) return null;
  return {frac: (hy - top) / span, text: hit.textContent.trim().slice(0,50),
          topUsed: topEl ? topEl.textContent.trim().slice(0,40) : 'MIN-LEAF',
          hy: Math.round(hy), top: Math.round(top), bottom: Math.round(bottom),
          span: Math.round(span)};
}
"""


def _page1_crop_fraction(page, spec: dict, verbose: bool):
    """Fraction (0-1) of the dashboard height where page 2 starts, or None if this
    is a single-page dashboard (marker not found). Scale-invariant, so it maps
    straight onto the exported image height."""
    marker = spec.get("crop_before", _DEFAULT_CROP_MARKER)
    top_marker = spec.get("crop_top", r"PAGE\s*1\b")
    try:
        el = page.query_selector(_IFRAME)
        frame = el.content_frame() if el else None
        if frame is None:
            return None
        res = frame.evaluate(_CROP_JS, {"marker": marker, "topMarker": top_marker})
    except Exception as e:
        if verbose:
            print(f"   crop probe failed ({type(e).__name__}) — no crop", flush=True)
        return None
    if not res:
        return None
    frac = res.get("frac")
    CROP_DEBUG[spec.get("id", "")] = (
        f"marker={res.get('text')!r} frac={frac:.4f} topUsed={res.get('topUsed')!r} "
        f"hy={res.get('hy')} top={res.get('top')} bottom={res.get('bottom')} "
        f"span={res.get('span')} margin={_CROP_MARGIN_FRAC}")
    if verbose:
        print(f"   page-2 marker {res.get('text')!r} at frac={frac:.3f} "
              f"— cropping to Page 1", flush=True)
    return frac


# Cut a hair ABOVE the page-2 header so its top sliver never shows in Page 1
# (Megan 2026-07-04: att_country showed a bit of the next header). ~1.5% of height.
_CROP_MARGIN_FRAC = 0.015


def _crop_top(path: Path, frac: float, verbose: bool) -> None:
    """Crop the PNG to its top `frac` (full width) = the Page-1 region, pulled up
    by a small margin so the next page's header doesn't peek in."""
    from PIL import Image
    frac = max(0.02, frac - _CROP_MARGIN_FRAC)
    with Image.open(path) as im:
        w, h = im.size
        cut = max(1, min(h, round(h * frac)))
        im.crop((0, 0, w, cut)).save(path)
    if verbose:
        print(f"   cropped {path.name} to top {frac:.1%} ({w}x{cut})", flush=True)


def _blue_bar_tops(path: Path) -> list:
    """Y of the top of each FULL-WIDTH dark-blue section bar in the image, top to
    bottom. Tableau renders each section header (the dashboard title, and each
    '... LAST WEEK' / 'Last Week' section) as a solid dark-blue band spanning the
    whole width; data cells + whitespace never do. Scale-invariant (reads the
    rendered pixels), so it beats the DOM-fraction estimate for a precise bottom."""
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(path).convert("RGB")).astype(int)
    h, w, _ = a.shape
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    # Tableau header blue ~ (26,61,109): clearly blue (B well above R/G) and dark.
    blue = (B > 60) & (B < 175) & (R < 100) & (G < 120) & (B > R + 15) & (B > G + 3)
    frac = blue.mean(axis=1)                     # share of the row that is bar-blue
    tops, prev = [], -10
    for y in np.where(frac > 0.5)[0]:            # >50% wide => a full-width bar
        if y - prev > 5:                         # new bar (not the same band)
            tops.append(int(y))
        prev = int(y)
    return tops


def _crop_above_bar(path: Path, bar_index: int, verbose: bool, spec_id: str = "") -> None:
    """Crop the image to just above the Nth (1-based) full-width blue section bar,
    dropping that section and everything below it. Used for the pager dashboards
    whose 'next section' (Last Week) bled into the DOM-fraction crop — snapping to
    the bar in IMAGE space is exact regardless of the DOM/image scale. Falls back
    to no-op (leaving the DOM crop / full image) if the bar isn't found."""
    from PIL import Image
    tops = _blue_bar_tops(path)
    CROP_DEBUG[spec_id] = CROP_DEBUG.get(spec_id, "") + f" blueBars={tops} wantBar#{bar_index}"
    if len(tops) < bar_index:
        if verbose:
            print(f"   crop-to-bar: found {len(tops)} blue bar(s), need "
                  f"#{bar_index} — leaving as-is", flush=True)
        return
    cut = max(1, tops[bar_index - 1] - 4)        # a few px above the bar's top edge
    with Image.open(path) as im:
        w, h = im.size
        if cut < h - 2:
            im.crop((0, 0, w, cut)).save(path)
            CROP_DEBUG[spec_id] = CROP_DEBUG.get(spec_id, "") + f" barCut={cut}(<-{h})"
            if verbose:
                print(f"   cropped above blue bar #{bar_index} ({h}->{cut}px)",
                      flush=True)


def _trim_bottom(path: Path, verbose: bool, margin_px: int = 14,
                 spec_id: str = "") -> None:
    """Trim the bottom of the PNG to the board's real end. Download→Image leaves a
    big blank gap + a small footer ('Last Object Update…', '***CONFIDENTIAL***')
    below the content that Jolie's posts don't have. Split the image into content
    BANDS (runs of non-blank rows) and peel off trailing bands that are SMALL and
    separated from the content above by a real gap (i.e. footer lines) — then cut
    just below the last real content. Generic — single-page + cropped alike; a
    cropped page-1 has no footer band so it just loses trailing whitespace."""
    import numpy as np
    from PIL import Image
    im = Image.open(path).convert("RGB")
    arr = np.asarray(im.convert("L")).astype(np.int16)
    h, w = arr.shape
    # A blank row is UNIFORM (near-constant color), whether the dashboard bg is
    # white OR light-gray. Content rows have dark text/lines -> big min..max range.
    # (The old `< 245` white test missed gray-bg whitespace, so nothing trimmed.)
    row_has = (arr.max(axis=1) - arr.min(axis=1)) >= 22
    bands, y = [], 0                            # content bands [start, end)
    while y < h:
        if row_has[y]:
            s = y
            while y < h and row_has[y]:
                y += 1
            bands.append((s, y))
        else:
            y += 1
    # DIAGNOSTIC: the last 8 content bands as (start,end,gap-before) + row-range
    # stats for the bottom 700px, so we can see why the tail isn't registering.
    tail = []
    for k in range(max(0, len(bands) - 8), len(bands)):
        s, e = bands[k]
        gap = s - bands[k - 1][1] if k > 0 else 0
        tail.append((int(s), int(e), int(gap)))
    rng = arr.max(axis=1) - arr.min(axis=1)
    bot = rng[-700:] if h > 700 else rng
    TRIM_DEBUG[spec_id] = (
        f"h={h} nbands={len(bands)} tail={tail} "
        f"bot700_rng[min/med/max]={int(bot.min())}/{int(np.median(bot))}/{int(bot.max())}")

    if not bands:
        return
    # Cut just after the last SUBSTANTIAL content band (>= 100px tall). Trailing
    # bands smaller than that are footer lines ("Last Object Update…",
    # "***CONFIDENTIAL***") — drop them and any whitespace, regardless of the gaps
    # between them. Real tables are >=140px, footers <=~76px, so 100 separates.
    main_end = bands[-1][1]
    for s, e in reversed(bands):
        if (e - s) >= 100:
            main_end = e
            break
    new_h = min(h, main_end + margin_px)
    TRIM_DEBUG[spec_id] += f" -> cut={new_h}"
    if new_h < h - 2:
        im.crop((0, 0, w, new_h)).save(path)
        if verbose:
            print(f"   trimmed bottom to content end ({h}->{new_h}px)", flush=True)


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
    # Measure the Page-1 crop BEFORE opening the download flyout (the flyout can
    # shift the DOM). None for single-page dashboards.
    crop_frac = _page1_crop_fraction(page, spec, verbose)

    dl_btn.click()
    page.wait_for_timeout(1800)                # flyout opens

    with page.expect_download(timeout=180_000) as dl_info:
        _click_image_item(viz, page)
        _maybe_click_export_dialog(viz, page)
    dl_info.value.save_as(str(out_path))

    _sid = spec.get("id", "")
    try:
        from PIL import Image as _Im
        with _Im.open(out_path) as _im0:
            CROP_DEBUG[_sid] = CROP_DEBUG.get(_sid, "") + f" preCropH={_im0.height}"
    except Exception:
        pass
    # Two crop strategies. crop_to_bar (nds, b2b): snap the bottom to just above
    # the Nth blue section bar in IMAGE space — exact, scale-proof. Otherwise the
    # DOM-fraction crop (default for the approved single/pager trackers).
    if spec.get("crop_to_bar"):
        _crop_above_bar(out_path, int(spec["crop_to_bar"]), verbose, spec_id=_sid)
    elif crop_frac is not None and 0.05 < crop_frac < 0.95:
        _crop_top(out_path, crop_frac, verbose)
    else:
        CROP_DEBUG[_sid] = CROP_DEBUG.get(_sid, "") + " NO-TOP-CROP"
    try:
        from PIL import Image as _Im
        with _Im.open(out_path) as _im1:
            CROP_DEBUG[_sid] = CROP_DEBUG.get(_sid, "") + f" postCropH={_im1.height}"
    except Exception:
        pass
    try:
        _trim_bottom(out_path, verbose, spec_id=spec.get("id", ""))
    except Exception as e:
        TRIM_DEBUG[spec.get("id", "")] = f"ERROR {type(e).__name__}: {str(e)[:120]}"
        if verbose:
            print(f"   bottom-trim skipped ({type(e).__name__}: {str(e)[:80]})",
                  flush=True)
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

    # Which tab is currently active/selected.
    try:
        active = viz.locator('[role="tab"][aria-selected="true"]')
        if active.count() > 0:
            info["active_tab"] = active.first.inner_text()[:60]
    except Exception:
        pass

    # Open the Download flyout, dump its menu items, then click Image and dump the
    # WHOLE frame text (so a sheet-picker dialog's options, if any, are captured —
    # or, if Image downloads directly, we just see the dashboard text).
    try:
        _clear_error_toast(viz, page, verbose)
        viz.locator(_DL_BTN).click()
        page.wait_for_timeout(1500)
        try:
            menu = viz.locator('[data-tb-test-id*="download-flyout" i], '
                               '[data-tb-test-id*="flyout" i]')
            if menu.count() > 0:
                info["download_menu"] = menu.first.inner_text(timeout=2000)[:400]
        except Exception:
            pass
        _click_image_item(viz, page)
        page.wait_for_timeout(3000)
        try:
            info["dialog"] = viz.locator("body").inner_text(timeout=4000)[:25000]
        except Exception as e:
            info["dialog_err"] = f"body read: {type(e).__name__}: {str(e)[:80]}"
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
