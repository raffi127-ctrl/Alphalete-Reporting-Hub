"""Generate AppStream (ApplicantStream) logins for the team.

We are moving off ONE shared account (rcaptain) onto one login per person, so
every action in AppStream is attributable. Security bar is low on purpose:
these passwords exist to TRACK who did what, not to guard money — so they are
easy to read out loud, type on a phone, and re-say over the phone.

Usage:
    python -m automations.shared.appstream_provision "Raf Hidalgo" "Carlos ..."
    python -m automations.shared.appstream_provision --file names.txt

Writes output/appstream-new-users-<date>.md (a table to work from) and a
matching .csv. Prints the same table. Creating the accounts in the AppStream
admin console is a human step — this only produces the credentials to paste.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import re
import secrets
import sys
import unicodedata
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_OUT = _ROOT / "output"

# Five-letter words, unambiguous, no lookalikes and nothing embarrassing. One
# word + four digits is the whole password: Megan's format, chosen so it fits on
# a sticky note and survives being read out over the phone.
_WORDS = [
    "amber", "anvil", "apple", "arrow", "aspen", "badge", "basin", "beach",
    "berry", "birch", "bison", "blaze", "block", "brick", "brush", "cabin",
    "cedar", "chalk", "chart", "cider", "clamp", "cliff", "cloud", "coast",
    "cocoa", "comet", "coral", "crane", "crest", "delta", "denim", "diner",
    "ditch", "drift", "eagle", "ember", "fable", "fence", "fern", "field",
    "flint", "flute", "focus", "forge", "frost", "glade", "globe", "grape",
    "grove", "harbor", "hazel", "heron", "hotel", "ivory", "jewel", "joker",
    "kayak", "knoll", "lakes", "lance", "large", "laurel", "ledge", "lemon",
    "linen", "lodge", "lunar", "maple", "march", "marsh", "medal", "melon",
    "mesa", "metal", "mocha", "motor", "mount", "nickel", "night", "noble",
    "north", "novel", "oasis", "ocean", "olive", "onyx", "opal", "orbit",
    "otter", "paint", "panel", "party", "patio", "pearl", "pedal", "pilot",
    "plaza", "porch", "prism", "quart", "quest", "quill", "quilt", "radar",
    "rally", "ranch", "raven", "relay", "ridge", "rider", "river", "robin",
    "rocket", "rodeo", "rover", "royal", "salad", "sandy", "scout", "shore",
    "siren", "skate", "slate", "smoke", "solar", "spark", "spice", "spine",
    "spoke", "sport", "stage", "stamp", "steam", "stone", "storm", "study",
    "sugar", "sunny", "swift", "table", "tempo", "tenor", "thorn", "tiger",
    "timer", "title", "toast", "token", "torch", "tower", "track", "trail",
    "train", "trend", "tulip", "tunnel", "ultra", "unity", "vapor", "vault",
    "vinyl", "vivid", "vocal", "voice", "wagon", "waltz", "watch", "water",
    "wheat", "wheel", "whale", "willow", "winds", "witty", "woven", "yacht",
    "yield", "young", "zebra", "zesty",
]
_WORDS = sorted({w for w in _WORDS if len(w) == 5})


def make_password() -> str:
    """One capitalized 5-letter word + 4 digits, e.g. 'Maple4827'.

    No separators (Megan 2026-08-30): dashes get lost when a password is read
    aloud or retyped on a phone. Low bar on purpose — these logins exist so
    AppStream actions are attributable, not to guard anything valuable."""
    word = secrets.choice(_WORDS).capitalize()
    return f"{word}{secrets.randbelow(9000) + 1000}"


def _ascii(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def make_username(full_name: str, taken: set[str]) -> str:
    """first-initial + last name, ascii-only, capitalized: 'Raf Hidalgo' -> Rhidalgo.

    Capitalized because Megan wants them that way and AppStream already carries
    a mixed-case account (CarlosNLR). Collision checks stay lowercase so 'Raf'
    and 'raf' can never both be handed out as separate logins."""
    parts = [p for p in re.split(r"\s+", _ascii(full_name).strip()) if p]
    if not parts:
        raise ValueError("empty name")
    if len(parts) == 1:
        base = re.sub(r"[^a-z]", "", parts[0].lower())
    else:
        base = re.sub(r"[^a-z]", "", (parts[0][0] + parts[-1]).lower())
    user = base
    if user in taken and len(parts) > 2:
        user = re.sub(r"[^a-z]", "", (parts[0][0] + parts[1][0] + parts[-1]).lower())
    n = 2
    while user in taken:
        user = f"{base}{n}"
        n += 1
    taken.add(user)
    return user.capitalize()


def build(names: list[str]) -> list[dict]:
    """Each entry is a full name, or "Display Name=username" when the derived
    username would read badly — service accounts, mainly: the Lucy bots want
    'lucyreports', not the first-initial+last-name shape people get."""
    taken: set[str] = set()
    rows = []
    for raw in names:
        display, _, forced = raw.partition("=")
        name = " ".join(display.split())
        forced = forced.strip()
        if not name:
            continue
        if forced:
            taken.add(forced.lower())
        rows.append({
            "name": name,
            "username": forced or make_username(name, taken),
            "password": make_password(),
        })
    return rows


def _table(rows: list[dict]) -> str:
    w_n = max([len(r["name"]) for r in rows] + [4])
    w_u = max([len(r["username"]) for r in rows] + [8])
    w_p = max([len(r["password"]) for r in rows] + [8])
    out = [f"| {'Name':<{w_n}} | {'Username':<{w_u}} | {'Password':<{w_p}} |",
           f"|{'-' * (w_n + 2)}|{'-' * (w_u + 2)}|{'-' * (w_p + 2)}|"]
    for r in rows:
        out.append(f"| {r['name']:<{w_n}} | {r['username']:<{w_u}} | "
                   f"{r['password']:<{w_p}} |")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("names", nargs="*", help="full names, quoted")
    ap.add_argument("--file", help="text file, one full name per line")
    ap.add_argument("--no-write", action="store_true",
                    help="print only, don't save to output/")
    args = ap.parse_args(argv)

    names = list(args.names)
    if args.file:
        names += [ln for ln in Path(args.file).read_text().splitlines() if ln.strip()]
    if not names:
        ap.error("give at least one name (or --file)")

    rows = build(names)
    table = _table(rows)
    print(table)

    if args.no_write:
        return 0

    _OUT.mkdir(exist_ok=True)
    stamp = _dt.date.today().isoformat()
    md = _OUT / f"appstream-new-users-{stamp}.md"
    md.write_text(
        f"# AppStream logins — {stamp}\n\n"
        "One login per person so AppStream actions are attributable. "
        "Passwords are low-security on purpose (tracking, not secrets).\n\n"
        f"{table}\n\n"
        "Next: create each user in the AppStream admin console, then have each "
        "person sign in once to confirm.\n"
    )
    csv_path = _OUT / f"appstream-new-users-{stamp}.csv"
    with csv_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["name", "username", "password"])
        w.writeheader()
        w.writerows(rows)

    print(f"\nSaved: {md.relative_to(_ROOT)}\n       {csv_path.relative_to(_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
