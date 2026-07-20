"""Leader roster: OBCL name <-> Slack ID <-> phone number.

Three name-spaces have to line up and none of them agree:
  OBCL column B   "Elijah Rodriguez", "rhea mckee", "Tadana Manyangadze"
  Slack           Eli Rodriguez, Rhea McKee, Tadana Jeti
  Raf's checklist "Eli", "Rhea", "Tadana"

Lucy's Slack user token has no `users:read` scope, so a scheduled run CANNOT
look names up live -- the mapping has to be on disk. leaders.json is that file;
add a leader there when a new one starts running 2nd rounds.

`phone` is only needed for the Sunday texts. Leave it blank and that leader is
reported as "no number on file" instead of being silently skipped.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

ROSTER_PATH = Path(__file__).resolve().parent / "leaders.json"


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
    return Roster([
        Leader(**{k: v for k, v in e.items() if k in fields})
        for e in raw.get("leaders", [])
    ])


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
