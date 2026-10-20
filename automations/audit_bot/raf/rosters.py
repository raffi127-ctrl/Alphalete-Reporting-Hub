"""
Owners + reps roster management with fuzzy matching.
Shared between slack_watcher and scorecards.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

RUNTIME_DIR = Path(__file__).parent.resolve()
OWNERS_FILE = RUNTIME_DIR / "owners.json"
REPS_FILE = RUNTIME_DIR / "reps.json"

# Fuzzy match threshold — pretty liberal to handle accents, spelling variants
FUZZY_THRESHOLD = 0.75


# ---------- IO ----------

def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_owners() -> list[dict]:
    data = _load_json(OWNERS_FILE, {"owners": []})
    return data.get("owners", [])


def save_owners(owners: list[dict]) -> None:
    _save_json(OWNERS_FILE, {"_note": "Canonical owner roster", "owners": owners})


def load_reps() -> dict:
    data = _load_json(REPS_FILE, {"reps": {}})
    return data.get("reps", {})


def save_reps(reps: dict) -> None:
    _save_json(REPS_FILE, {"_note": "Maps Slack user_id → rep info + assigned owner.", "reps": reps})


# ---------- Fuzzy matching ----------

def _normalize(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    s = s.lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def match_owner(query: str, owners: list[dict] | None = None) -> tuple[dict | None, float, list[tuple[dict, float]]]:
    """Find the best matching owner for a free-text query.

    Returns: (best_match_or_None, best_score, top_3_candidates)
    A match is returned only if its score >= FUZZY_THRESHOLD.
    """
    if owners is None:
        owners = load_owners()
    if not query.strip():
        return None, 0.0, []

    q_norm = _normalize(query)
    scored: list[tuple[dict, float]] = []

    for owner in owners:
        name = owner.get("name", "")
        aliases = owner.get("aliases", []) or []
        # Build all candidate strings for this owner
        candidates = [name, _normalize(name).split()[0] if name else ""]
        candidates.extend(aliases)

        best = 0.0
        for c in candidates:
            if not c:
                continue
            sim = _similarity(q_norm, c)
            # Also boost if the query is contained in the candidate or vice versa
            if q_norm in _normalize(c) or _normalize(c) in q_norm:
                sim = max(sim, 0.85)
            if sim > best:
                best = sim
        scored.append((owner, best))

    scored.sort(key=lambda x: x[1], reverse=True)
    top3 = scored[:3]
    best_owner, best_score = scored[0] if scored else (None, 0.0)
    if best_owner and best_score >= FUZZY_THRESHOLD:
        return best_owner, best_score, top3
    return None, best_score, top3


# ---------- Owner mutations ----------

def add_owner(name: str, aliases: list[str] | None = None) -> dict:
    """Add a new owner. Returns the new owner dict."""
    owners = load_owners()
    # Generate ID
    new_id = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    # Make unique if collision
    base_id = new_id
    i = 2
    while any(o.get("id") == new_id for o in owners):
        new_id = f"{base_id}_{i}"
        i += 1
    new_owner = {
        "id": new_id,
        "name": name.strip(),
        "aliases": aliases or [name.split()[0].lower()] if name.strip() else [],
        "added_at": datetime.now().isoformat(),
        "source": "auto",
    }
    owners.append(new_owner)
    save_owners(owners)
    return new_owner


def remove_owner(name_or_id: str) -> dict | None:
    """Remove an owner. Returns the removed entry or None.
    Also clears the owner_id on any reps assigned to them."""
    owners = load_owners()
    norm = _normalize(name_or_id)
    target = None
    for o in owners:
        if (
            o.get("id") == name_or_id
            or _normalize(o.get("name", "")) == norm
        ):
            target = o
            break
    if not target:
        return None
    owners = [o for o in owners if o is not target]
    save_owners(owners)

    # Clear from any reps
    reps = load_reps()
    cleared = 0
    for uid, rep in reps.items():
        if rep.get("owner_id") == target["id"]:
            rep["owner_id"] = None
            rep["owner_cleared_at"] = datetime.now().isoformat()
            cleared += 1
    if cleared:
        save_reps(reps)
    target["reps_cleared"] = cleared
    return target


def merge_owners(source_name: str, target_name: str) -> bool:
    """Merge source into target. All reps under source get reassigned to target."""
    owners = load_owners()
    source = next((o for o in owners if _normalize(o.get("name", "")) == _normalize(source_name)), None)
    target = next((o for o in owners if _normalize(o.get("name", "")) == _normalize(target_name)), None)
    if not source or not target or source["id"] == target["id"]:
        return False
    # Reassign reps
    reps = load_reps()
    for uid, rep in reps.items():
        if rep.get("owner_id") == source["id"]:
            rep["owner_id"] = target["id"]
            rep["merged_from"] = source["id"]
    save_reps(reps)
    # Remove source
    owners = [o for o in owners if o is not source]
    # Add source's aliases to target so future lookups still work
    target.setdefault("aliases", []).append(source["name"].lower())
    save_owners(owners)
    return True


# ---------- Rep mutations ----------

def get_rep(user_id: str) -> dict | None:
    return load_reps().get(user_id)


def has_owner(user_id: str) -> bool:
    rep = get_rep(user_id)
    return bool(rep and rep.get("owner_id"))


def set_rep_owner(user_id: str, owner_id: str, first_name: str = "", last_name: str = "",
                   source: str = "self_reported") -> dict:
    reps = load_reps()
    rep = reps.get(user_id, {})
    if first_name:
        rep["first_name"] = first_name
    if last_name:
        rep["last_name"] = last_name
    rep["owner_id"] = owner_id
    rep["set_at"] = datetime.now().isoformat()
    rep["source"] = source
    reps[user_id] = rep
    save_reps(reps)
    return rep


def set_rep_terminated(user_id: str, terminated: bool = True) -> dict | None:
    """Mark a rep terminated (retired) or reinstate them. Terminated reps are
    excluded from the scorecard + leaderboards. Returns the rep dict, or None
    if there's no rep with that user_id."""
    if not user_id:
        return None
    reps = load_reps()
    # Create a minimal entry if the rep isn't on the roster yet — reps can submit
    # (and appear on the scorecard) without ever being assigned an owner, and
    # those still need to be retire-able.
    rep = reps.get(user_id) or {}
    if terminated:
        rep["terminated"] = True
        rep["terminated_at"] = datetime.now().isoformat()
    else:
        rep.pop("terminated", None)
        rep.pop("terminated_at", None)
    reps[user_id] = rep
    save_reps(reps)
    return rep


def is_terminated(user_id: str) -> bool:
    return bool((get_rep(user_id) or {}).get("terminated"))


def reinstate_and_reset(user_id: str, from_ts: str) -> dict | None:
    """A retired rep just submitted again — put them back on the scorecard but
    RESET their numbers. `count_from` makes the scorecard ignore everything
    before this point, so they start over at their new first submission."""
    if not user_id:
        return None
    reps = load_reps()
    rep = reps.get(user_id) or {}
    rep.pop("terminated", None)
    rep.pop("terminated_at", None)
    rep["count_from"] = from_ts or datetime.now().isoformat()
    rep["reinstated_at"] = datetime.now().isoformat()
    reps[user_id] = rep
    save_reps(reps)
    return rep


def resurrect_rep(user_id: str) -> dict | None:
    """Undo an accidental retirement — bring the rep back with ALL their prior
    data intact (clears terminated AND any reset window, so full history counts
    again). Different from reinstate_and_reset, which starts them over at 1."""
    if not user_id:
        return None
    reps = load_reps()
    rep = reps.get(user_id)
    if rep is None:
        return None
    rep.pop("terminated", None)
    rep.pop("terminated_at", None)
    rep.pop("count_from", None)   # restore their full submission history
    reps[user_id] = rep
    save_reps(reps)
    return rep


def find_rep_by_name(query: str) -> tuple[str | None, dict | None, float]:
    """Find a rep by their first/last name (fuzzy). Returns (user_id, rep_dict, score)."""
    reps = load_reps()
    q_norm = _normalize(query)
    best_uid, best_rep, best_score = None, None, 0.0
    for uid, rep in reps.items():
        full = f"{rep.get('first_name', '')} {rep.get('last_name', '')}".strip()
        if not full:
            continue
        sim = _similarity(q_norm, full)
        if q_norm in _normalize(full):
            sim = max(sim, 0.9)
        if sim > best_score:
            best_uid, best_rep, best_score = uid, rep, sim
    if best_score >= FUZZY_THRESHOLD:
        return best_uid, best_rep, best_score
    return None, None, best_score


def owner_name(owner_id: str) -> str:
    owners = load_owners()
    for o in owners:
        if o.get("id") == owner_id:
            return o.get("name", owner_id)
    return owner_id
