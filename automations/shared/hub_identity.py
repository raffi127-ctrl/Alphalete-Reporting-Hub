"""Friendly names for Hub change-notification emails.

Two lookups:
  • git_author()  — map a commit's git identity to a team name
                    (raffi127-ctrl / raffi127@gmail.com → Megan).
  • machine_name() — this runner's profile name ("Lucy 1" = the mini), from the
                    same .machine-profile marker mini_control uses, so the
                    emails match how the team refers to the machines.

Both are best-effort and fall back to the raw value, so an unknown author/host
still shows *something* rather than blank.
"""
from __future__ import annotations

import socket
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

# git author name OR email (lower-cased) → friendly team name. Extend as more
# people's git identities are learned.
_GIT_AUTHOR_ALIASES = {
    "raffi127-ctrl": "Megan",
    "raffi127@gmail.com": "Megan",
    "raffi127": "Megan",
}


def git_author(name: str, email: str = "") -> str:
    """Friendly name for a git identity; falls back to the raw name/email."""
    for key in (name, email):
        alias = _GIT_AUTHOR_ALIASES.get((key or "").strip().lower())
        if alias:
            return alias
    return (name or email or "someone").strip()


def machine_name() -> str:
    """This runner's profile name ('Lucy 1' = the mini / 'Lucy 2'), from the
    gitignored .machine-profile marker. Falls back to the raw hostname if the
    marker is absent (so a non-runner machine isn't mislabeled 'Lucy 1')."""
    try:
        v = (_REPO_ROOT / ".machine-profile").read_text().strip()
        if v:
            return v
    except Exception:
        pass
    try:
        return socket.gethostname()
    except Exception:
        return "this machine"
