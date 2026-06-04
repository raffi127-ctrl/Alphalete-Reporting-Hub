"""Real Google Sheets screenshots for the Captainship drafts.

The Product Summary + Captainship Units sections are captured as actual
browser screenshots of the 'Alphalete ORG Sales Board' sheet (so they
look EXACTLY like the sheet on screen — expanded weekly historicals and
all), driven by patchright.

Auth: a DEDICATED persistent Chrome profile (separate from the Tableau
automation profile so we never disturb that flow), logged into Google as
alphaletereporting@gmail.com — the account that can open the sheet. Log
in once (interactive, headed):

    python -m automations.captainship_drafts.sheet_shot login

The cookie persists in the profile; later headless runs reuse it. If
Google ever logs the profile out (cookie expiry / 2FA challenge), re-run
the login command.
"""
from __future__ import annotations

import math
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Tuple

from patchright.sync_api import sync_playwright

from automations.captainship_drafts.sales_board import (
    SALES_BOARD_ID, UNITS_ROWS, _open_ws, ps_range, units_day_columns,
)

SHEETS_PROFILE_DIR = (
    Path.home() / ".config" / "recruiting-report" / "sheets-browser-profile"
)
LOGIN_ACCOUNT = "alphaletereporting@gmail.com"
_SHEET_EDIT_URL = f"https://docs.google.com/spreadsheets/d/{SALES_BOARD_ID}/edit"

# How capture works: the URL `#gid=<gid>&range=<rng>` fragment makes the
# editor scroll to AND select the range. The grid itself is a canvas, but
# the selection is drawn as DOM overlay divs (.selection + .range-border)
# positioned exactly over the range — so we read the selection div's
# bounding rect for a pixel-exact crop, hide the overlays via injected
# CSS (so no blue tint / border / autofill nub taints the image), and
# screenshot with clip=rect.
_HIDE_OVERLAYS_CSS = (
    ".selection, .range-border, .autofill-cover, .autofill-handle,"
    " .touch-selection-handle { visibility: hidden !important; }")

_DEFAULT_VIEWPORT = {"width": 1600, "height": 1100}
_VIEWPORT_PAD = 80               # room for scrollbars beyond the range
_MAX_VIEWPORT = (4400, 12000)    # sanity cap; tallest PS range is ~4.2k css px


def _launch(p, headless: bool, viewport: dict | None = None,
            device_scale_factor: float | None = None):
    SHEETS_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    kw: dict = dict(user_data_dir=str(SHEETS_PROFILE_DIR), headless=headless)
    if viewport is None:
        kw["no_viewport"] = True
    else:
        kw["viewport"] = viewport
        if device_scale_factor:
            kw["device_scale_factor"] = device_scale_factor
    try:
        return p.chromium.launch_persistent_context(channel="chrome", **kw)
    except Exception:
        return p.chromium.launch_persistent_context(**kw)


def _is_authenticated(page) -> bool:
    """True if `page` is on the sheet editor (not a Google sign-in wall)."""
    url = page.url
    if "accounts.google.com" in url:
        return False
    if "docs.google.com/spreadsheets" not in url:
        return False
    # The editor exposes the menubar / grid once loaded.
    try:
        return page.locator("#docs-chrome, .grid-container, [role='grid']").count() > 0
    except Exception:
        return False


def login(timeout_s: int = 300) -> bool:
    """Open a headed browser to the sheet and wait for the user to sign in
    as alphaletereporting@gmail.com. Returns True once authenticated."""
    print(f"Opening a browser window. Sign in as {LOGIN_ACCOUNT} "
          f"(the account that can open the Sales Board).")
    print("This window will close automatically once login is detected "
          f"(waiting up to {timeout_s}s).")
    with sync_playwright() as p:
        ctx = _launch(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(_SHEET_EDIT_URL, wait_until="domcontentloaded")
        deadline = time.time() + timeout_s
        ok = False
        while time.time() < deadline:
            if _is_authenticated(page):
                ok = True
                break
            page.wait_for_timeout(2000)
        if ok:
            print(f"✓ Logged in — profile saved at {SHEETS_PROFILE_DIR}")
        else:
            print("✗ Timed out before login was detected. Re-run and finish "
                  "the Google sign-in (incl. 2FA) before the timeout.")
        # Give cookies a moment to flush to disk, then close.
        page.wait_for_timeout(1500)
        ctx.close()
        return ok


def check() -> bool:
    """Headless check that the saved profile can open the sheet."""
    with sync_playwright() as p:
        ctx = _launch(p, headless=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(_SHEET_EDIT_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        ok = _is_authenticated(page)
        print("✓ Authenticated" if ok else f"✗ Not authenticated (at {page.url[:80]})")
        ctx.close()
        return ok


# --------------------------------------------------------------------------
# Range screenshots
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _gid() -> int:
    """gid of the Sales Board tab (looked up by tab name, not hardcoded)."""
    return _open_ws().id


def _selection_rect(page) -> dict | None:
    """Viewport rect of the current selection overlay, or None if absent."""
    return page.evaluate("""() => {
        for (const el of document.querySelectorAll('.selection')) {
            const b = el.getBoundingClientRect();
            if (b.width > 1 && b.height > 1)
                return {x: b.x, y: b.y, width: b.width, height: b.height};
        }
        return null;
    }""")


def _goto_range(page, rng: str, timeout_s: int) -> dict:
    """Navigate to the sheet with `rng` selected; return the selection rect
    once it has STOPPED MOVING. The editor keeps shifting layout for a few
    seconds after load (row-header strip widens for 4-digit rows, toolbar
    chrome finishes, the grid re-anchors after tiles paint) — a rect read
    too early drifts off the range by the time the screenshot is taken."""
    page.goto(f"{_SHEET_EDIT_URL}#gid={_gid()}&range={rng}",
              wait_until="domcontentloaded")
    deadline = time.time() + timeout_s
    prev, stable = None, 0
    while time.time() < deadline:
        if "accounts.google.com" in page.url:
            raise RuntimeError(
                f"Google signed the profile out — re-run: python -m "
                f"automations.captainship_drafts.sheet_shot login")
        rect = _selection_rect(page)
        if rect is not None and prev is not None and all(
                abs(rect[k] - prev[k]) < 0.5 for k in rect):
            stable += 1
            if stable >= 2:        # unchanged across 2 polls (~1.6s)
                return rect
        else:
            stable = 0
        prev = rect
        page.wait_for_timeout(800)
    raise RuntimeError(f"range {rng}: selection never settled "
                       f"(timeout {timeout_s}s, at {page.url[:80]})")


_INK_LUMA = 96      # pixels darker than this count as "ink" (cell text)
_MIN_INK_PX = 200   # a shot with less ink than this has no text painted


def _ink_pixels(png: bytes) -> int:
    import io

    from PIL import Image
    return sum(Image.open(io.BytesIO(png)).convert("L")
               .histogram()[:_INK_LUMA])


def _shoot_when_painted(page, rng: str, *, settle_ms: int,
                        timeout_s: int) -> bytes:
    """Screenshot the selection clip once consecutive frames stop changing.
    The canvas keeps painting (backgrounds first, then text once the row
    data arrives) for seconds AFTER the selection rect is stable — only
    frame-comparison catches that."""
    page.wait_for_timeout(settle_ms)
    deadline = time.time() + timeout_s
    prev, same = None, 0
    while True:
        rect = _selection_rect(page)
        if rect is None:
            raise RuntimeError(f"range {rng}: selection overlay vanished")
        cur = page.screenshot(clip=rect)
        if prev is not None and cur == prev:
            same += 1
            if same >= 2:          # 3 identical frames ≈ 2.4s of no painting
                return cur
        else:
            same = 0
        if time.time() > deadline:
            return cur             # best effort — ink gate below still guards
        prev = cur
        page.wait_for_timeout(1200)


def _capture_on_page(page, rng: str, out_path: Path, *,
                     settle_ms: int, timeout_s: int) -> Path:
    png = None
    for attempt in (1, 2):
        rect = _goto_range(page, rng, timeout_s)
        # Grow the viewport so the WHOLE range is on screen (rect.x/y is
        # the grid origin below the toolbar + headers), then re-navigate
        # so the editor re-anchors the range and repaints at full size.
        need_w = math.ceil(rect["x"] + rect["width"]) + _VIEWPORT_PAD
        need_h = math.ceil(rect["y"] + rect["height"]) + _VIEWPORT_PAD
        if need_w > _MAX_VIEWPORT[0] or need_h > _MAX_VIEWPORT[1]:
            raise RuntimeError(
                f"range {rng} needs a {need_w}x{need_h} viewport, over the "
                f"{_MAX_VIEWPORT} cap — split the range or raise the cap.")
        vp = page.viewport_size or _DEFAULT_VIEWPORT
        if need_w > vp["width"] or need_h > vp["height"]:
            page.set_viewport_size({"width": max(vp["width"], need_w),
                                    "height": max(vp["height"], need_h)})
            _goto_range(page, rng, timeout_s)
        page.add_style_tag(content=_HIDE_OVERLAYS_CSS)
        png = _shoot_when_painted(page, rng, settle_ms=settle_ms,
                                  timeout_s=timeout_s)
        if _ink_pixels(png) >= _MIN_INK_PX:
            break                  # text actually painted — good shot
        # Backgrounds painted but no text (row data never arrived) —
        # a fresh navigation re-requests it; retry once.
    else:
        raise RuntimeError(f"range {rng}: cells never painted text "
                           f"(2 attempts) — sheet slow or range empty?")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(png)
    return out_path


def capture_ranges(items: Iterable[Tuple[str, Path]], *, scale: float = 2.0,
                   settle_ms: int = 2500, timeout_s: int = 60) -> list[Path]:
    """Screenshot each (range, out_path) of the Sales Board tab in one
    browser session. Returns the written paths."""
    done: list[Path] = []
    with sync_playwright() as p:
        ctx = _launch(p, headless=True, viewport=dict(_DEFAULT_VIEWPORT),
                      device_scale_factor=scale)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            for rng, path in items:
                done.append(_capture_on_page(
                    page, rng, Path(path),
                    settle_ms=settle_ms, timeout_s=timeout_s))
        finally:
            ctx.close()
    return done


def capture_range(rng: str, out_path: Path, **kw) -> Path:
    return capture_ranges([(rng, out_path)], **kw)[0]


def _hstack(paths: list[Path], out_path: Path) -> Path:
    """Join PNGs side by side (used to splice the Units name+total strip
    onto the chosen day's 3-col strip, skipping the days in between)."""
    from PIL import Image
    ims = [Image.open(p).convert("RGB") for p in paths]
    canvas = Image.new("RGB", (sum(i.width for i in ims),
                               max(i.height for i in ims)), "white")
    x = 0
    for im in ims:
        canvas.paste(im, (x, 0))
        x += im.width
    canvas.save(out_path)
    return out_path


def captain_shots(captain_key: str, out_dir: Path, *,
                  scale: float = 2.0) -> dict:
    """Product Summary + Captainship Units PNGs for one captain.

    Product Summary: the whole block through the last weekly-historical
    column (ps_range scans for it — never hardcoded).
    Units: names+'Total for week' (B:E) spliced next to the most recent
    day group with data — the in-between days are not shown.

    Returns {'product_summary': Path, 'units': Path, 'units_day': str}."""
    u_s, u_e = UNITS_ROWS[captain_key]
    day_name, d_first, d_last = units_day_columns(captain_key)
    out_dir = Path(out_dir)
    ps_path = out_dir / f"captainship_{captain_key}_product_summary.png"
    u_path = out_dir / f"captainship_{captain_key}_units.png"
    u_left = out_dir / f"_{captain_key}_units_left.tmp.png"
    u_day = out_dir / f"_{captain_key}_units_day.tmp.png"
    try:
        capture_ranges([(ps_range(captain_key), ps_path),
                        (f"B{u_s}:E{u_e}", u_left),
                        (f"{d_first}{u_s}:{d_last}{u_e}", u_day)],
                       scale=scale)
        _hstack([u_left, u_day], u_path)
    finally:
        for tmp in (u_left, u_day):
            tmp.unlink(missing_ok=True)
    return {"product_summary": ps_path, "units": u_path,
            "units_day": day_name}


if __name__ == "__main__":
    # Windows consoles default to cp1252, which can't print '✓'.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "login"
    if cmd == "check":
        sys.exit(0 if check() else 1)
    elif cmd == "shot":
        # python -m ...sheet_shot shot <captain> [out_dir]   (default output/)
        key = sys.argv[2]
        out_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("output")
        shots = captain_shots(key, out_dir)
        day = shots.pop("units_day")
        for label, path in shots.items():
            print(f"✓ {label}: {path}" + (f" (day: {day})"
                                          if label == "units" else ""))
    else:
        sys.exit(0 if login() else 1)
