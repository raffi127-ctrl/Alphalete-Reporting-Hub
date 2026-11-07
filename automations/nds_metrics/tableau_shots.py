"""Tableau view screenshots for the NDS Metrics thread (Carlos 2026-11-07).

  * rep_tiers -- the NDS workbook's "Order Tiered Bonus - Rep Ranking" view,
    Owner Name = Carlos Hidalgo (the view's own default Time Frame is This
    Week): which reps are one order away from the next tier bonus. "We used
    to post this in the past when we were doing B2B ... Every morning in the
    NDS metrics thread, post this screenshot."
  * top_reps -- the workbook's "Top 100 Reps View", the top 50.

Same capture as every other Tableau shot (tableau_screenshots.capture_page:
Tableau's own Download -> Image, full canvas) inside the shared
tableau_session; then the board is cropped to the table's bottom border
(the canvas carries a page of white space under a short table) and the
Top 100 view to its first 50 rep rows. A blank board (an owner the filter
does not know) raises, so the section is skipped rather than posted empty.
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional
from urllib.parse import quote

WORKBOOK = "https://us-east-1.online.tableau.com/#/site/sci/views/NDS-SNRES-ATT-OOFWorkbook/"
OWNER = "Carlos Hidalgo"          # the view's Owner Name member, as Tableau spells it
TOP_REPS = 50

VIEWS = {
    "rep_tiers": {
        "title": "NDS Rep Tiered Ranking (this week)",
        "url": WORKBOOK + "OrderTieredBonus-RepRanking?" + quote("Owner Name") + "=" + quote(OWNER),
        "crop": "table",
    },
    "top_reps": {
        "title": "NDS Top %d Reps" % TOP_REPS,
        "url": WORKBOOK + "Top100RepsView",
        "rows": TOP_REPS,
    },
}


def crop_to_table(png: Path, extra_px: int = 30) -> Path:
    """Cut the canvas at the table's bottom border: the last pixel row whose
    dark pixels span more than half the image width (the footer box under
    it is narrower, the white space has none). No wide dark row = untouched."""
    from PIL import Image
    im = Image.open(png)
    g = im.convert("L")
    w, h = g.size
    px = g.load()
    bottom = None
    for y in range(h):
        dark = 0
        for x in range(0, w, 2):
            if px[x, y] < 160:
                dark += 1
        if dark > (w / 2) * 0.5:
            bottom = y
    if bottom is None or bottom + extra_px >= h:
        return png
    im.crop((0, 0, w, bottom + extra_px)).save(png)
    return png


def _wide_lines(g, frac: float = 0.6):
    """y of every horizontal grid line: pixel rows whose dark pixels span
    more than `frac` of the width, consecutive rows collapsed to the first."""
    w, h = g.size
    px = g.load()
    out = []
    prev = -5
    for y in range(h):
        dark = 0
        for x in range(0, w, 4):
            if px[x, y] < 160:
                dark += 1
        if dark > (w / 4) * frac:
            if y - prev > 1:
                out.append(y)
            prev = y
    return out


def crop_rows(png: Path, n: int, extra_px: int = 4) -> Path:
    """Keep the header and the first n DATA rows of a Tableau crosstab: the
    data rows are the run of grid lines with the modal gap (Top 100 Reps:
    64 px); the cut is the line that closes row n. Fewer rows than n, or no
    grid = untouched."""
    from PIL import Image
    im = Image.open(png)
    ys = _wide_lines(im.convert("L"))
    gaps = [b - a for a, b in zip(ys, ys[1:])]
    if len(gaps) < 3:
        return png
    modal = sorted(gaps)[len(gaps) // 2]
    first = next((i for i, gp in enumerate(gaps) if abs(gp - modal) <= 3), None)
    if first is None or first + n >= len(ys):
        return png
    bottom = ys[first + n] + extra_px
    im.crop((0, 0, im.size[0], bottom)).save(png)
    return png


def looks_blank(png: Path) -> bool:
    from automations.office_metrics.metrics_shot import _looks_blank
    return _looks_blank(png)


def capture(key: str, out_dir: Path, log=print, headless: bool = True) -> Path:
    from automations.shared.tableau_patchright import tableau_session
    from automations.tableau_screenshots import capture as _cap
    v = VIEWS[key]
    spec = {"id": "nds_" + key, "title": "nds_" + key, "url": v["url"], "crop": "canvas"}
    out_dir.mkdir(parents=True, exist_ok=True)
    with tableau_session(headless=headless, allow_form_login=False, verbose=False) as page:
        png = Path(_cap.capture_page(page, spec, out_dir, verbose=False))
    if looks_blank(png):
        raise RuntimeError("%s: the board came back blank (filter member missing?) -- not posting" % key)
    if v.get("rows"):
        crop_rows(png, int(v["rows"]))
    elif v.get("crop") == "table":
        crop_to_table(png)
    log("[nds] tableau shot %s -> %s" % (key, png.name))
    return png
