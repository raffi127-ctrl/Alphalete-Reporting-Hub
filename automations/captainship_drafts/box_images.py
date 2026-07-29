"""Render a captain's one-column-per-day metric boxes to PNGs.

Six sections of the fiber draft come from boxes we fill daily on three
workbooks — cancel rate (0-30 / 30-60), activation rate (0-30 / 30-60), ABP %
and 6+-days-out. Each is a box on a tab, all six share the same shape, so this
module is just orchestration over config.BoxSource + daily_box_render.

The worksheet for a tab is opened ONCE per captain even though two boxes live
on it (cancel 0-30 and 30-60 are the same tab), because opening a worksheet is
a Sheets API round-trip and this runs for five captains in a row.

A box that can't be read degrades to no image: the caller drops it from the
bundle and email_build shows a per-section 'pending' note. A section quietly
rendering the WRONG thing would be far worse than one that says it's missing.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict

from automations.captainship_drafts import daily_box_render
from automations.captainship_drafts.config import Captain
from automations.new_internet_churn.render import contrast_fg


def render_captain(captain: Captain, today: dt.date, out_dir: Path,
                   *, logfn=print) -> Dict[str, Path]:
    """Render every configured box for `captain`. Returns {slot: png_path},
    missing slots meaning 'couldn't be produced'."""
    if not captain.boxes:
        return {}
    out_dir.mkdir(parents=True, exist_ok=True)
    sub_dir = out_dir / f"{captain.key}_boxes"
    sub_dir.mkdir(parents=True, exist_ok=True)

    ws_cache: dict = {}
    sect_cache: dict = {}
    out: Dict[str, Path] = {}
    fg = contrast_fg(captain.title_bg)

    for src in captain.boxes:
        try:
            key = src.cache_key
            if key not in ws_cache:
                ws_cache[key] = src.open_ws()
                sect_cache[key] = src.find(ws_cache[key])
            ws, sections = ws_cache[key], sect_cache[key]
            section = sections.get(src.box)
            if section is None:
                logfn(f"  ⚠ {captain.key}/{src.slot}: box {src.box!r} not found "
                      f"on the tab (boxes present: {sorted(sections)})")
                continue
            path = sub_dir / f"{src.slot}.png"
            daily_box_render.render_box(
                ws, section, src.title, path, today=today,
                title_bg=captain.title_bg, title_fg=fg)
            out[src.slot] = path
        except Exception as e:  # noqa: BLE001 — one box must not kill the draft
            logfn(f"  ⚠ {captain.key}/{src.slot}: not rendered "
                  f"({type(e).__name__}: {e})")

    logfn(f"  {captain.key}: rendered {len(out)}/{len(captain.boxes)} metric box(es)")
    return out
