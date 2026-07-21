"""Render Carlos's three B2B churn tabs to PNGs — one per product, per period.

Reuses the D2D renderers wholesale (Megan 2026-07-20: "do what we already do
for the 7 Fiber offices"). The B2B churn tabs are filled by the SAME
new_internet_churn.fill machinery, so they carry the identical section
structure the D2D renderers read — new_internet_churn.render and
wireless_churn.render work pointed straight at them.

AIR is the only product with no existing renderer. It is not a new renderer
either: the base render_multi_week already takes a title + palette, so AIR is a
thin variant (green palette, "AIR CHURN — <period> DAY" title), the same way
wireless_churn.render is a thin variant of new_internet's.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from automations.new_internet_churn import render as _ni
from automations.wireless_churn import render as _wl

# AIR palette — a green family, distinct from New Internet's orange and
# Wireless's blue so the three read apart in one thread.
AIR_TITLE_BG = (34, 139, 90)
AIR_OFFICE_AVG_BG = (208, 236, 220)
AIR_SECTION_HDR_BG = (150, 206, 178)
AIR_TITLE = {
    "0-30": "AIR CHURN — 0-30 DAY",
    "30":   "AIR CHURN — 30 DAY",
    "60":   "AIR CHURN — 60 DAY",
    "90":   "AIR CHURN — 90 DAY",
}


def _air_render_multi_week(ws, section, period, today, out_path,
                           n_weeks=_ni.N_WEEKS, show_subtitle=True):
    saved = _ni.SECTION_HDR_BG
    try:
        _ni.SECTION_HDR_BG = AIR_SECTION_HDR_BG
        return _ni.render_multi_week(
            ws, section, period, today, out_path, n_weeks=n_weeks,
            title_bg=AIR_TITLE_BG, office_avg_bg=AIR_OFFICE_AVG_BG,
            title_text=AIR_TITLE.get(period, "AIR CHURN — {} DAY".format(period)),
            show_subtitle=show_subtitle)
    finally:
        _ni.SECTION_HDR_BG = saved


def _air_render_all_sections(ws, sections, today, out_dir, n_weeks=_ni.N_WEEKS):
    out = {}
    out_dir.mkdir(parents=True, exist_ok=True)
    for period, sect in sections.items():
        if not _ni.section_has_data(ws, sect, n_weeks):
            continue
        path = out_dir / "air_churn_{}_day.png".format(period.replace("-", "_"))
        _air_render_multi_week(ws, sect, period, today, path, n_weeks=n_weeks)
        out[period] = path
    return out


# key -> the render_all_sections callable for that product's tab.
RENDERERS = {
    "new_int": _ni.render_all_sections,
    "wireless": _wl.render_all_sections,
    "air": _air_render_all_sections,
}


def render(key: str, ws, sections: dict, today: dt.date, out_dir: Path) -> dict:
    """Render one product's populated period sections. Returns {period: png}."""
    fn = RENDERERS.get(key)
    if fn is None:
        raise ValueError("no renderer for churn feed {!r}".format(key))
    return fn(ws, sections, today, out_dir)
