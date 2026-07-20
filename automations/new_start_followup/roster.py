"""Leader roster: OBCL name <-> Slack ID <-> phone number.

Three name-spaces have to line up and none of them agree:
  OBCL column B   "Elijah Rodriguez", "rhea mckee", "Tadana Manyangadze"
  Slack           Eli Rodriguez, Rhea McKee, Tadana Jeti
  Raf's checklist "Eli", "Rhea", "Tadana"

Lucy's Slack user token has no `users:read` scope, so a scheduled run CANNOT
look names up live -- the mapping has to be on disk. leaders.json is that file;
add a leader there when a new one starts running 2nd rounds.

Phone numbers are NOT in this file and must never be committed to it -- the repo
is public on GitHub. They live in a machine-local, gitignored overlay:

    ~/.config/recruiting-report/new-start-leader-phones.json
    { "U0B4RUR83J9": "+12145551234", ... }

`load()` merges that overlay on top of the roster, so the code reads
`leader.phone` the same either way. On a machine without the overlay every phone
is blank and the texting step reports "no number on file" instead of silently
skipping people.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

ROSTER_PATH = Path(__file__).resolve().parent / "leaders.json"

# Machine-local, gitignored. Personal numbers stay off GitHub.
PHONES_PATH = Path(
    os.environ.get("NSF_PHONES_PATH")
    or (Path.home() / ".config" / "recruiting-report" / "new-start-leader-phones.json")
)


def _norm(name: str) -> str:
    """Casefold + collapse whitespace + drop punctuation, so 'Rhea McKee',
    'rhea mckee' and 'Rhea  Mc Kee' all land on the same key."""
    s = re.sub(r"[^a-z0-9 ]+", "", (name or "").lower())
    return re.sub(r"\s+", " ", s).strip()


class Leader:
    def __init__(self, slack_id: str, name: str, short: str = "",
                 obcl_names: Optional[List[str]] = None, phone: str = ""):
        self.slack_id = slack_id
        self.name = name
        self.short = short or _short_from(name)
        self.obcl_names = obcl_names or []
        self.phone = phone

    @property
    def mention(self) -> str:
        return "<@{}>".format(self.slack_id)

    def keys(self) -> List[str]:
        """Every normalized name this leader answers to."""
        return [_norm(n) for n in [self.name] + list(self.obcl_names) if n]

    def to_dict(self) -> dict:
        return {
            "slack_id": self.slack_id,
            "name": self.name,
            "short": self.short,
            "obcl_names": self.obcl_names,
            "phone": self.phone,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Leader({!r}, {!r})".format(self.name, self.slack_id)


def _short_from(name: str) -> str:
    """'Kaleb Muvunyi' -> 'Kaleb M' -- how Raf writes the checklist."""
    parts = (name or "").split()
    if len(parts) < 2:
        return name or ""
    return "{} {}".format(parts[0], parts[-1][0])


class Roster:
    def __init__(self, leaders: List[Leader]):
        self.leaders = leaders
        self._by_id = {l.slack_id: l for l in leaders}
        self._by_name = {}  # type: Dict[str, Leader]
        for l in leaders:
            for k in l.keys():
                self._by_name.setdefault(k, l)

    def by_id(self, slack_id: str) -> Optional[Leader]:
        return self._by_id.get(slack_id)

    def by_obcl_name(self, name: str) -> Optional[Leader]:
        """Exact/alias match, then first-name + last-initial.

        The loose pass is what catches OBCL's free-text drift ('Andrew Sanborn
        Roadtrip', 'Rashad'), but it only fires when exactly one leader matches
        -- an ambiguous hit is reported as unmatched rather than guessed at.
        """
        key = _norm(name)
        if not key:
            return None
        hit = self._by_name.get(key)
        if hit:
            return hit

        parts = key.split()
        first = parts[0]
        initial = parts[-1][0] if len(parts) > 1 else ""
        loose = []
        for l in self.leaders:
            for k in l.keys():
                kp = k.split()
                if not kp or kp[0] != first:
                    continue
                if initial and len(kp) > 1 and kp[-1][0] != initial:
                    continue
                loose.append(l)
                break
        uniq = {l.slack_id: l for l in loose}
        if len(uniq) == 1:
            return list(uniq.values())[0]
        return None


def load(path: Optional[Path] = None) -> Roster:
    path = path or ROSTER_PATH
    if not path.exists():
        raise RuntimeError(
            "Leader roster missing at {}. Build it with "
            "`python -m automations.new_start_followup.build_roster`.".format(path)
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    fields = ("slack_id", "name", "short", "obcl_names", "phone")
    # Ignore any extra keys -- entries carry free-text `_note`/`_alias_note`
    # comments for whoever edits the file by hand.
    leaders = [
        Leader(**{k: v for k, v in e.items() if k in fields})
        for e in raw.get("leaders", [])
    ]
    phones = load_phones()
    for leader in leaders:
        if not leader.phone and leader.slack_id in phones:
            leader.phone = phones[leader.slack_id]
    return Roster(leaders)


def load_phones(path: Optional[Path] = None) -> Dict[str, str]:
    """slack_id -> E.164 from the machine-local overlay. {} if absent."""
    path = path or PHONES_PATH
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_") and v}


def save_phones(phones: Dict[str, str], path: Optional[Path] = None) -> Path:
    """Write the local phone overlay. Never goes near leaders.json / git."""
    path = path or PHONES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    body = dict(phones)
    body["_note"] = (
        "Leader phone numbers for the New-Start Follow-Up texts. Machine-local "
        "on purpose: the repo is PUBLIC, so these must never be committed. "
        "Regenerate with: python -m automations.new_start_followup.contacts --write"
    )
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)  # personal numbers -- owner-only
    except OSError:
        pass
    return path


def save(leaders: List[Leader], path: Optional[Path] = None) -> None:
    path = path or ROSTER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "_note": (
            "Leader roster for the New-Start Follow-Up report. Add a leader here "
            "when someone new starts running 2nd-round interviews. 'obcl_names' "
            "holds every spelling that shows up in OBCL column B. 'phone' is "
            "E.164 (+15551234567) and is only used for the Sunday texts."
        ),
        "leaders": [l.to_dict() for l in sorted(leaders, key=lambda x: x.name.lower())],
    }
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
