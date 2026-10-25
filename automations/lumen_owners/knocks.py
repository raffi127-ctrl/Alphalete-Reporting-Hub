"""Yesterday's Quantum Fiber knock boards for the Lumen Owners mail.

WHY (Eve, 2026-10-23): the mail now goes to Chan + the Quantum owners and
should look like a captainship mail, which carries knock boards. These are
the SAME boards Chan's captainship draft draws for his Quantum owners
(OwnerVille campaign 7): the owner list is captainship_drafts.config.
EXTRA_CAMPAIGN_KNOCK_OWNERS["chan"], so when Myles Neal / Angel Padilla give
Office Access and get uncommented there, both mails pick them up — one list.
LUMEN_EXTRA adds the Lumen owners who aren't Chan's (Christian, Lala, Nigel).

The boards go as PDFs attached to the mail, not as pictures in the body
(Eve, 2026-10-24) — the body only says they're attached. Like a captainship
mail: one PDF with every board + one per owner (Eve, 2026-10-25). A board that can't be
pulled becomes a note line; it never stops the mail.
"""
from __future__ import annotations

import datetime as dt
import html
from pathlib import Path
from typing import List, Tuple

CAPTAIN_KEY = "chan"

# Lumen owners with Quantum knocks who are NOT Chan's (Raf, 2026-10-25: "I
# thought we already had Christian, Lala & Nigel?"). Both already have
# OwnerVille access on campaign 7: Christian's picker (knocks_pull
# CAMPAIGN_OVERRIDES), Lala's nightly Quantum dispositions (gap_alerts
# LALA_QF). Nigel Marshall gave Office Access 2026-10-25 (office 20034, Eve).
LUMEN_EXTRA = (
    ("Christian Esposito", "7", "Quantum Fiber"),
    ("Lajahnik Valentine", "7", "Quantum Fiber"),
    ("Nigel Marshall", "7", "Quantum Fiber"),
)


def owner_boards(aliases_raw, logfn=print) -> List[Tuple[str, dict]]:
    """[(label, cfg)] — one per Quantum owner with OwnerVille access: Chan's
    list first, then LUMEN_EXTRA."""
    from automations.captainship_drafts import config as _cfg
    from automations.captainship_drafts.knock_dispo_images import (
        extra_campaign_pairs)
    chan = tuple((getattr(_cfg, "EXTRA_CAMPAIGN_KNOCK_OWNERS", {}) or {}
                  ).get(CAPTAIN_KEY, ()))
    seen = {s[0] for s in chan}
    specs = chan + tuple(s for s in LUMEN_EXTRA if s[0] not in seen)
    return extra_campaign_pairs(CAPTAIN_KEY, aliases_raw, logfn=logfn,
                                specs=specs)


def note_html(failed: List[Tuple[str, str]]) -> str:
    """One orange line per board that could not be drawn. Pure."""
    return "".join(
        '<p style="color:#b35900;font-size:12px">Knocks for %s could not be '
        "pulled this run (%s).</p>" % (html.escape(label), html.escape(why))
        for label, why in failed)


PDF_LABEL = "Daily Knocks — Quantum Fiber"
TITLE = "Lumen Owners"


def owner_name(label: str) -> str:
    """'Nigel Marshall (Quantum Fiber)' -> 'Nigel Marshall'. Pure."""
    return label.split(" (", 1)[0].strip()


def pdf_files(blocks, day: dt.date, out_dir: Path) -> list:
    """[(attachment label, pdf)] the captainship way (Eve, 2026-10-25): one
    PDF with every board, then one PDF per owner, named owner-first
    ('Nigel Marshall - Daily Knocks disposition - Oct 24, 2026') so each
    owner can pick out their own on a phone."""
    from automations.captainship_drafts.daily_pdf import attachment_name
    from automations.captainship_drafts.pdf_pages import compose
    label = lambda who: attachment_name(who, day)[:-len(".pdf")]
    out_dir = Path(out_dir)
    files = [(label(TITLE), compose(
        blocks, out_dir / ("knocks-%s.pdf" % day.isoformat())))]
    for lab, png in blocks:
        who = owner_name(lab)
        files.append((label(who), compose(
            [(who, png)], owner_dir(out_dir, lab) / "knocks.pdf")))
    return files


def owner_dir(out_dir: Path, label: str) -> Path:
    """out_dir/<label as a folder name>, created. Pure but for the mkdir."""
    d = Path(out_dir) / "".join(c if c.isalnum() else "_" for c in label)
    d.mkdir(parents=True, exist_ok=True)
    return d


def build(today: dt.date, out_dir: Path, aliases_raw, logfn=print
          ) -> Tuple[list, list]:
    """(email blocks, files to attach). One DAILY TOTAL KNOCKS board per owner
    for yesterday, all in one PDF; the body gets an "attached" line plus a
    note for any board that failed. ([], []) when nobody is configured."""
    from automations.captainship_drafts import knock_dispo_images as K
    from automations.shared.tableau_patchright import ownerville_session

    pairs = owner_boards(aliases_raw, logfn=logfn)
    if not pairs:
        return [], []
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
                    # One folder per owner: the board's file name is only
                    # the date, so a shared folder left every page the LAST
                    # owner's board (4x Nigel, 2026-10-25).
                    png = K.render_owner_daily_board(
                        target, rows, rows, owner_dir(out_dir, label), label)
                    blocks.append((label, png))
                    logfn("[lumen] knocks %s: %d rep(s)" % (label, len(rows)))
                except Exception as e:  # noqa: BLE001 — one owner, not the mail
                    failed.append((label, type(e).__name__))
                    logfn("[lumen] knocks %s FAILED: %s: %s"
                          % (label, type(e).__name__, e))
    except Exception as e:  # noqa: BLE001 — no OwnerVille, still a mail
        logfn("[lumen] OwnerVille session FAILED: %s: %s" % (type(e).__name__, e))
        failed = [(l, "OwnerVille login failed") for l, _c in pairs]
        blocks = []
    files, out = [], []
    if blocks:
        try:
            files = pdf_files(blocks, target, out_dir)
            out = [(PDF_LABEL, None, None, "attached")]
        except Exception as e:  # noqa: BLE001 — a note, not a dead mail
            logfn("[lumen] knocks PDF FAILED: %s: %s" % (type(e).__name__, e))
            failed += [(l, "PDF failed") for l, _p in blocks]
    if failed:
        out.append((note_html(failed), None, None, "note"))
    return out, files
