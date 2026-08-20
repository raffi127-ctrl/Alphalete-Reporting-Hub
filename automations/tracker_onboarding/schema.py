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
    channel_id: str                # PRIMARY Slack channel id (C...)
    channel_name: str              # "#aeon-sales" — becomes ORG_LABEL (display)
    trackers: List[str] = field(default_factory=list)   # ordered tracker ids
    owner: str = ""                # ICD name as in OwnerVille (identity + key)
    submitted_at: str = ""
    submitted_by: str = ""
    # Self-serve flow: an ICD's own submission lands as "pending" and is NEVER
    # wired until Megan confirms it (which flips it to "wired"). Legacy rows
    # (pre-self-serve) have status "" and are treated as confirmed.
    status: str = ""               # "" (legacy/confirmed) | "pending" | "wired"
    requested_by: str = ""         # who filled the form (the ICD's name)
    # The same boards can post to MORE channels than the primary one — the
    # daily run already loops a per-org channel_ids LIST, so extra channels
    # ride along with no poster change. [{"channel_id": .., "channel_name": ..}]
    extra_channels: List[Dict[str, str]] = field(default_factory=list)

    def channel_pairs(self) -> "List[tuple]":
        """[(channel_id, channel_name), ...] — primary first, extras after."""
        out = [(self.channel_id, self.channel_name)]
        for c in self.extra_channels:
            out.append((c.get("channel_id", ""), c.get("channel_name", "")))
        return out

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


def validate_request(rec: TrackerRecord, *,
                     existing_keys: "Optional[List[str]]" = None) -> "List[str]":
    """Lighter check for an ICD's self-serve REQUEST (before Megan confirms).
    The channel id may still be missing/wrong — Megan fixes it at confirm — but
    identity, channel name and at least one (universal) tracker are required."""
    existing_keys = existing_keys or []
    problems: List[str] = []
    if not rec.owner.strip():
        problems.append("Please enter your ICD name as it appears in OwnerVille.")
    if not rec.key.strip():
        problems.append("Couldn't make an office id from that name — "
                        "please use your real OwnerVille name.")
    elif rec.key in existing_keys:
        problems.append("An office under that name already gets the daily "
                        "trackers. If something about it needs to change, "
                        "message Megan Hidalgo instead of re-submitting.")
    seen_names = set()
    for i, (_cid, cname) in enumerate(rec.channel_pairs()):
        tag = "" if i == 0 else f" (channel {i + 1})"
        low = cname.strip().lstrip("#").lower()
        if not low:
            problems.append(f"Please enter the Slack channel's name{tag}.")
        elif low in seen_names:
            problems.append(f"Channel {cname} is listed twice — each channel "
                            "only needs to be entered once.")
        seen_names.add(low)
    if not rec.trackers:
        problems.append("Pick at least one tracker board.")
    cat = tracker_catalog()
    known = {t["id"] for t in cat}
    opt_in = {t["id"] for t in cat if t.get("opt_in")}
    if known:
        for tid in rec.trackers:
            if tid not in known or tid in opt_in:
                problems.append(f"Tracker {tid!r} isn't available on this form.")
    return problems


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
    seen_ids: set = set()
    for i, (cid, cname) in enumerate(rec.channel_pairs()):
        tag = "" if i == 0 else f" (channel {i + 1})"
        if not cid.strip():
            problems.append(f"Slack channel id is empty{tag}.")
        elif cid in seen_ids:
            problems.append(f"Channel {cid} ({cname}) is listed twice — it "
                            "would double-post.")
        elif cid in existing_channels:
            problems.append(f"Channel {cid} ({cname}) already "
                            f"posts trackers as {existing_channels[cid]!r} "
                            "— it would double-post. Use a different channel.")
        seen_ids.add(cid)
        if not cname.strip():
            problems.append(f"Channel name is empty{tag}.")
    if not rec.trackers:
        problems.append("No trackers selected — check at least one.")
    cat = tracker_catalog()
    known = {t["id"] for t in cat}
    # Owner-scoped / opt-in boards are hardcoded to one owner's Tableau view and
    # would post THAT owner's numbers into this office's channel (the jamis→Atef
    # isolation failure, 2026-08-01). They are never a valid per-office enrollment
    # — per-office rankings come through b2b_metrics, which slices by owner.
    opt_in = {t["id"] for t in cat if t.get("opt_in")}
    if known:
        for tid in rec.trackers:
            if tid not in known:
                problems.append(f"Unknown tracker id {tid!r}.")
            elif tid in opt_in:
                problems.append(f"Tracker {tid!r} is owner-scoped (opt-in) and "
                                "can't be enrolled per office — it would post "
                                "another owner's numbers. It's excluded on "
                                "purpose; that office gets its own ranking via "
                                "its metrics thread.")
    return problems
