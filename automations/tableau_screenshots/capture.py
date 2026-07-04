"""Capture a Tableau view as a PNG on an already-authenticated patchright page.

This is the one genuinely new capability in the module. Auth + the warm session
are entirely reused (tableau_patchright.tableau_session yields the SSO'd page);
here we only: navigate to a view URL, wait for the viz to finish PAINTING, and
screenshot it.

Why a paint-settle loop (borrowed from captainship_drafts/sheet_shot.py): a
Tableau canvas keeps repainting for seconds AFTER the URL's load event -- it
draws the frame, then the marks, then text as the query returns. A fixed sleep
either clips a half-drawn viz or wastes time. Frame-comparison (screenshot until
consecutive frames are byte-identical) + an ink gate (reject a blank/near-blank
frame) is what reliably catches "done".

Cropping is deliberately configurable + defensive because it's the one thing
that needs live tuning on the mini:
  crop="full"   -> full_page screenshot (always captures everything; safe default
                   for the first mini run so we SEE the whole board).
  crop="canvas" -> clip to the detected Tableau viz element; falls back to
                   full_page with a printed warning if the element isn't found.
"""
from __future__ import annotations

import io
import re
import time
from pathlib import Path

# Candidate selectors for the Tableau viz container, largest-visible wins. Tableau
# Online's DOM changes across versions, so we try several and pick by area rather
# than pin one brittle selector.
_VIZ_SELECTORS = [
    ".tab-viz",
    "#tabZoneContainer",
    "[class*='tableauViz']",
    ".tabCanvas",
    "#view",
    "div[role='application']",
]

# A rendered frame with fewer "ink" (dark) pixels than this is still blank/loading.
_INK_LUMA = 110
_MIN_INK_PX = 1500


def _ink_pixels(png: bytes) -> int:
    """Count dark pixels in a PNG (proxy for 'has the table text painted yet')."""
    from PIL import Image
    hist = Image.open(io.BytesIO(png)).convert("L").histogram()
    return sum(hist[:_INK_LUMA])


def _sanitize(name: str) -> str:
    """Filesystem-safe file stem; keep it readable (spaces ok, drop path chars)."""
    return re.sub(r"[/\\:*?\"<>|]+", "-", name).strip()


def _viz_clip(page):
    """Bounding box {x,y,width,height} of the best-guess viz element, or None.

    Only returns a clip fully inside the current viewport -- page.screenshot(clip=)
    errors on a rect that spills past the viewport, and for an oversized viz
    full_page is the right capture anyway."""
    try:
        vp = page.viewport_size or {"width": 1680, "height": 1280}
        box = page.evaluate(
            """(sels) => {
                let best = null, bestA = 0;
                for (const s of sels) {
                  for (const el of document.querySelectorAll(s)) {
                    const r = el.getBoundingClientRect();
                    const a = r.width * r.height;
                    if (a > bestA && r.width > 200 && r.height > 200) {
                      bestA = a;
                      best = {x: r.x, y: r.y, width: r.width, height: r.height};
                    }
                  }
                }
                return best;
            }""",
            _VIZ_SELECTORS,
        )
    except Exception:
        return None
    if not box:
        return None
    # Reject clips that spill outside the viewport (oversized viz -> use full_page).
    if (box["x"] < -1 or box["y"] < -1
            or box["x"] + box["width"] > vp["width"] + 1
            or box["y"] + box["height"] > vp["height"] + 1):
        return None
    return box


def _wait_ready(page, *, timeout_s: float, verbose: bool) -> None:
    """Best-effort wait for a Tableau viz container to exist, then for the network
    to go quiet. Non-fatal: the paint-settle loop below is the real gate."""
    deadline = time.time() + timeout_s
    for sel in _VIZ_SELECTORS:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        try:
            page.wait_for_selector(sel, timeout=int(remaining * 1000), state="attached")
            break
        except Exception:
            continue
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass


def _shoot(page, clip):
    return page.screenshot(clip=clip) if clip else page.screenshot(full_page=True)


def capture_page(page, spec: dict, out_dir: Path, *,
                 settle_ms: int = 1400,
                 stable_frames: int = 3,
                 settle_timeout_s: float = 45.0,
                 ready_timeout_s: float = 90.0,
                 force_crop: str | None = None,
                 verbose: bool = True) -> Path:
    """Navigate `page` to spec['url'], wait for the viz to settle, save a PNG.

    Returns the written path. Raises on a genuinely failed render (never painted /
    stayed blank) so the caller can skip+flag that tracker.

    force_crop overrides spec['crop'] for the whole run (e.g. --full on the first
    mini pass so we see the entire board before tightening the canvas crop).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    crop = force_crop or spec.get("crop", "canvas")
    title = spec["title"]

    if verbose:
        print(f"-> [{spec['id']}] {spec['url']}", flush=True)
    # about:blank first so a re-used page always triggers a real load event.
    try:
        page.goto("about:blank")
    except Exception:
        pass
    page.goto(spec["url"], wait_until="domcontentloaded")
    _wait_ready(page, timeout_s=ready_timeout_s, verbose=verbose)

    # Resolve the clip once the layout has settled enough to measure it.
    page.wait_for_timeout(settle_ms)
    clip = _viz_clip(page) if crop == "canvas" else None
    if crop == "canvas" and clip is None and verbose:
        print(f"   (canvas element not found -- falling back to full_page)", flush=True)

    # Paint-settle: screenshot until consecutive frames are identical, gated on
    # the frame actually having ink (table text painted).
    deadline = time.time() + settle_timeout_s
    prev, same, last = None, 0, None
    while True:
        cur = _shoot(page, clip)
        last = cur
        if _ink_pixels(cur) >= _MIN_INK_PX:
            if prev is not None and cur == prev:
                same += 1
                if same >= (stable_frames - 1):
                    break
            else:
                same = 0
            prev = cur
        if time.time() > deadline:
            if _ink_pixels(last) < _MIN_INK_PX:
                raise RuntimeError(
                    f"{spec['id']}: viz never painted (blank after "
                    f"{settle_timeout_s:g}s) -- check the URL / session.")
            if verbose:
                print(f"   (settle timeout -- using best-effort frame)", flush=True)
            break
        page.wait_for_timeout(1100)

    stem = _sanitize(title)
    out_path = out_dir / f"{stem}.png"
    out_path.write_bytes(last)
    if verbose:
        kb = len(last) // 1024
        print(f"   saved {out_path.name} ({kb} KB, crop={crop}"
              f"{'/full-fallback' if crop == 'canvas' and clip is None else ''})",
              flush=True)
    return out_path
