"""Real Google Sheets screenshots for the Captainship drafts.

The Product Summary + Captainship Units sections are captured as actual
browser screenshots of the 'Alphalete ORG Sales Board' sheet (so they
look EXACTLY like the sheet on screen), driven by patchright.

How capture works: the URL `#gid=<gid>&range=<rng>` fragment makes the
editor scroll to AND select the range. The grid itself is a canvas, but
the selection is drawn as DOM overlay divs (.selection + .range-border)
positioned exactly over the range — so we read the selection div's
bounding rect for a pixel-exact crop, hide the overlays via injected CSS
(no blue tint / border / autofill nub in the image), wait for the canvas
to actually finish painting (frame comparison + an "ink" gate, because
backgrounds paint before text), and screenshot with clip=rect.

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

import datetime as dt

from automations.captainship_drafts.sales_board import (
    PS_END_COL, SALES_BOARD_ID, _open_ws, _values,
    discover_blocks, prior_day_columns, ps_shot_view,
)

SHEETS_PROFILE_DIR = (
    Path.home() / ".config" / "recruiting-report" / "sheets-browser-profile"
)
LOGIN_ACCOUNT = "alphaletereporting@gmail.com"
_SHEET_EDIT_URL = f"https://docs.google.com/spreadsheets/d/{SALES_BOARD_ID}/edit"

_HIDE_OVERLAYS_CSS = (
    ".selection, .range-border, .autofill-cover, .autofill-handle,"
    " .touch-selection-handle { visibility: hidden !important; }"
    # The sheet-tab bar (#grid-bottom-bar — tabs, the all-sheets menu, scroll
    # arrows) is pinned to the viewport bottom and floats OVER the grid; on a
    # tall range (e.g. Product Summary) it occludes the last rows. The grid
    # paints behind it, so hiding the whole bar reveals them.
    " #grid-bottom-bar { visibility: hidden !important; }")
# The frozen column-header strip (A B C …) is painted on the same canvas as the
# cells, so it can't be hidden with CSS — instead _selection_rect clamps the clip
# top below it. This selector reads its extent.
_COL_HEADER_SEL = ".column-headers-background"

_DEFAULT_VIEWPORT = {"width": 1600, "height": 1100}
_VIEWPORT_PAD = 80               # room for scrollbars beyond the range
_MAX_VIEWPORT = (4400, 12000)    # sanity cap on auto-grown viewport


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
    """Viewport rect of the current selection overlay, or None if absent. The top
    is clamped to the bottom of the frozen column-header strip: for a range
    anchored high on the sheet (e.g. Rafael's PS at row 208) the overlay starts
    ABOVE the header, so an unclamped clip captures the A B C column letters. The
    real cell content begins at the header bottom, so clamping loses no data."""
    return page.evaluate("""(sel) => {
        let hb = 0;
        const h = document.querySelector(sel);
        if (h) hb = h.getBoundingClientRect().bottom;
        for (const el of document.querySelectorAll('.selection')) {
            const b = el.getBoundingClientRect();
            if (b.width > 1 && b.height > 1) {
                const top = Math.max(b.y, hb);
                return {x: b.x, y: top, width: b.width,
                        height: b.height - (top - b.y)};
            }
        }
        return null;
    }""", _COL_HEADER_SEL)


def _goto_range(page, rng: str, timeout_s: int,
                edit_url: str | None = None, gid: int | None = None) -> dict:
    """Navigate to the sheet with `rng` selected; return the selection rect
    once it has STOPPED MOVING. The editor keeps shifting layout for a few
    seconds after load (row-header strip widens for 4-digit rows, toolbar
    chrome finishes, the grid re-anchors after tiles paint) — a rect read
    too early drifts off the range by the time the screenshot is taken.

    `edit_url`/`gid` override the target sheet/tab (default: the captainship
    drafts' Sales Board). Lets other reports screenshot a different workbook."""
    _url = edit_url or _SHEET_EDIT_URL
    _g = _gid() if gid is None else gid
    page.goto(f"{_url}#gid={_g}&range={rng}",
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


def _png_height(png: bytes) -> int:
    import io

    from PIL import Image
    return Image.open(io.BytesIO(png)).height


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
                     settle_ms: int, timeout_s: int,
                     edit_url: str | None = None, gid: int | None = None) -> Path:
    png = None
    for attempt in (1, 2):
        rect = _goto_range(page, rng, timeout_s, edit_url, gid)
        # Grow the viewport so the WHOLE range is on screen (rect.x/y is the
        # grid origin below the toolbar + headers), re-navigating so the editor
        # re-anchors and repaints at full size. The selection overlay is CLIPPED
        # to the current viewport, so growing once off a clipped first measure
        # can still fall short on a tall range (the rect reads taller only after
        # the viewport can show more). Re-measure and re-grow until the whole
        # rect fits — else the bottom rows (e.g. PS last weeks) get cut off.
        for _ in range(6):
            need_w = math.ceil(rect["x"] + rect["width"]) + _VIEWPORT_PAD
            need_h = math.ceil(rect["y"] + rect["height"]) + _VIEWPORT_PAD
            if need_w > _MAX_VIEWPORT[0] or need_h > _MAX_VIEWPORT[1]:
                raise RuntimeError(
                    f"range {rng} needs a {need_w}x{need_h} viewport, over the "
                    f"{_MAX_VIEWPORT} cap — split the range or raise the cap.")
            vp = page.viewport_size or _DEFAULT_VIEWPORT
            if need_w <= vp["width"] and need_h <= vp["height"]:
                break              # entire range already on screen
            page.set_viewport_size({"width": max(vp["width"], need_w),
                                    "height": max(vp["height"], need_h)})
            rect = _goto_range(page, rng, timeout_s, edit_url, gid)
        grown_h = rect["height"]        # settled full-range height (all rows)
        page.add_style_tag(content=_HIDE_OVERLAYS_CSS)
        png = _shoot_when_painted(page, rng, settle_ms=settle_ms,
                                  timeout_s=timeout_s)
        has_ink = _ink_pixels(png) >= _MIN_INK_PX
        # Guard against a vertically-clipped shot. On a very tall range Sheets can
        # paint only part of it before _shoot returns, so the selection overlay
        # collapses to the painted region and the shot cuts the last rows (e.g.
        # Rafael's PS 4th week). Compare the shot height to the GROWN rect height
        # (× devicePixelRatio) — not the possibly-collapsed one — and retry.
        dpr = page.evaluate("() => window.devicePixelRatio") or 1
        tall_enough = _png_height(png) >= math.floor(grown_h * dpr * 0.97)
        if has_ink and tall_enough:
            break                  # text painted AND full height — good shot
        if has_ink and attempt == 2:
            break                  # best effort: text present, accept if short
        # Text missing (row data never arrived) or shot clipped short —
        # a fresh navigation re-requests + repaints at full size; retry once.
    else:
        raise RuntimeError(f"range {rng}: cells never painted text "
                           f"(2 attempts) — sheet slow or range empty?")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(png)
    return out_path


def capture_ranges(items: Iterable[Tuple[str, Path]], *, scale: float = 2.0,
                   settle_ms: int = 2500, timeout_s: int = 60,
                   edit_url: str | None = None, gid: int | None = None) -> list[Path]:
    """Screenshot each (range, out_path) of the Sales Board tab in one
    browser session. Returns the written paths. `edit_url`/`gid` target a
    different workbook/tab (default: the captainship drafts' Sales Board)."""
    done: list[Path] = []
    with sync_playwright() as p:
        ctx = _launch(p, headless=True, viewport=dict(_DEFAULT_VIEWPORT),
                      device_scale_factor=scale)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            for rng, path in items:
                done.append(_capture_on_page(
                    page, rng, Path(path),
                    settle_ms=settle_ms, timeout_s=timeout_s,
                    edit_url=edit_url, gid=gid))
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


def _units_label(raw: str) -> str:
    """Pretty caption for a units block from its sheet sub-header."""
    r = (raw or "").strip().upper()
    if "NEW INTERNET" in r:
        return "New Internet Units"
    if "ALL UNITS" in r or r in ("", "UNITS"):
        return "All Units"
    return raw.title()


def _units_blocks_for(captain_key: str, flavor: str, blocks) -> list:
    """Which discovered units charts go in this captain's email.
    Rafael: New Internet only (spec = one chart). Fiber: both (New Internet +
    All Units). B2B/NDS: their single block."""
    units = blocks.units
    if flavor == "rafael":
        ni = [u for u in units if "NEW INTERNET" in u.label.upper()]
        return ni or units[:1]
    return units


def captain_shots(captain_key: str, flavor: str, out_dir: Path, *,
                  today: dt.date | None = None, scale: float = 2.0) -> dict:
    """Product Summary + Captainship Units PNGs for one captain, all ranges
    found BY LABEL on the 'Copy of' Sales Board tab.

    Product Summary: the A:K span (New-Internet + All-Units sub-blocks for
    fiber/Rafael) with its collapsed weekly-historical row groups EXPANDED
    for the shot (shared view state — expanded only during this capture).
    Units: for each chart, the names+'Total for week' strip (B:E) spliced
    next to the PRIOR DAY's 3-col group; the in-between days are hidden.

    Returns {'product_summary': Path, 'units': [(caption, Path), ...]}."""
    today = today or dt.date.today()
    blocks = discover_blocks()[captain_key]
    vals = _values()
    out_dir = Path(out_dir)
    ps_path = out_dir / f"captainship_{captain_key}_product_summary.png"

    # PS alone inside the shot-view window (groups expanded + old weeks hidden),
    # so the shared sheet spends the least possible time in that state. The CM
    # yields the row to end the capture on (last kept week of the last block).
    # The PS is a TALL range; Sheets needs a longer paint-settle before the whole
    # thing is on the canvas (a short settle cuts the bottom weeks — proven: at
    # 2.5s it clipped intermittently, at 8s it was full every time). timeout_s is
    # raised to match so the frame-settle loop isn't starved.
    with ps_shot_view(blocks.ps_start, blocks.ps_end, keep_weeks=4) as ps_end_row:
        capture_ranges(
            [(f"A{blocks.ps_start}:{PS_END_COL}{ps_end_row}", ps_path)],
            scale=scale, settle_ms=8000, timeout_s=90)

    units_out: list = []
    for i, ub in enumerate(_units_blocks_for(captain_key, flavor, blocks)):
        day_name, d_first, d_last = prior_day_columns(ub, today, vals)
        u_path = out_dir / f"captainship_{captain_key}_units{i}.png"
        u_left = out_dir / f"_{captain_key}_units{i}_left.tmp.png"
        u_day = out_dir / f"_{captain_key}_units{i}_day.tmp.png"
        try:
            capture_ranges(
                [(f"B{ub.start_row}:E{ub.end_row}", u_left),
                 (f"{d_first}{ub.start_row}:{d_last}{ub.end_row}", u_day)],
                scale=scale)
            _hstack([u_left, u_day], u_path)
        finally:
            for tmp in (u_left, u_day):
                tmp.unlink(missing_ok=True)
        units_out.append((f"{_units_label(ub.label)} — {day_name}", u_path))
    return {"product_summary": ps_path, "units": units_out}


if __name__ == "__main__":
    # Windows consoles default to cp1252, which can't print '✓'.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "login"
    if cmd == "check":
        sys.exit(0 if check() else 1)
    elif cmd == "shot":
        # python -m ...sheet_shot shot <captain> [out_dir]   (default output/)
        from automations.captainship_drafts.config import BY_KEY
        key = sys.argv[2]
        out_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("output")
        shots = captain_shots(key, BY_KEY[key].flavor, out_dir)
        print(f"✓ product_summary: {shots['product_summary']}")
        for caption, path in shots["units"]:
            print(f"✓ units [{caption}]: {path}")
    else:
        sys.exit(0 if login() else 1)
