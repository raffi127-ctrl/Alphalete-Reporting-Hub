"""Flag birthdays that are probably wrong: Blue Ink date = start date.

WHY (Eve, 2026-11-24). Milagros Colon's birthday came off her Blue Ink I-9 as
08/17 -- her START date, not her birthday (it is 11/24). Lucy greeted nobody on
the real day. Same thing on 3 more rows that day (Hayden Wilson, Shacor Brown,
Priscilla Hernandez Ibarra): birthday MM/DD == start MM/DD. By chance that is
about 1 in 365 per person, so 4 of ~150 is the date-of-birth field being filled
with the hire/signing date, not 4 coincidences.

What this does: every run, rows whose birthday equals their start date are
posted ONCE to #claudecorrections-and-requests (the channel every report alert
goes to), so somebody types the real birthday into 'DOB LUCY'. It does NOT hold
the greeting and does NOT change the tab -- a person fixes the date.

If a rep really was hired on their birthday, typing "confirmed" in that row's
Notes stops the flag.

Posted in English (team channel), as Lucy, @-mentioning Evelyn (Eve, 2026-11-24:
"que me etiquete a mi").
"""
from __future__ import annotations

from pathlib import Path

from automations.birthday_reminders import config as C

CHANNEL = "C0BK5PRG259"   # #claudecorrections-and-requests
EVELYN = "U088E2KJEV8"     # Evelyn (Eve) Sobrino -- resources/owner-slack-ids.md
CONFIRM_WORD = "confirmed"
STATE = (Path(__file__).resolve().parents[2] / "output" / "birthday_reminders"
         / "suspect_alerted.txt")


def _md(text: str):
    """'08/17' or '8/17/2026' -> (8, 17); None if it doesn't parse."""
    parts = str(text or "").strip().split("/")
    try:
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return None


def find(entries) -> list:
    """Rows whose birthday MM/DD is the same as their start date's MM/DD."""
    out = []
    for e in entries:
        if e.is_staff or e.opted_out:
            continue
        if CONFIRM_WORD in (e.notes or "").lower():
            continue
        b, s = _md(e.mmdd), _md(e.start)
        if b and s and b == s:
            out.append(e)
    return out


def _key(e) -> str:
    # Name + the date we flagged: if somebody "fixes" it to another wrong
    # date that still matches the start date, that's a new flag.
    return "%s|%s" % (e.key, e.mmdd.strip())


def _seen() -> set:
    try:
        return {l.strip() for l in STATE.read_text(encoding="utf-8").splitlines()
                if l.strip()}
    except OSError:
        return set()


def compose(rows) -> str:
    lines = ["<@%s> :warning: Birthday check -- %d birthday(s) in Blue Ink are the "
             "same as the rep's start date, so they're probably wrong:" % (EVELYN, len(rows))]
    for e in rows:
        lines.append("\u2022 %s -- birthday %s, started %s" % (e.name, e.mmdd, e.start))
    lines.append("Fix: type the real birthday (MM/DD) in 'All in One Local Office "
                 "- Raf' \u2192 '%s' \u2192 '%s'. If it really is the same day, "
                 "type \"%s\" in Notes." % (C.STORE_TAB, C.COL_MMDD, CONFIRM_WORD))
    return "\n".join(lines)


def alert(entries, *, dry_run: bool, logfn=print) -> list:
    """Post the NEW suspects once. Returns the rows that were (or would be) posted.
    Never raises: a flag must never cost a birthday we do have."""
    rows = find(entries)
    if not rows:
        return []
    seen = _seen()
    new = [e for e in rows if _key(e) not in seen]
    for e in rows:
        logfn("  check %s -- birthday %s = start date %s%s"
              % (e.name, e.mmdd, e.start, "" if e in new else " (already flagged)"))
    if not new:
        return []
    text = compose(new)
    if dry_run:
        logfn("  (dry run) would post to %s:\n%s" % (CHANNEL, text))
        return new
    try:
        from automations.shared import slack_metrics_post as SM
        SM._client().chat_postMessage(channel=CHANNEL, text=text)
    except Exception as e:  # noqa: BLE001
        logfn("\u26a0 couldn't post the birthday check: %s" % str(e)[:200])
        return []
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        with STATE.open("a", encoding="utf-8") as f:
            for e in new:
                f.write(_key(e) + "\n")
    except OSError:
        pass
    logfn("  posted the birthday check for %d rep(s)" % len(new))
    return new
