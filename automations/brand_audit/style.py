"""Lucy's learned posting style — accumulates Megan/Raf's feedback so captions
and photo edits get it right the first time over time.

Every correction (a ❌ + a thread note) is appended here; the standing caption
feedback is fed into EVERY caption generation, and the preferred photo crop
(zoom) is learned too. Seeded with the lessons from the first sessions so Lucy
starts smart.

Stored at ~/.config/brand-audit/learned_style.json (outside the repo).
"""
from __future__ import annotations

import json
from pathlib import Path

_FILE = Path.home() / ".config" / "brand-audit" / "learned_style.json"
_MAX_RULES = 30          # keep the most recent N so the prompt stays tight
_MAX_NOTE_LEN = 180

# Lessons learned in the first sessions (2026-06-19). Used as the starting point
# the first time the file is created.
_SEED = {
    "caption_feedback": [
        "First names only — never use last names.",
        "Keep it short and human; not wordy. No AI-sounding balanced three-part "
        "phrases (tricolons) and no filler hype ('locked in', 'well earned', "
        "'just getting started').",
        "No slang (e.g. 'dude', 'showing out', 'hit different').",
        "Feature the person being promoted/featured; the trainer/mentor is "
        "secondary — mention them in passing at most.",
        "Be accurate — a Level 1 is a first/entry promotion; never imply "
        "leadership or overstate it; invent nothing.",
        "Write for 20-25yo applicants, like a real teammate would — not marketing.",
    ],
    "photo_feedback": [
        "Crop tight / zoomed in on the subjects — avoid big empty ceiling/floor.",
    ],
    "photo_default_zoom": 1.2,
}


def _load() -> dict:
    try:
        return json.loads(_FILE.read_text())
    except Exception:
        _save(dict(_SEED))
        return dict(_SEED)


def _save(d: dict) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    _FILE.write_text(json.dumps(d, indent=2))


def _similar(lst: list[str], note: str) -> bool:
    n = note.lower()
    return any(n == x.lower() or n in x.lower() or x.lower() in n for x in lst)


def caption_rules() -> list[str]:
    """Standing caption feedback to apply to every generation."""
    return _load().get("caption_feedback", [])


def add_caption_feedback(note: str) -> None:
    note = (note or "").strip()[:_MAX_NOTE_LEN]
    if not note:
        return
    d = _load()
    lst = d.setdefault("caption_feedback", [])
    if not _similar(lst, note):
        lst.append(note)
        d["caption_feedback"] = lst[-_MAX_RULES:]
        _save(d)


def photo_default_zoom() -> float:
    return float(_load().get("photo_default_zoom", 1.0))


def add_photo_feedback(note: str, zoom: float | None = None) -> None:
    d = _load()
    lst = d.setdefault("photo_feedback", [])
    note = (note or "").strip()[:_MAX_NOTE_LEN]
    if note and not _similar(lst, note):
        lst.append(note)
        d["photo_feedback"] = lst[-_MAX_RULES:]
    if zoom and zoom > 1.0:
        # nudge the default crop tighter toward what they keep asking for
        d["photo_default_zoom"] = round(
            min(1.5, max(float(d.get("photo_default_zoom", 1.0)), zoom * 0.9)), 2)
    _save(d)
