"""A running joke for ONE rep in ONE room, every Nth time Lucy names them.

Megan 2026-10-27, Raf's room: "train lucy to specifically call Pranish a YN
when he gets called out or makes a sale ... in a reply on that thread 'Don't
Tell Megan' ... not on every single thing for him - just do it like every 3
... It should say his name and YN - not just YN."

So: the line still names him, with the tag after his name ("Pranish YN is on
the board"), and the thread under that post gets the aside. Counted per rep
per room, so the third mention is the third mention whatever Lucy was saying.
Nothing here fires for any other rep or any other room: the table below is
the whole feature, and an absent entry is "never".
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Optional

ASIDES: Dict[str, Dict[str, dict]] = {
    # room -> rep (lowercase full name) -> rule
    "ao-board": {                       # #alphalete-sales sale lines (Raf's board)
        # THE ASIDE IS LUCY GETTING AWAY WITH SOMETHING (Megan 2026-10-27:
        # "it's about profanity so we need to make it funny - like Lucy is
        # pulling one over on me"). Rotates, so the joke doesn't go stale.
        "pranish shrestha": {"every": 3, "tag": "YN", "aside": (
            "Don't tell Megan I said that 🤫",
            "That one stays between us. Megan thinks I'm PG 😇",
            "If Megan asks, YN stands for Young Professional 🤫",
            "Shhh 👀 Megan reads these. Act normal.",
            "Delete this before Megan logs on 🫣",
            "Megan said keep it clean. Megan is not in this thread 😌",
            "Language, habibi 🧼 ...is what I'd say if Megan were watching 🤫",
        )},
    },
    "rafael-gaps": {                    # Raf's typed "15 min of gaps" list (texts)
        "pranish shrestha": {"every": 3, "tag": "YN", "aside": ""},
    },
}

STATE_PATH = Path.home() / ".config" / "recruiting-report" / "rep_asides.json"


def _norm(name: str) -> str:
    return " ".join(str(name or "").split()).lower()


def _load() -> Dict[str, int]:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:  # noqa: BLE001 -- no file yet, or unreadable: start at 0
        return {}


def _save(data: Dict[str, int]) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(data, indent=2, sort_keys=True))
    except OSError:
        pass


def due(room: str, rep: str, *, remember: bool = True) -> Optional[dict]:
    """The rule to apply to THIS mention, or None.

    Every mention counts; the rule applies on the Nth. `remember=False`
    (a dry run) reads the counter without advancing it, so a preview never
    spends a real mention.
    """
    rule = (ASIDES.get(room) or {}).get(_norm(rep))
    if not rule:
        return None
    key = "%s|%s" % (room, _norm(rep))
    data = _load()
    n = int(data.get(key, 0)) + 1
    if remember:
        data[key] = n
        _save(data)
    every = max(int(rule.get("every", 1)), 1)
    if n % every:
        return None
    # A pool of asides rotates in order, one per firing, so the joke moves.
    aside = rule.get("aside") or ""
    if isinstance(aside, (list, tuple)):
        aside = aside[((n // every) - 1) % len(aside)] if aside else ""
    return {**rule, "aside": aside}


def tag_name(text: str, name: str, tag: str) -> str:
    """'Pranish is on the board' -> 'Pranish YN is on the board'.

    The first whole-word occurrence of `name` (any casing, so a SUPER-tier
    'PRANISH' works too); the tag follows the name as written. Unchanged when
    the name is not in the text.
    """
    if not name or not tag:
        return text
    pat = re.compile(r"\b(%s)\b" % re.escape(name), re.I)
    return pat.sub(lambda m: "%s %s" % (m.group(1), tag), text, count=1)
