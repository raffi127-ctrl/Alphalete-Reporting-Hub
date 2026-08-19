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

# Never more than this many columns, however much history a tab holds
# (Eve 2026-07-29: "máximo siempre los últimos 7 días, no más").
MAX_WEEKS = _ni.N_WEEKS


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
        # A block whose DATA changed product but kept its renderer overrides the
        # words in the title bar (B2B churn went wireless 2026-08-19 and keeps
        # the owner-colored New Internet look — Eve).
        if getattr(src, "title_prefix", ""):
            kw["title_text_fn"] = lambda per: f"{src.title_prefix} — {per} DAY"
        if src.brand_title:
            kw["title_bg"] = captain.title_bg
            kw["title_fg"] = _ni.contrast_fg(captain.title_bg)
        # Draw only the columns that actually carry a date. The renderer's
        # default is a fixed 7-wide grid, which on a YOUNG tab (the fiber
        # Wireless tabs opened with 2 days of history) painted five empty
        # columns to the right of the data — Eve 2026-07-29: the image should
        # grow a column per daily run instead, and stop at 7.
        filled = _dated_weeks(ws, sections)
        rendered = 0
        for period in BUCKET_ORDER:
            sect = sections.get(period)
            if sect is None:
                continue
            path = sub_dir / f"{_slug(src.label)}_{period.replace('-', '_')}_day.png"
            per_kw = dict(kw)
            title_fn = per_kw.pop("title_text_fn", None)
            if title_fn is not None:
                per_kw["title_text"] = title_fn(period)
            src.render_mod.render_multi_week(
                ws, sect, period, today, path,
                n_weeks=filled.get(period, MAX_WEEKS), **per_kw)
            images.append((f"{src.label} — {period} Day", path))
            rendered += 1
        logfn(f"  {captain.key}/{src.label}: rendered {rendered} bucket(s)")

    return images


def _dated_weeks(ws, sections: dict) -> dict:
    """{period: how many of the 7 week columns carry a date header}.

    ONE batch_get for every section on the tab — a read per bucket would be
    four extra round-trips per source, times two sources, times 12 captains.

    Date labels sit at B, D, F… (each header is merged across the %+units
    pair), so only every other cell is read. Counting STOPS at the first gap:
    history on these tabs is contiguous from B (newest) rightwards, so a blank
    means 'no more history', not 'one missing day'.
    """
    items = list(sections.items())
    if not items:
        return {}
    # B..O covers 7 merged week-pairs.
    ranges = [f"B{s['header_row']}:O{s['header_row']}" for _, s in items]
    try:
        result = ws.batch_get(ranges)
    except Exception:  # noqa: BLE001 — fall back to the full grid, never fail
        return {}

    out = {}
    for (period, _sect), rows in zip(items, result):
        row = rows[0] if rows else []
        n = 0
        for i in range(0, MAX_WEEKS * 2, 2):
            if not (row[i].strip() if i < len(row) else ""):
                break
            n += 1
        out[period] = max(1, min(n, MAX_WEEKS))
    return out


def _find_sections(src, ws):
    """Locate sections via the render module's fill sibling. Both render
    modules import their own fill; new_internet_churn.fill.find_sections
    is the shared implementation re-exported everywhere, so import it
    directly to avoid guessing."""
    from automations.new_internet_churn import fill as _fill
    return _fill.find_sections(ws)


def _slug(s: str) -> str:
    return s.lower().replace(" ", "_")
