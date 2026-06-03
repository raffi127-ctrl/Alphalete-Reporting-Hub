"""Render a captain's churn buckets to PNGs, reusing the existing
multi-week render engine (new_internet_churn / wireless_churn).

Returns an ordered list of (caption, path) so the email builder can drop
them inline under the churn section in bucket order (0-30, 30, 60, 90,
and 120 for B2B). No new rendering logic — just orchestration over the
captain's configured ChurnSource(s)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import List, Tuple

from automations.captainship_drafts.config import Captain, BUCKET_ORDER
from automations.new_internet_churn import render as _ni


def render_captain(captain: Captain, today: dt.date, out_dir: Path,
                   *, logfn=print) -> List[Tuple[str, Path]]:
    """Render every churn bucket for `captain` across all their churn
    sources. Returns [(caption, png_path), ...] in (source, bucket) order.

    Reads the LIVE sheet — the churn run must have filled today's column
    already (this module runs after the churn runs)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    images: List[Tuple[str, Path]] = []

    for src in captain.churn:
        ws = src.open_ws()
        sections = _find_sections(src, ws)
        sub_dir = out_dir / f"{captain.key}_{_slug(src.label)}"
        sub_dir.mkdir(parents=True, exist_ok=True)
        # Render each bucket directly (not render_all_sections) so we can
        # pass show_subtitle=False — the email drops the 'Last 7 fills…'
        # subtitle the Slack post keeps.
        # Brand color on the title bar for NI blocks; Rafael's Wireless
        # keeps the render's own default (brand_title=False). title_fg is
        # auto-contrasted so pale brands (Luis, Colten, Jairo) get dark text.
        kw = {"show_subtitle": False}
        if src.brand_title:
            kw["title_bg"] = captain.title_bg
            kw["title_fg"] = _ni.contrast_fg(captain.title_bg)
        rendered = 0
        for period in BUCKET_ORDER:
            sect = sections.get(period)
            if sect is None:
                continue
            path = sub_dir / f"{_slug(src.label)}_{period.replace('-', '_')}_day.png"
            src.render_mod.render_multi_week(
                ws, sect, period, today, path, **kw)
            images.append((f"{src.label} — {period} Day", path))
            rendered += 1
        logfn(f"  {captain.key}/{src.label}: rendered {rendered} bucket(s)")

    return images


def _find_sections(src, ws):
    """Locate sections via the render module's fill sibling. Both render
    modules import their own fill; new_internet_churn.fill.find_sections
    is the shared implementation re-exported everywhere, so import it
    directly to avoid guessing."""
    from automations.new_internet_churn import fill as _fill
    return _fill.find_sections(ws)


def _slug(s: str) -> str:
    return s.lower().replace(" ", "_")
