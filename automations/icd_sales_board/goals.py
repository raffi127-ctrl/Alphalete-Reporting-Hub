"""Weekly team goals — the owner's number, not the board's.

Raf's board carries a "Team Weekly Goal" column, but a goal is a decision an
owner makes and changes, so it has to be settable from the site rather than by
opening the sheet. A saved goal wins over the board's value; a team with no
saved goal keeps showing whatever the sheet says.

Keyed by office and team. Stored per office so one owner editing a goal can
never touch another's — the same reason the office registry refuses to let two
offices share a channel or a view.
"""
from __future__ import annotations

import json
from pathlib import Path

STORE = Path("output/icd_sales_board/goals")


def _path(office_key: str) -> Path:
    return STORE / f"{office_key}.json"


def load(office_key: str) -> dict:
    """{team: goal} — only the goals an owner has actually set."""
    p = _path(office_key)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def get(office_key: str, team: str, fallback: str = "") -> str:
    """The owner's goal for a team, else the board's own value."""
    return str(load(office_key).get(team, fallback) or fallback)


# Recruiting-funnel goals live in the same per-office store under a namespaced
# key. Every office sets its own — a 25-rep office and a 200-rep office do not
# share a target, and one org-wide number would be wrong for nearly everyone
# (Megan 2026-08-17).
_STAGE_PREFIX = "funnel:"


def stage_goal(office_key: str, stage_key: str, fallback=None):
    """This office's goal for a funnel stage, as a fraction, or None.

    None means nobody has set one — the display must then show the actual with
    NO goal line rather than invent a target."""
    raw = load(office_key).get(_STAGE_PREFIX + stage_key)
    if raw in (None, ""):
        return fallback
    try:
        v = float(str(raw).replace("%", "").strip())
    except ValueError:
        return fallback
    return v / 100 if v > 1 else v


def set_stage_goal(office_key: str, stage_key: str, pct) -> None:
    """Store a funnel goal as a PERCENT ('50' or '50%'). Blank clears it."""
    set_goal(office_key, _STAGE_PREFIX + stage_key, pct)


def set_goal(office_key: str, team: str, goal) -> None:
    """Save one team's goal. A blank clears the override so the board's own
    number shows again, rather than pinning a zero nobody chose."""
    data = load(office_key)
    text = str(goal).strip()
    if text:
        data[team] = text
    else:
        data.pop(team, None)
    STORE.mkdir(parents=True, exist_ok=True)
    _path(office_key).write_text(json.dumps(data, indent=2), encoding="utf-8")
