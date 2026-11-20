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


def _profile() -> str:
    """The .machine-profile name ('Lucy 1' ...), or '' when there is none."""
    try:
        return (_REPO_ROOT / ".machine-profile").read_text().strip()
    except Exception:
        return ""


def activity_machine() -> str:
    """What a run writes into the Hub Activity log's Machine column:
    'Mac.attlocal.net [Lucy 1]' -- the hostname, then the runner's profile name.

    WHY BOTH (2026-11-20). The AT&T router hands Lucy 1 AND Lucy 2 the same name,
    'Mac.attlocal.net'. The watcher had that name on its Lucy-2 list, so Lucy 1's
    3am DD harvest and its BG check failures were posted as "on Lucy 2", and the
    log searches for them came back empty on the wrong box. A hostname can't tell
    the two apart, but the profile marker can. The hostname stays first, so every
    substring match on it (machine_digest._ran_here, the --host lists) still hits.
    No marker = hostname alone, exactly as before."""
    try:
        host = socket.gethostname()
    except Exception:
        host = "this machine"
    prof = _profile()
    if prof and prof.lower() != host.lower():
        return "%s [%s]" % (host, prof)
    return host


def split_machine(value: str) -> tuple:
    """('Mac.attlocal.net', 'Lucy 1') from an Activity Machine value. Old rows
    with no tag come back as (value, '')."""
    v = (value or "").strip()
    if v.endswith("]") and " [" in v:
        host, _, tag = v[:-1].rpartition(" [")
        return host.strip(), tag.strip()
    return v, ""
