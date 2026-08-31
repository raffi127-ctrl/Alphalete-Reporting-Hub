"""Render Sales Board ranges to PNG WITHOUT a Google browser login.

The captainship drafts' Product Summary + Units images used to be literal
screenshots of the Sales Board, taken through a Chrome profile signed into
Google (sheet_shot.py). Google expires that browser session every few weeks and
the re-login needs 2FA *physically at the machine that runs the report* — a
standing manual chore (Eve pinged Megan for it 2026-07-29).

This module removes that dependency. It reads the same cells WITH their
formatting through the API token (the auto-refreshing OAuth token in
recruiting_report.fill._client — the one that never logs out, which is why the
DATA side of every report never breaks), builds an HTML table that mirrors the
sheet, and screenshots that LOCAL html with a headless browser. No Google login
is ever in the loop, so there is nothing to expire and nobody has to sit at
Lucy 1 again.

Public API mirrors sheet_shot so run.py can swap paths with no other change:

    captain_shots(captain_key, flavor, out_dir) -> {
        'product_summary': Path, 'units': [(caption, Path), ...]}
"""
from __future__ import annotations

import atexit
import datetime as dt
import html as _html
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from patchright.sync_api import sync_playwright

from automations.captainship_drafts.sales_board import (
    PS_END_COL, SALES_BOARD_ID, SALES_BOARD_TAB, _open_ws, _values,
    block_anchors, discover_blocks, moved_anchors, ps_shot_plan,
    prior_day_columns, refresh_blocks,
)

# Font families that browsers already have — everything else is pulled from
# Google Fonts so the render matches the sheet (the Sales Board uses display
# faces like "Alfa Slab One" for the team headers).
_WEBSAFE = {
    "arial", "helvetica", "times new roman", "times", "georgia", "verdana",
    "courier new", "courier", "trebuchet ms", "tahoma", "garamond", "roboto",
    "", None,
}


def _col_to_index(letter: str) -> int:
    """'A' -> 0, 'L' -> 11, 'AA' -> 26."""
    n = 0
    for ch in letter.strip().upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _index_to_col(idx: int) -> str:
    """0 -> 'A', 11 -> 'L'."""
    s = ""
    idx += 1
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def _retrying(call, *, tries: int = 4, base: float = 5.0):
    """Run `call`, retrying a RATE-LIMIT / transient server error with backoff.

    Only 429 and 5xx are retried — a 403 or a bad range is a real error and
    must surface immediately instead of costing 30s of sleeping first. This
    exists because the failure it absorbs is invisible in the output: a 429
    mid-build made §1 render a 'pending' note, so a report went out looking
    complete-but-empty rather than failing loudly."""
    import time
    for attempt in range(tries):
        try:
            return call()
        except Exception as e:      # noqa: BLE001 — classified by message below
            msg = str(e)
            transient = ("429" in msg or "RESOURCE_EXHAUSTED" in msg
                         or "Quota exceeded" in msg or "500" in msg
                         or "503" in msg or "Internal error" in msg)
            if not transient or attempt == tries - 1:
                raise
            time.sleep(base * (2 ** attempt))       # 5s, 10s, 20s


def _fetch_grid(col_start: str, col_end: str, row_start: int,
                row_end: int) -> dict:
    """Grid data (values + effectiveFormat + merges + col widths + row heights)
    for the A1 window, read through the API token. 1-based inclusive rows."""
    ws = _open_ws()
    a1 = f"'{ws.title}'!{col_start}{row_start}:{col_end}{row_end}"
    meta = _retrying(lambda: ws.spreadsheet.fetch_sheet_metadata(
        {"includeGridData": "true", "ranges": a1}))
    sheet = meta["sheets"][0]
    data = sheet["data"][0]
    return {
        "start_row": data.get("startRow", row_start - 1),   # 0-based
        "start_col": data.get("startColumn", 0) or 0,       # 0-based (abs)
        "rows": data.get("rowData", []),
        "row_meta": data.get("rowMetadata", []),
        "col_meta": data.get("columnMetadata", []),
        "merges": sheet.get("merges", []),
    }


def _rgb(c: Optional[dict], default: str = "") -> str:
    """A Sheets color dict -> CSS 'rgb(r,g,b)'. Missing channel = 0 (that is how
    Sheets stores pure black / pure red — the absent keys are zeros, not ones).

    `c is None` means the cell carries no such color and the caller's default
    applies. An EMPTY DICT is not that: proto3 omits zero-valued fields, so
    pure black serializes as {} and `not c` would throw it away — see
    _is_white."""
    if c is None:
        return default
    r = round(c.get("red", 0) * 255)
    g = round(c.get("green", 0) * 255)
    b = round(c.get("blue", 0) * 255)
    return f"rgb({r},{g},{b})"


def _is_white(c: Optional[dict]) -> bool:
    """Whether this fill can be left unpainted.

    `{}` is PURE BLACK, not absent — the API omits zero-valued channels, and a
    genuinely unstyled cell comes back with explicit 1s instead. Treating the
    empty dict as falsy dropped the black fill off 114 cells of Rafael's
    Product Summary alone: the TOTALS row turned white-on-white (its numbers
    vanished) and the black-masked K/L helper cells published prior-week totals
    the sheet deliberately hides."""
    if c is None:
        return True
    return (c.get("red", 0) >= 0.999 and c.get("green", 0) >= 0.999
            and c.get("blue", 0) >= 0.999)


_ALIGN = {"LEFT": "left", "CENTER": "center", "RIGHT": "right"}
_VALIGN = {"TOP": "top", "MIDDLE": "middle", "BOTTOM": "bottom"}


def _cell_style(fmt: dict, fonts: set) -> str:
    """Inline CSS for one cell from its effectiveFormat."""
    css: List[str] = []
    bg = fmt.get("backgroundColor")
    if not _is_white(bg):
        css.append(f"background:{_rgb(bg)}")
    tf = fmt.get("textFormat", {})
    fam = (tf.get("fontFamily") or "").strip()
    if fam:
        if fam.lower() not in _WEBSAFE:
            fonts.add(fam)
        css.append(f"font-family:'{fam}',sans-serif")
    if tf.get("fontSize"):
        css.append(f"font-size:{tf['fontSize']}pt")
    if tf.get("bold"):
        css.append("font-weight:700")
    if tf.get("italic"):
        css.append("font-style:italic")
    deco = []
    if tf.get("underline"):
        deco.append("underline")
    if tf.get("strikethrough"):
        deco.append("line-through")
    if deco:
        css.append(f"text-decoration:{' '.join(deco)}")
    fg = tf.get("foregroundColor")
    if fg:
        css.append(f"color:{_rgb(fg, 'rgb(0,0,0)')}")
    ha = _ALIGN.get(fmt.get("horizontalAlignment", ""))
    if ha:
        css.append(f"text-align:{ha}")
    va = _VALIGN.get(fmt.get("verticalAlignment", ""))
    if va:
        css.append(f"vertical-align:{va}")
    wrap = fmt.get("wrapStrategy", "OVERFLOW_CELL")
    css.append("white-space:normal;word-break:break-word"
               if wrap == "WRAP" else "white-space:nowrap")
    pad = fmt.get("padding") or {}
    css.append("padding:{}px {}px {}px {}px".format(
        pad.get("top", 2), pad.get("right", 3),
        pad.get("bottom", 2), pad.get("left", 3)))
    # Explicit cell borders override the default light gridline.
    for side in ("top", "right", "bottom", "left"):
        b = (fmt.get("borders") or {}).get(side)
        if b and b.get("style") not in (None, "NONE"):
            w = max(1, round(b.get("width", 1)))
            col = _rgb(b.get("color"), "rgb(0,0,0)")
            css.append(f"border-{side}:{w}px solid {col}")
    return ";".join(css)


def _covered_cells(merges: List[dict], start_row: int,
                   start_col: int) -> Dict[Tuple[int, int], dict]:
    """Map (local_row, local_col) -> merge span for the top-left anchor, and
    mark the other covered cells as skipped. Indices are LOCAL to the window."""
    info: Dict[Tuple[int, int], dict] = {}
    for m in merges:
        r0 = m["startRowIndex"] - start_row
        r1 = m["endRowIndex"] - start_row
        c0 = m["startColumnIndex"] - start_col
        c1 = m["endColumnIndex"] - start_col
        if r0 < 0 or c0 < 0:
            continue
        for rr in range(r0, r1):
            for cc in range(c0, c1):
                if rr == r0 and cc == c0:
                    info[(rr, cc)] = {"rowspan": r1 - r0, "colspan": c1 - c0}
                else:
                    info[(rr, cc)] = {"skip": True}
    return info


def _build_html(grid: dict, ncols: int, *,
                skip_rows_0based: Optional[set] = None) -> str:
    """HTML <table> mirroring the grid. `skip_rows_0based` are absolute 0-based
    sheet rows to omit (the collapsed older weeks in a Product Summary)."""
    fonts: set = set()
    skip_rows_0based = skip_rows_0based or set()
    start_row = grid["start_row"]
    start_col = grid["start_col"]
    merges = _covered_cells(grid["merges"], start_row, start_col)

    # Column widths (rendered = stored pixelSize + 1 gridline, per sales_board).
    widths = [(c.get("pixelSize", 100) + 1) for c in grid["col_meta"][:ncols]]
    while len(widths) < ncols:
        widths.append(101)
    colgroup = "".join(f'<col style="width:{w}px">' for w in widths)

    body: List[str] = []
    for ri, row in enumerate(grid["rows"]):
        abs_row = start_row + ri
        if abs_row in skip_rows_0based:
            continue
        h = grid["row_meta"][ri].get("pixelSize", 21) if ri < len(
            grid["row_meta"]) else 21
        cells: List[str] = []
        values = row.get("values", [])
        for ci in range(ncols):
            span = merges.get((ri, ci))
            if span and span.get("skip"):
                continue
            cell = values[ci] if ci < len(values) else {}
            fmt = cell.get("effectiveFormat", {})
            val = _html.escape(cell.get("formattedValue", "") or "").replace(
                "\n", "<br>")
            attrs = ""
            if span:
                if span.get("rowspan", 1) > 1:
                    attrs += f' rowspan="{span["rowspan"]}"'
                if span.get("colspan", 1) > 1:
                    attrs += f' colspan="{span["colspan"]}"'
            cells.append(
                f'<td{attrs} style="{_cell_style(fmt, fonts)}">{val}</td>')
        body.append(f'<tr style="height:{h}px">' + "".join(cells) + "</tr>")

    font_link = ""
    if fonts:
        fam = "&".join(
            "family=" + f.replace(" ", "+") for f in sorted(fonts))
        font_link = (f'<link rel="stylesheet" '
                     f'href="https://fonts.googleapis.com/css2?{fam}'
                     f'&display=swap">')
    return f"""<!doctype html><html><head><meta charset="utf-8">{font_link}
<style>
 * {{ box-sizing:border-box; }}
 body {{ margin:0; padding:0; background:#fff; }}
 table {{ border-collapse:collapse; table-layout:fixed;
          font-family:Arial,sans-serif; font-size:10pt; color:#000; }}
 td {{ border:1px solid #d9d9d9; overflow:hidden; }}
</style></head><body>
<table id="grid"><colgroup>{colgroup}</colgroup><tbody>{''.join(body)}
</tbody></table></body></html>"""


# ONE browser for the whole run, not one per image. A full build renders ~36 of
# these (12 captains x Product Summary + 2 unit charts), and launching Chrome
# per image is what pushed the first unattended run on the mini past its 45-min
# timeout. The browser is opened on first use and closed at exit; a context is
# per scale because device_scale_factor is fixed at creation.
_RENDER: dict = {}          # scale -> (playwright, browser, context)


def _render_ctx(scale: float):
    got = _RENDER.get(scale)
    if got is not None:
        return got[2]
    p = sync_playwright().start()
    try:
        browser = p.chromium.launch(channel="chrome", headless=True)
    except Exception:       # noqa: BLE001 — no system Chrome: use the bundled one
        browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(device_scale_factor=scale,
                              viewport={"width": 2400, "height": 2000})
    _RENDER[scale] = (p, browser, ctx)
    return ctx


def close_renderer() -> None:
    """Shut the shared browser down. Registered atexit, so callers never have to
    remember — but exposed for a long-lived process that wants the memory back."""
    for p, browser, ctx in list(_RENDER.values()):
        for close in (ctx.close, browser.close, p.stop):
            try:
                close()
            except Exception:   # noqa: BLE001 — teardown must not raise
                pass
    _RENDER.clear()


atexit.register(close_renderer)


def _render_html_to_png(html: str, out_path: Path, *, scale: float = 2.0,
                        fonts_present: bool = False) -> Path:
    """Screenshot the #grid table of `html` to `out_path` at `scale`x. Pure
    local render — no navigation to Google, no login, nothing to expire."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return _screenshot(html, out_path, scale, fonts_present)
    except Exception:       # noqa: BLE001 — see below
        # The browser is SHARED across all 12 captains, so if it dies (the mini
        # is small and these pages are large) every later captain inherits a
        # dead handle and loses §1 — the first captains look perfect and the
        # rest are blank, with nothing in the report saying why. Drop the
        # corpse and rebuild once; a second failure is a real error and raises.
        close_renderer()
        return _screenshot(html, out_path, scale, fonts_present)


def _screenshot(html: str, out_path: Path, scale: float,
                fonts_present: bool) -> Path:
    page = _render_ctx(scale).new_page()
    try:
        # 'load', not 'networkidle': the only network here is the Google Fonts
        # stylesheet, and networkidle waits out its own 500ms quiet period on
        # every single render — 30s of it when the font CDN is slow, which is
        # dead time multiplied by ~36. The font wait below is the part that
        # actually matters, and it is bounded.
        page.set_content(html, wait_until="load")
        if fonts_present:
            try:
                page.wait_for_function("document.fonts.status === 'loaded'",
                                       timeout=4000)
            except Exception:   # noqa: BLE001 — a stalled CDN falls back to a
                page.wait_for_timeout(600)      # web-safe face, never to a hang
        page.locator("#grid").screenshot(path=str(out_path))
    finally:
        try:
            page.close()
        except Exception:   # noqa: BLE001 — a dead browser must not mask the
            pass            # real error the caller is about to retry on
    return out_path


# --------------------------------------------------------------------------
# Public API — mirrors sheet_shot.captain_shots
# --------------------------------------------------------------------------
def _units_label(raw: str) -> str:
    r = (raw or "").strip().upper()
    if "NEW INTERNET" in r:
        return "New Internet Units"
    if "ALL UNITS" in r or r in ("", "UNITS"):
        return "All Units"
    return raw.title()


def captain_shots(captain_key: str, flavor: str, out_dir: Path, *,
                  today: Optional[dt.date] = None, scale: float = 2.0,
                  logfn=print) -> dict:
    """Product Summary + Units PNGs for one captain, rendered from API data
    (no Google login). Same return shape as sheet_shot.captain_shots.

    Re-locates the blocks first and checks afterwards that they did not move
    while rendering — see sales_board.refresh_blocks for the image that got
    Khalil captured two rows low. A move gets ONE retry; a board being written
    that fast twice in a row is not something to paper over with a picture, so
    the second one raises and run.py degrades the section with the reason."""
    today = today or dt.date.today()
    for attempt in (1, 2):
        blocks, vals = _locate(captain_key)
        expected = block_anchors(vals, blocks)
        out = _render_blocks(captain_key, blocks, vals, Path(out_dir),
                             today=today, scale=scale)
        moved = moved_anchors(expected)
        if not moved:
            return out
        logfn(f"  ⚠ the Sales Board moved under {captain_key}'s render "
              f"({'; '.join(moved)})"
              + (" — rendering it again" if attempt == 1 else ""))
    raise RuntimeError(
        f"the Sales Board kept moving under {captain_key}'s render "
        f"(twice): {'; '.join(moved)}")


def _locate(captain_key: str):
    """(blocks, values) for one captain, re-read from the live sheet."""
    all_blocks = refresh_blocks()
    if captain_key not in all_blocks:
        raise RuntimeError(
            f"no Product Summary block found for {captain_key!r} on "
            f"'{SALES_BOARD_TAB}' — team header missing/renamed. "
            f"Found: {sorted(all_blocks)}")
    return all_blocks[captain_key], _values()


def _render_blocks(captain_key: str, blocks, vals, out_dir: Path, *,
                   today: dt.date, scale: float) -> dict:
    """One pass of the actual rendering, against blocks already located."""
    # --- Product Summary: last 4 weeks, older weeks collapsed out -----------
    hide_ranges, end_row = ps_shot_plan(blocks.ps_start, blocks.ps_end)
    skip: set = set()
    for s, e in hide_ranges:          # 0-based half-open -> absolute rows
        skip.update(range(s, e))
    ncols = _col_to_index(PS_END_COL) + 1
    grid = _fetch_grid("A", PS_END_COL, blocks.ps_start, end_row)
    html = _build_html(grid, ncols, skip_rows_0based=skip)
    ps_path = out_dir / f"captainship_{captain_key}_product_summary.png"
    _render_html_to_png(html, ps_path, scale=scale,
                        fonts_present="fonts.googleapis" in html)

    # --- Units: names+total strip (A:E) spliced onto the prior day's group --
    units_out: List = []
    for i, ub in enumerate(blocks.units):
        day_name, d_first, d_last = prior_day_columns(ub, today, vals)
        # One table: cols A..E, then the prior-day's 3-col group. The columns
        # between them (the other days) are simply not fetched.
        #
        # Starts at A, not B (Eve, 2026-08-25: "no se ven los titulos de los
        # cuadros ... para ningun delta chart"). The block's two title rows
        # live in col A — "Raf Captainship" and "NEW INTERNET UNITS" / "ALL
        # UNITS" — so a B:E window cut them off and every chart arrived with a
        # blank top-left corner. Col A also carries the rank numbers and the
        # totals row's label, which is the sheet's own layout.
        left = _fetch_grid("A", "E", ub.start_row, ub.end_row)
        day = _fetch_grid(d_first, d_last, ub.start_row, ub.end_row)
        u_path = out_dir / f"captainship_{captain_key}_units{i}.png"
        html = _spliced_units_html(left, day)
        _render_html_to_png(html, u_path, scale=scale,
                            fonts_present="fonts.googleapis" in html)
        units_out.append((f"{_units_label(ub.label)} — {day_name}", u_path))
    return {"product_summary": ps_path, "units": units_out}


def _spliced_units_html(left: dict, day: dict) -> str:
    """Build one table from two column windows (B:E and the day's 3 cols),
    row-aligned, skipping the days in between — the render equivalent of the
    old _hstack of two separate screenshots."""
    n_left = 5                                   # A,B,C,D,E
    n_day = len(day["col_meta"]) or 3
    fonts: set = set()

    # SPILL. Col A is a narrow rank column, but its title rows hold long text
    # ("NEW INTERNET UNITS"): on the sheet that text simply flows over the
    # empty B beside it. This table is table-layout:fixed with overflow:hidden,
    # so without help the title would be CLIPPED to the rank column's width —
    # a blank corner again, by a different route. Reproduce the spill: an A
    # cell with text whose B neighbour is empty spans both columns.
    def _spills(ri: int) -> bool:
        vals_ = (left["rows"][ri].get("values", [])
                 if ri < len(left["rows"]) else [])
        a_txt = (vals_[0].get("formattedValue") or "").strip() if vals_ else ""
        b_txt = ((vals_[1].get("formattedValue") or "").strip()
                 if len(vals_) > 1 else "")
        return bool(a_txt) and not b_txt

    def widths(g, n):
        w = [(c.get("pixelSize", 100) + 1) for c in g["col_meta"][:n]]
        while len(w) < n:
            w.append(101)
        return w

    cols = widths(left, n_left) + widths(day, n_day)
    colgroup = "".join(f'<col style="width:{w}px">' for w in cols)

    lmerge = _covered_cells(left["merges"], left["start_row"],
                            left["start_col"])
    dmerge = _covered_cells(day["merges"], day["start_row"], day["start_col"])
    nrows = max(len(left["rows"]), len(day["rows"]))
    body: List[str] = []
    for ri in range(nrows):
        h = (left["row_meta"][ri].get("pixelSize", 21)
             if ri < len(left["row_meta"]) else 21)
        cells: List[str] = []
        for (g, n, mg) in ((left, n_left, lmerge), (day, n_day, dmerge)):
            values = g["rows"][ri].get("values", []) if ri < len(
                g["rows"]) else []
            spill = g is left and _spills(ri)
            for ci in range(n):
                span = mg.get((ri, ci))
                if span and span.get("skip"):
                    continue
                if spill and ci == 1:      # covered by A's colspan
                    continue
                cell = values[ci] if ci < len(values) else {}
                fmt = cell.get("effectiveFormat", {})
                val = _html.escape(
                    cell.get("formattedValue", "") or "").replace("\n", "<br>")
                attrs = ' colspan="2"' if (spill and ci == 0) else ""
                if span:
                    if span.get("rowspan", 1) > 1:
                        attrs += f' rowspan="{span["rowspan"]}"'
                    if span.get("colspan", 1) > 1:
                        attrs += f' colspan="{span["colspan"]}"'
                cells.append(
                    f'<td{attrs} style="{_cell_style(fmt, fonts)}">{val}</td>')
        body.append(f'<tr style="height:{h}px">' + "".join(cells) + "</tr>")

    font_link = ""
    if fonts:
        fam = "&".join("family=" + f.replace(" ", "+") for f in sorted(fonts))
        font_link = (f'<link rel="stylesheet" '
                     f'href="https://fonts.googleapis.com/css2?{fam}'
                     f'&display=swap">')
    return f"""<!doctype html><html><head><meta charset="utf-8">{font_link}
<style>
 * {{ box-sizing:border-box; }}
 body {{ margin:0; padding:0; background:#fff; }}
 table {{ border-collapse:collapse; table-layout:fixed;
          font-family:Arial,sans-serif; font-size:10pt; color:#000; }}
 td {{ border:1px solid #d9d9d9; overflow:hidden; }}
</style></head><body>
<table id="grid"><colgroup>{colgroup}</colgroup><tbody>{''.join(body)}
</tbody></table></body></html>"""


if __name__ == "__main__":
    import sys
    from automations.captainship_drafts.config import BY_KEY
    key = sys.argv[1] if len(sys.argv) > 1 else "rafael"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("output")
    shots = captain_shots(key, BY_KEY[key].flavor, out)
    print(f"product_summary: {shots['product_summary']}")
    for cap, path in shots["units"]:
        print(f"units [{cap}]: {path}")
