"""This week's batch, kept on disk so the card can show it and edit it.

Megan, 2026-09-17: she wants the names ON THE CARD, with the ability to untick
anybody who should not go in — twice asked for, so it belongs there and not
only on the panel in Apex.

The card cannot re-read the board to do that: the board and everyone's Blue Ink
packet is the slow half (most of the minute). So `--button` writes what it
built here, and unticking rebuilds the clipboard from this file. No network, no
second fetch.

Nothing sensitive is in here. It is the same information the setup carries —
names, start dates, and the answers off their I-9 — and never a Social: those
are typed at run time and are not in the setup either.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
PATH = REPO_ROOT / "output" / ".apex-batch.json"


def save(*, week: str, build: str, notice: str, start: str,
         people: List[Dict]) -> None:
    """Keep what --button just built, for the card to show."""
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(
            {"week": week, "build": build, "notice": notice, "start": start,
             "people": people}, separators=(",", ":")), encoding="utf-8")
    except Exception:
        pass            # never worth failing a build over


def load() -> Optional[Dict]:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def names() -> List[str]:
    got = load() or {}
    return [p.get("name", "") for p in got.get("people") or []]


def setup_for(excluded) -> Optional[str]:
    """The setup text for everyone NOT excluded, or None if there is no batch.

    Rebuilt from the saved file, so unticking somebody costs nothing.
    """
    from automations.apex_new_starts import filler

    got = load()
    if not got:
        return None
    out = [p for p in got.get("people") or []
           if p.get("name") not in set(excluded or ())]
    if not out:
        return None
    return filler.build_js(out, got.get("week", ""), got.get("build", ""),
                           got.get("notice", ""), got.get("start", ""))[
        len("javascript:"):]
