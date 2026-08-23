"""Render the Org WOW Sales Board image — the All Units DELTA CHART.

Megan 2026-08-23: the board Raf means is ONLY the bottom section of the All
Units email — the "All Units - All Campaigns" per-day This week / Last week /
Delta chart (red/green), now with the 1..n rank chain in its col-A gutter so
the board itself says how many owners it lists.

The range comes from all_campaigns_board.slack_post.capture_ranges — the same
derivation the board's email and Slack DM use — so this image can never crop
differently from theirs. Rendered from the Sheet via the email's PDF-export
engine: no Tableau, no browser, works from Lucy 1 with the shared Google OAuth
token.

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

from pathlib import Path


def capture_wow_board(out_dir: Path) -> Path:
    """The entire delta chart as ONE PNG. Raises if the block can't be found
    (template change) — never renders a guessed range."""
    from automations.all_campaigns_board.slack_post import _find_ws, capture_ranges
    from automations.org_sales_board.run import SHEET_ID
    from automations.org_sales_board.screenshot_email import (
        _access_token, _export_png)
    from automations.recruiting_report.fill import open_by_key, _retry

    sh = open_by_key(SHEET_ID)
    ws = _find_ws(sh)
    grid = _retry(ws.get_all_values)
    # ALWAYS most-to-least apps for the week (Megan 2026-08-23). The daily fill
    # sorts the board, but numbers keep landing after it runs — re-rank with
    # the board's own sorter right before the shot so the order is true at
    # send time, whatever time that is. Idempotent when already sorted; col A's
    # rank chain stays put by design.
    from automations.all_campaigns_board import sort_board as _sb
    _sb.sort_board(ws, grid)
    grid = _retry(ws.get_all_values)
    rng = next((r for n, r in capture_ranges(grid) if n == "delta"), None)
    if not rng:
        raise RuntimeError("All Units delta chart not found — template changed?")
    out_dir.mkdir(parents=True, exist_ok=True)
    return _export_png(ws.id, rng, out_dir / "org_wow_board.png",
                       _access_token())
