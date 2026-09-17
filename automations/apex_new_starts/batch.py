"""This week's batch, kept on disk so the card can show it and edit it.

Megan, 2026-09-17: she wants the names ON THE CARD, with the ability to untick
anybody who should not go in — twice asked for, so it belongs there and not
only on the panel in Apex.

The card cannot re-read the board to draw that: the board and everyone's Blue
Ink packet is the slow half, most of that minute. So `--button` writes what it
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
NAME = ".apex-batch.json"
PATH = REPO_ROOT / "output" / NAME


def path_in(out_dir=None) -> Path:
    """Where the batch lives, for a given output directory.

    Callers pass the SAME output directory the run is using, so a test that
    redirects `run.OUTPUT_DIR` redirects this too. It did not, once: the suite
    wrote two people called "A" and "B" into the live batch and they turned up
    on Megan's card (2026-09-17). A hardcoded path inside a module a test can
    reach is a path a test will eventually write to.
    """
    return (Path(out_dir) / NAME) if out_dir else PATH


def save(*, week: str, build: str, notice: str, start: str,
         people: List[Dict], out_dir=None) -> None:
    """Keep what --button just built, for the card to show."""
    try:
        target = path_in(out_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(
            {"week": week, "build": build, "notice": notice, "start": start,
             "people": people}, separators=(",", ":")), encoding="utf-8")
    except Exception:
        pass            # never worth failing a build over


def load(out_dir=None) -> Optional[Dict]:
    try:
        return json.loads(path_in(out_dir).read_text(encoding="utf-8"))
    except Exception:
        return None


def names(out_dir=None) -> List[str]:
    got = load(out_dir) or {}
    return [p.get("name", "") for p in got.get("people") or []]


def setup_for(excluded, out_dir=None) -> Optional[str]:
    """The setup text for everyone NOT excluded, or None if there is no batch.

    Rebuilt from the saved file, so unticking somebody costs nothing.
    """
    from automations.apex_new_starts import filler

    got = load(out_dir)
    if not got:
        return None
    out = [p for p in got.get("people") or []
           if p.get("name") not in set(excluded or ())]
    if not out:
        return None
    return filler.build_js(out, got.get("week", ""), got.get("build", ""),
                           got.get("notice", ""), got.get("start", ""))[
        len("javascript:"):]
