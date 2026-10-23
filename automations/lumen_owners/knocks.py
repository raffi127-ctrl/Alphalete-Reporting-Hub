"""Yesterday's Quantum Fiber knock boards for the Lumen Owners mail.

WHY (Eve, 2026-10-23): the mail now goes to Chan + the Quantum owners and
should look like a captainship mail, which carries knock boards. These are
the SAME boards Chan's captainship draft draws for his Quantum owners
(OwnerVille campaign 7): the owner list is captainship_drafts.config.
EXTRA_CAMPAIGN_KNOCK_OWNERS["chan"], so when Myles Neal / Angel Padilla give
Office Access and get uncommented there, both mails pick them up — one list.

A board that can't be pulled becomes a note line; it never stops the mail.
"""
from __future__ import annotations

import datetime as dt
import html
from pathlib import Path
from typing import List, Tuple

CAPTAIN_KEY = "chan"


def owner_boards(aliases_raw, logfn=print) -> List[Tuple[str, dict]]:
    """[(label, cfg)] — one per Quantum owner with OwnerVille access."""
    from automations.captainship_drafts.knock_dispo_images import (
        extra_campaign_pairs)
    return extra_campaign_pairs(CAPTAIN_KEY, aliases_raw, logfn=logfn)


def note_html(failed: List[Tuple[str, str]]) -> str:
    """One orange line per board that could not be drawn. Pure."""
    return "".join(
        '<p style="color:#b35900;font-size:12px">Knocks for %s could not be '
        "pulled this run (%s).</p>" % (html.escape(label), html.escape(why))
        for label, why in failed)


def build(today: dt.date, out_dir: Path, aliases_raw, logfn=print) -> list:
    """Email blocks: a DAILY TOTAL KNOCKS board per owner for yesterday, then a
    note for any that failed. [] when nobody is configured."""
    from automations.captainship_drafts import knock_dispo_images as K
    from automations.shared.tableau_patchright import ownerville_session

    pairs = owner_boards(aliases_raw, logfn=logfn)
    if not pairs:
        return []
    target = K.daily_target(today)
    out_dir = Path(out_dir) / "knocks"
    out_dir.mkdir(parents=True, exist_ok=True)
    blocks, failed = [], []
    # The box pictures (board.render_boxes) leave sheet_render's shared sync
    # playwright running, and a second sync playwright in the same thread dies
    # with "using Playwright Sync API inside the asyncio loop" — the first
    # test send, 2026-10-23. Same medicine as the captainship knocks.
    try:
        from automations.captainship_drafts import sheet_render
        sheet_render.close_renderer()
    except Exception:  # noqa: BLE001
        pass
    try:
        with ownerville_session(verbose=False, profile_dir=K.PROFILE_DIR) as page:
            for label, cfg in pairs:
                try:
                    rows = K._daily_rows_for_owner(page, cfg, aliases_raw, target)
                    if not rows:
                        failed.append((label, "no knocks in OwnerVille for %s"
                                       % target.strftime("%m/%d")))
                        continue
                    png = K.render_owner_daily_board(target, rows, rows,
                                                     out_dir, label)
                    blocks.append(("Daily Knocks — %s" % label, png))
                    logfn("[lumen] knocks %s: %d rep(s)" % (label, len(rows)))
                except Exception as e:  # noqa: BLE001 — one owner, not the mail
                    failed.append((label, type(e).__name__))
                    logfn("[lumen] knocks %s FAILED: %s: %s"
                          % (label, type(e).__name__, e))
    except Exception as e:  # noqa: BLE001 — no OwnerVille, still a mail
        logfn("[lumen] OwnerVille session FAILED: %s: %s" % (type(e).__name__, e))
        failed = [(l, "OwnerVille login failed") for l, _c in pairs]
        blocks = []
    if failed:
        blocks.append((note_html(failed), None, None, "note"))
    return blocks
