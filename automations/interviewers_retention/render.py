"""Draw each board as a PNG that is ONLY the board (Raf, 2026-11).

Raf's ask: "crop the image to the content: no gray margin or empty space on the
sides; readable on a phone without zooming (max width ~900px)". So:

  * the PNG is a screenshot of the board's own box, nothing around it -- no
    page background, no padding outside the table;
  * the box is at most MAX_W px wide, and the email paints it at its natural
    width (width:100%; max-width:<its width>px), never wider;
  * the type is big (BASE_PX) because a phone shrinks a ~880px picture to
    ~40% -- 24px text arrives at ~10px, still readable without pinching.
  * rendered at 2x so it stays sharp on a retina phone after that shrink.
"""
from __future__ import annotations

import html
from pathlib import Path
from typing import List, Optional

from automations.interviewers_retention.build import Board, colour, pct

MAX_W = 880             # CSS px; Raf: "max width ~900px"
BASE_PX = 24
SCALE = 2               # device pixels per CSS px in the PNG

GREEN_BG, GREEN_FG = "#cdebd3", "#155c2a"
RED_BG, RED_FG = "#f6d1cc", "#8f2318"

_CSS = f"""
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; background: #ffffff; }}
.board {{ display: inline-block; max-width: {MAX_W}px; background: #ffffff;
         font-family: Arial, Helvetica, sans-serif; color: #1d2420;
         font-size: {BASE_PX}px; }}
.head {{ padding: 14px 14px 10px; width: 0; min-width: 100%; box-sizing: border-box; }}  /* never widens the box */
.title {{ font-size: {BASE_PX + 6}px; font-weight: 700; letter-spacing: .02em; }}
.sub {{ font-size: {BASE_PX - 4}px; color: #5f6a63; margin-top: 4px; }}
.counts {{ margin-top: 10px; display: flex; gap: 10px; flex-wrap: wrap; }}
.pill {{ padding: 4px 12px; border-radius: 99px; font-weight: 700;
        font-size: {BASE_PX - 4}px; }}
.pill.good {{ background: {GREEN_BG}; color: {GREEN_FG}; }}
.pill.bad  {{ background: {RED_BG}; color: {RED_FG}; }}
.note {{ font-size: {BASE_PX - 4}px; color: #5f6a63; padding: 0 14px 12px; width: 0; min-width: 100%; }}
table {{ border-collapse: collapse; width: auto; }}  /* the box is as wide as the table */
th {{ background: #eef0ec; color: #5f6a63; font-size: {BASE_PX - 8}px;
     text-transform: uppercase; letter-spacing: .05em; font-weight: 700;
     padding: 8px 12px; text-align: right; border-bottom: 2px solid #b9bfb4;
     white-space: nowrap; }}
td {{ padding: 8px 12px; text-align: right; border-bottom: 1px solid #d9ddd6;
     white-space: nowrap; font-variant-numeric: tabular-nums; }}
th.l, td.l {{ text-align: left; }}
td.rk {{ color: #5f6a63; }}
td.nm {{ white-space: normal; font-weight: 600; }}
td.nm div {{ max-width: 340px; }}   /* a long office list wraps, never widens the table */
td.nm small {{ display: block; font-weight: 400; color: #5f6a63;
              font-size: {BASE_PX - 6}px; margin-top: 2px; }}
td.good {{ background: {GREEN_BG}; color: {GREEN_FG}; font-weight: 700; }}
td.bad  {{ background: {RED_BG}; color: {RED_FG}; font-weight: 700; }}
td.h {{ font-size: {BASE_PX - 4}px; }}
th.hist {{ border-left: 2px solid #b9bfb4; }}
td.hfirst {{ border-left: 2px solid #b9bfb4; }}
td.na {{ color: #9aa69f; }}
"""


def fmt(p: Optional[float]) -> str:
    return "—" if p is None else f"{round(p * 100)}%"


def board_html(b: Board, show_detail: bool = True) -> str:
    e = html.escape
    hist = b.history_labels
    head = (f'<th>#</th><th class="l">{e(b.name_header)}</th>'
            '<th>Booked</th><th>Showed</th><th>%</th>'
            + "".join(f'<th class="{"hist" if i == 0 else ""}">{e(l)}</th>'
                      for i, l in enumerate(hist)))
    rows: List[str] = []
    for i, ln in enumerate(b.lines, 1):
        det = (f"<small>{e(', '.join(ln.detail))}</small>"
               if show_detail and ln.detail else "")
        cells = [f'<td class="rk">{i}</td>',
                 f'<td class="l nm"><div>{e(ln.name)}{det}</div></td>',
                 f"<td>{ln.booked}</td>", f"<td>{ln.showed}</td>",
                 f'<td class="{colour(ln.pct)}">{fmt(ln.pct)}</td>']
        for j, p in enumerate(ln.history):
            cls = ["h", colour(p) or "na"] + (["hfirst"] if j == 0 else [])
            cells.append(f'<td class="{" ".join(cls)}">{fmt(p)}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    counts = (f'<div class="counts"><span class="pill good">{b.green} at 50% or more</span>'
              f'<span class="pill bad">{b.red} under 50%</span></div>') if b.lines else ""
    hist_note = (f'<div class="note">Last {len(hist)} columns: the % of each of the '
                 f'last {len(hist)} weeks, oldest to newest, this week included (each '
                 f'labelled by the Sunday it starts). — = no 2nd rounds booked that '
                 f'week.</div>') if hist else ""
    return (f'<div class="board" id="board"><div class="head">'
            f'<div class="title">{e(b.title)}</div><div class="sub">{e(b.subtitle)}</div>'
            f'{counts}</div>{hist_note}'
            f'<table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>'
            f'</div>')


def page(inner: str) -> str:
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>{_CSS}</style>"
            f"</head><body>{inner}</body></html>")


def _launch():
    try:
        from patchright.sync_api import sync_playwright        # what the repo uses
    except ImportError:                                          # pragma: no cover
        from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    try:
        browser = p.chromium.launch(channel="chrome", headless=True)
    except Exception:                                            # noqa: BLE001
        browser = p.chromium.launch(headless=True)
    return p, browser


def render_boards(boards: List[Board], out_dir: Path, stem: str = "board") -> List[Path]:
    """One PNG per board, cropped to the board's own box. Returns the paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    p, browser = _launch()
    paths: List[Path] = []
    try:
        ctx = browser.new_context(device_scale_factor=SCALE,
                                  viewport={"width": MAX_W, "height": 800})
        pg = ctx.new_page()
        for n, b in enumerate(boards, 1):
            pg.set_content(page(board_html(b)))
            path = out_dir / f"{stem}-{n}.png"
            pg.locator("#board").screenshot(path=str(path))
            _shrink(path)
            paths.append(path)
    finally:
        browser.close()
        p.stop()
    return paths


def _shrink(path: Path) -> None:
    """Same pixels, ~5x fewer bytes. A board is a handful of flat colours plus
    their antialiasing, so a 256-colour palette is visually identical -- and a
    tall 2x board otherwise weighs 1-2 MB each, making the mail ~8 MB."""
    from PIL import Image
    with Image.open(path) as im:
        q = im.convert("RGB").quantize(colors=256)   # median cut; works on old Pillow too
    q.save(path, optimize=True)


def css_width(path: Path) -> int:
    """The width the email should paint `path` at: its pixels / SCALE."""
    from PIL import Image
    with Image.open(path) as im:
        return round(im.width / SCALE)


# ------------------------------------------------- THIS WEEK BY DAY (Raf 11/12)
# A wide board: per day B / S / %, the week B / S / %, then 4 weekly %. Raf:
# readable on a phone at max ~900px; "if 3+ days don't fit, show only the %
# per day and leave Booked/Showed in the Week column". So the renderer tries
# the full layout, then the compact one, then steps the type down, and keeps
# the first that fits MAX_W.
DAY_FONTS = (24, 22, 20, 18)


def day_board_html(b, *, compact: bool, base: int) -> str:
    e = html.escape
    sub_px, th_px, small_px = base - 4, max(base - 8, 12), max(base - 6, 12)
    per_day = 1 if compact else 3
    top = [f'<th rowspan="2">#</th>', f'<th rowspan="2" class="l">{e(b.name_header)}</th>']
    second = []
    for i, d in enumerate(b.days):
        # Compact: the day on two short lines, so the header never sets the width.
        label = (f"{d:%a}<br>{d.month}/{d.day}" if compact else f"{d:%a} {d.month}/{d.day}")
        top.append(f'<th colspan="{per_day}" class="grp c">{label}</th>')
        second += (['<th class="grp">%</th>'] if compact else
                   ['<th class="grp">B</th>', "<th>S</th>", "<th>%</th>"])
    top.append('<th colspan="3" class="grp c wk">Week</th>')
    second += ['<th class="grp wk">B</th>', '<th class="wk">S</th>', '<th class="wk">%</th>']
    if b.history_labels:
        top.append(f'<th colspan="{len(b.history_labels)}" class="grp c">Last 4 weeks</th>')
        second += [f'<th class="{"grp" if i == 0 else ""}">{e(l)}</th>'
                   for i, l in enumerate(b.history_labels)]
    rows = []
    for n, ln in enumerate(b.lines, 1):
        det = f"<small>{e(', '.join(ln.detail))}</small>" if ln.detail else ""
        cells = [f'<td class="rk">{n}</td>', f'<td class="l nm"><div>{e(ln.name)}{det}</div></td>']
        for d in b.days:
            bk, sh = ln.days.get(d, [0, 0])
            p = pct(sh, bk)
            pc = f'<td class="{colour(p) or "na"} {"grp" if compact else ""}">{fmt(p)}</td>'
            if compact:
                cells.append(pc)
            else:
                cells += [f'<td class="grp">{bk if bk else "—"}</td>',
                          f'<td>{sh if bk else "—"}</td>', pc]
        cells += [f'<td class="grp wk">{ln.booked}</td>', f'<td class="wk">{ln.showed}</td>',
                  f'<td class="{colour(ln.pct)} wkp">{fmt(ln.pct)}</td>']
        for j, p in enumerate(ln.history):
            cells.append(f'<td class="h {colour(p) or "na"} {"grp" if j == 0 else ""}">{fmt(p)}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    counts = (f'<div class="counts"><span class="pill good">{b.green} at 50% or more</span>'
              f'<span class="pill bad">{b.red} under 50%</span></div>') if b.lines else ""
    css = f"""
    .board {{ font-size:{base}px; }}
    .board .title {{ font-size:{base + 6}px; }}
    .board .sub, .board .pill, .board .note {{ font-size:{sub_px}px; }}
    .board th {{ font-size:{th_px}px; padding:6px 8px; }}
    .board td {{ padding:7px 6px; }}
    .board td.h {{ font-size:{base - 2}px; }}
    .board td.nm small {{ font-size:{small_px}px; }}
    .board td.nm div {{ max-width:{base * 10}px; }}
    .board th.c {{ text-align:center; }}
    .board th.grp, .board td.grp {{ border-left:2px solid #b9bfb4; }}
    .board th.wk {{ background:#e3e7e0; color:#1d2420; }}
    .board td.wk {{ background:#f6f7f4; font-weight:600; }}
    .board td.wkp {{ font-size:{base + 2}px; }}
    """
    note = ('<div class="note">— = no 2nd rounds booked that day / week. '
            'Last 4 weeks = the same weeks as the podium below.</div>')
    return (f'<style>{css}</style><div class="board" id="board"><div class="head">'
            f'<div class="title">{e(b.title)}</div><div class="sub">{e(b.subtitle)}</div>'
            f'{counts}</div>{note}<table><thead><tr>{"".join(top)}</tr>'
            f'<tr>{"".join(second)}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def _fit_day_board(pg, b) -> str:
    """The first layout that fits MAX_W: full (only when < 3 days), then compact,
    each at decreasing type sizes. Measured with the width cap lifted."""
    tries = ([(False, f) for f in DAY_FONTS] if len(b.days) < 3 else []) + \
            [(True, f) for f in DAY_FONTS]
    last = None
    for compact, font in tries:
        doc = day_board_html(b, compact=compact, base=font)
        pg.set_content(page(doc))
        w = pg.evaluate("() => { const b = document.getElementById('board');"
                        " b.style.maxWidth = 'none'; return b.scrollWidth; }")
        last = doc
        if w <= MAX_W:
            return doc
    return last                      # smallest compact layout; the cap still applies


def render_day_boards(boards, out_dir: Path, stem: str = "week") -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    p, browser = _launch()
    paths: List[Path] = []
    try:
        ctx = browser.new_context(device_scale_factor=SCALE,
                                  viewport={"width": MAX_W, "height": 800})
        pg = ctx.new_page()
        for n, b in enumerate(boards, 1):
            doc = _fit_day_board(pg, b)
            pg.set_content(page(doc))
            path = out_dir / f"{stem}-{n}.png"
            pg.locator("#board").screenshot(path=str(path))
            _shrink(path)
            paths.append(path)
    finally:
        browser.close()
        p.stop()
    return paths
