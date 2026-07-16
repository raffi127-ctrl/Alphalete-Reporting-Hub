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
# people's git identities are learned. Matched against both the commit author
# name and email, so keying on the stable name is usually enough.
_GIT_AUTHOR_ALIASES = {
    # Megan
    "raffi127-ctrl": "Megan",
    "raffi127@gmail.com": "Megan",
    "raffi127": "Megan",
    # Carlos
    "carlos hidalgo": "Carlos",
    # Dylan
    "dylan twaddle": "Dylan",
    "dylanjtwaddle@gmail.com": "Dylan",
    # JD
    "jd mascorro": "JD",
    # Eve — the VA who commits report work under the alphaletereporting account
    # (Megan confirmed 2026-07-15; alphaletereporting@gmail.com is Eve's in the
    # Hub roster). Keyed on the GitHub identity, not the shared gmail address.
    "alphaletereporting-ej": "Eve",
    "alphaletereporting-ej@users.noreply.github.com": "Eve",
    # Maud — hasn't committed yet; pre-mapped so her first push is named right,
    # matched on either her git name or her email (maudmiller4@gmail.com).
    "maud miller": "Maud",
    "maudmiller4@gmail.com": "Maud",
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
