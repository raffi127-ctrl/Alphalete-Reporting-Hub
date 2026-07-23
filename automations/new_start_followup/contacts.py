"""PARKED 2026-07-22 — texting is off (no active iMessage number). Unwired from
the registry; kept for when/if a number is added. See texts.py.

Fill leader phone numbers from the macOS Contacts app. RUN ON LUCY 1.

Raf keeps the leaders' numbers in Contacts on Lucy 1 (the mini) -- they aren't
in OBCL, and Slack profiles don't carry a phone. So this reads Contacts once and
caches what it finds.

Cached on purpose, not looked up per run: reaching Contacts needs macOS
automation permission (TCC), and a launchd job that trips a TCC prompt just
hangs -- there's nobody at the mini to click Allow. Resolving once, by hand,
keeps every scheduled run a pure Sheets+Slack job.

Numbers are written to the machine-local, gitignored overlay
(`roster.PHONES_PATH`), NOT to leaders.json -- **this repo is public on GitHub**
and these are personal phone numbers.

    # on Lucy 1, see what it would fill in (no writes)
    python -m automations.new_start_followup.contacts

    # actually save the numbers locally
    python -m automations.new_start_followup.contacts --write

Anything it can't match is listed, not guessed at -- texting a wrong number is
worse than texting nobody.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

from automations.new_start_followup import roster as roster_mod
from automations.swag_welcome.roster import normalize_phone, pretty_phone

# Field/record separators unlikely to show up in a contact name or number.
_FS = "\x1f"
_RS = "\x1e"

_DUMP_SCRIPT = """
tell application "Contacts"
    set out to ""
    repeat with p in people
        set nm to name of p
        repeat with ph in phones of p
            set out to out & nm & "{fs}" & (value of ph) & "{rs}"
        end repeat
    end repeat
    return out
end tell
""".format(fs=_FS, rs=_RS)


class ContactsError(RuntimeError):
    pass


def dump_contacts(timeout: int = 120) -> List[Tuple[str, str]]:
    """Every (name, phone) pair in Contacts, in one osascript call.

    One dump beats a query per leader: it's a single permission surface and it
    lets the matching happen in Python where the alias rules already live.
    """
    if sys.platform != "darwin":
        raise ContactsError("Contacts is macOS-only; run this on Lucy 1.")
    try:
        proc = subprocess.run(
            ["osascript", "-e", _DUMP_SCRIPT],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise ContactsError("Contacts didn't respond in {}s.".format(timeout))

    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        if "-1743" in err or "Not authorized" in err:
            raise ContactsError(
                "Not authorized to read Contacts. On Lucy 1, grant the terminal "
                "(or whatever runs this) access under System Settings → Privacy "
                "& Security → Automation → Contacts, then re-run. Raw: " + err
            )
        raise ContactsError("osascript failed: " + (err or "no stderr"))

    pairs = []
    for record in proc.stdout.split(_RS):
        if _FS not in record:
            continue
        name, phone = record.split(_FS, 1)
        name, phone = name.strip(), phone.strip()
        if name and phone:
            pairs.append((name, phone))
    return pairs


def match(leaders, pairs: List[Tuple[str, str]]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """-> (found: slack_id -> E.164, problems: leader name -> why).

    A leader is only filled when the contact name matches one of the spellings
    already in leaders.json AND exactly one distinct number comes back. Two
    different numbers under the same name is ambiguous, so it's reported.
    """
    by_key = {}  # type: Dict[str, List[str]]
    for name, phone in pairs:
        by_key.setdefault(roster_mod._norm(name), []).append(phone)

    found = {}      # type: Dict[str, str]
    problems = {}   # type: Dict[str, str]

    for leader in leaders:
        if leader.phone:
            continue  # already cached; never overwrite a number by hand
        hits = []  # type: List[str]
        for key in leader.keys():
            hits.extend(by_key.get(key, []))
        if not hits:
            problems[leader.name] = "no Contacts entry"
            continue

        numbers = []
        bad = None
        for raw in hits:
            e164, warn = normalize_phone(raw)
            if e164 and e164 not in numbers:
                numbers.append(e164)
            elif warn and not e164:
                bad = warn
        if not numbers:
            problems[leader.name] = bad or "no usable number"
        elif len(numbers) > 1:
            problems[leader.name] = "ambiguous — {} numbers: {}".format(
                len(numbers), ", ".join(pretty_phone(n) for n in numbers))
        else:
            found[leader.slack_id] = numbers[0]
    return found, problems


def fill(write: bool = False) -> int:
    ros = roster_mod.load()
    already = [l for l in ros.leaders if l.phone]
    print("Roster: {} leaders · {} already have a number".format(
        len(ros.leaders), len(already)))

    pairs = dump_contacts()
    print("Contacts: {} name/number pairs".format(len(pairs)))
    print()

    found, problems = match(ros.leaders, pairs)

    if found:
        print("MATCHED ({}):".format(len(found)))
        for leader in ros.leaders:
            if leader.slack_id in found:
                print("   {:<20} {}".format(
                    leader.short or leader.name, pretty_phone(found[leader.slack_id])))
    if problems:
        print()
        print("NOT FILLED ({}) — add by hand to {}:".format(
            len(problems), roster_mod.PHONES_PATH))
        for name in sorted(problems):
            print("   {:<20} {}".format(name, problems[name]))

    if not write:
        print()
        print("[dry-run] nothing saved. Re-run with --write to store them.")
        return 0

    # Merge over whatever is already cached, so a re-run can't drop numbers
    # that were filled in by hand.
    phones = roster_mod.load_phones()
    phones.update(found)
    path = roster_mod.save_phones(phones)
    print()
    print("Wrote {} number(s) into {}".format(len(found), path))
    print("(machine-local + gitignored — the repo is public, these never get committed)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Fill leader phone numbers from macOS Contacts (run on Lucy 1).")
    ap.add_argument("--write", action="store_true",
                    help="save the matched numbers into leaders.json")
    args = ap.parse_args(argv)
    try:
        return fill(write=args.write)
    except ContactsError as exc:
        print("INCOMPLETE — {}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
