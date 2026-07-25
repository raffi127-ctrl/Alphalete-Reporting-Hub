"""The shape of one tracker-onboarded office and the tracker catalog.

Pure data + rules (no network), shared by the form (app.py) and the apply CLI.
An office here = a Slack channel + an ORDERED set of tracker ids to post there.
The trackers themselves are org-wide boards defined in tableau_screenshots.pages,
so nothing per-office needs cloning — this is channel + selection + order only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


def tracker_catalog() -> "List[dict]":
    """[{id, title, emoji, opt_in}] from tableau_screenshots.pages. Empty list if
    the import fails (the form then shows a warning rather than crashing)."""
    try:
        from automations.tableau_screenshots import pages as P
        return [{"id": p["id"], "title": p.get("title", p["id"]),
                 "emoji": p.get("emoji", ""), "opt_in": bool(p.get("opt_in_only"))}
                for p in P.PAGES]
    except Exception:
        return []


def default_selection() -> "List[str]":
    """Tracker ids checked by default — every non-opt-in tracker, in catalog
    order (matches tableau_screenshots.pages.default_ids)."""
    return [t["id"] for t in tracker_catalog() if not t["opt_in"]]


@dataclass
class TrackerRecord:
    key: str                       # org key, e.g. "aeon" (unique CLI/dict handle)
    channel_id: str                # Slack channel id (C...)
    channel_name: str              # "#aeon-sales" — becomes ORG_LABEL (display)
    trackers: List[str] = field(default_factory=list)   # ordered tracker ids
    owner: str = ""                # office/owner name (identity + audit)
    submitted_at: str = ""
    submitted_by: str = ""

    def label(self) -> str:
        return self.channel_name.strip() or self.key

    def to_json(self) -> dict:
        d = asdict(self)
        d["_derived"] = {"label": self.label(), "n_trackers": len(self.trackers)}
        return d


def slug_from(name: str) -> str:
    """First word, lowercased, a-z0-9 only — the conventional org key."""
    first = (name or "").strip().split()[0] if (name or "").strip() else ""
    return re.sub(r"[^a-z0-9]", "", first.lower())


def validate(rec: TrackerRecord, *,
             existing_keys: "Optional[List[str]]" = None,
             existing_channels: "Optional[Dict[str, str]]" = None) -> "List[str]":
    """[] when safe to wire, else problems. A duplicate channel is the mistake
    that double-posts one office's feed, so channels must be unique across orgs."""
    existing_keys = existing_keys or []
    existing_channels = existing_channels or {}
    problems: List[str] = []

    if not rec.key.strip():
        problems.append("Office key is empty.")
    elif not re.match(r"^[a-z0-9_]+$", rec.key):
        problems.append(f"Office key {rec.key!r} must be lowercase letters/digits/"
                        "underscore only.")
    if rec.key in existing_keys:
        problems.append(f"Office key {rec.key!r} already posts trackers — pick a "
                        "unique handle.")
    if not rec.channel_id.strip():
        problems.append("Slack channel id is empty.")
    elif rec.channel_id in existing_channels:
        problems.append(f"Channel {rec.channel_id} ({rec.channel_name}) already "
                        f"posts trackers as {existing_channels[rec.channel_id]!r} "
                        "— it would double-post. Use a different channel.")
    if not rec.channel_name.strip():
        problems.append("Channel name is empty.")
    if not rec.trackers:
        problems.append("No trackers selected — check at least one.")
    known = {t["id"] for t in tracker_catalog()}
    if known:
        for tid in rec.trackers:
            if tid not in known:
                problems.append(f"Unknown tracker id {tid!r}.")
    return problems
