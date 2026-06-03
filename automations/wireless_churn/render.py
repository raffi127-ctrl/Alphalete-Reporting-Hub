"""Render the 4 Wireless Churn period sections as multi-week PNGs.

Same layout + thresholds as new_internet_churn.render — different title
prefix and blue palette so the Slack post visually differs from the
orange New Internet Churn images posted in the same thread.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from automations.new_internet_churn import render as _shared

# Blue palette (Wireless)
TITLE_BG       = (32, 96, 168)
OFFICE_AVG_BG  = (210, 226, 246)
SECTION_HDR_BG = (140, 178, 226)

TITLE_BY_PERIOD = {
    "0-30": "WIRELESS CHURN — 0-30 DAY",
    "30":   "WIRELESS CHURN — 30 DAY",
    "60":   "WIRELESS CHURN — 60 DAY",
    "90":   "WIRELESS CHURN — 90 DAY",
}


def render_multi_week(ws, section, period, today, out_path,
                      n_weeks: int = _shared.N_WEEKS,
                      show_subtitle: bool = True) -> Path:
    # Temporarily monkey-patch the shared module's section-header band
    # so the blue palette propagates through the date-row.
    saved = _shared.SECTION_HDR_BG
    try:
        _shared.SECTION_HDR_BG = SECTION_HDR_BG
        return _shared.render_multi_week(
            ws, section, period, today, out_path,
            n_weeks=n_weeks,
            title_bg=TITLE_BG,
            office_avg_bg=OFFICE_AVG_BG,
            title_text=TITLE_BY_PERIOD.get(period, f"WIRELESS CHURN — {period} DAY"),
            show_subtitle=show_subtitle,
        )
    finally:
        _shared.SECTION_HDR_BG = saved


def render_all_sections(ws, sections, today, out_dir,
                         n_weeks: int = _shared.N_WEEKS) -> dict:
    out: dict = {}
    out_dir.mkdir(parents=True, exist_ok=True)
    for period, sect in sections.items():
        path = out_dir / f"wireless_churn_{period.replace('-', '_')}_day.png"
        render_multi_week(ws, sect, period, today, path, n_weeks=n_weeks)
        out[period] = path
    return out
