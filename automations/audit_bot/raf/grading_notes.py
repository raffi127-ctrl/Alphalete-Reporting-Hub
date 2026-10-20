"""Persistent grading-notes layer (Raf's 2026-08-04 ask).

Admins DM Lucy adjustments to HOW she grades ("stop docking points for a short
chitchat"). Each note is stored here and appended to the framework system prompt
on every audit, so a tweak takes effect on the very next submission — no code
edits, no restart, and it's reversible. `framework.py` stays the stable base.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

RUNTIME_DIR = Path(__file__).parent.resolve()
NOTES_FILE = RUNTIME_DIR / "grading_notes.json"


def load_notes() -> list[dict]:
    try:
        data = json.loads(NOTES_FILE.read_text(encoding="utf-8"))
        return data.get("notes", []) if isinstance(data, dict) else []
    except Exception:
        return []


def _save(notes: list[dict]) -> None:
    NOTES_FILE.write_text(
        json.dumps({"notes": notes}, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def add_note(text: str, by: str = "") -> dict:
    notes = load_notes()
    note = {"text": text.strip(), "added_at": datetime.now().isoformat(), "by": by}
    notes.append(note)
    _save(notes)
    return note


def remove_last() -> dict | None:
    notes = load_notes()
    if not notes:
        return None
    dropped = notes.pop()
    _save(notes)
    return dropped


def clear() -> int:
    n = len(load_notes())
    _save([])
    return n


def as_prompt_addendum() -> str:
    """Text block appended to FRAMEWORK at grade-time. Empty when no notes."""
    notes = load_notes()
    if not notes:
        return ""
    lines = "\n".join(f"- {n.get('text','')}" for n in notes)
    return (
        "\n\n# ADDITIONAL GRADING DIRECTIVES (from Rafael)\n"
        "Apply these on top of the 11-frame framework above. If any of them "
        "conflict with the frames, THESE DIRECTIVES WIN:\n" + lines + "\n"
    )
