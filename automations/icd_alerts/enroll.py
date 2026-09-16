"""Enroll an office by typing their name. Everything else is derived.

    python -m automations.icd_alerts.enroll "Cyrus Wade"

WHY THIS EXISTS. Enrolling used to be four jobs done by hand: an entry in
offices.py, a matching entry in offices_public.json, a key on the 'Relay Keys'
tab, and a push -- and nothing kept the first two in step, so an office could
pass every check we had and then die on their own machine with "an office I do
not recognise". Megan, 2026-09-13: "That's a lot. there's got to be something
way simpler. Like I just add their name somewhere."

So: one name, one command. It mints the key, writes all three places, pushes
(the installer reads from GitHub, so an un-pushed office does not exist), and
prints the link to send them.

WHAT IT DELIBERATELY DOES NOT DECIDE:

  * THEIR SLACK ID. whois.py exists because a name match is a guess, and the
    cost of the wrong one is a DM to a stranger about a machine they do not
    own. If exactly one person matches, that is not a guess and it is used;
    anything else is left blank and printed for a person to settle.
  * WHERE THEIR ALERTS POST. The installer asks them and a human approves it.
    Nothing here routes an office into a room.
  * THEIR REAL HOURS. It fills the org default and says so. An owner who sells
    a different Saturday tells us, and `offices.py` is edited then -- a wrong
    default is visible and harmless, a wrong-looking prompt during setup is
    not.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import secrets
import subprocess
import sys
from typing import Dict, List, Optional

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
OFFICES_PY = HERE / "offices.py"
PUBLIC_JSON = HERE / "offices_public.json"

# The org default, and the only thing here anybody has to correct later.
DEFAULT_TZ = "America/Chicago"
DEFAULT_DAY = ("13:30", "20:30")
DEFAULT_SAT = ("10:45", "17:00")

KEY_GROUPS = 3
KEY_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no O/0, I/1 -- it gets read aloud


def office_key_for(name: str) -> str:
    """First name, lowercased. It becomes the prefix of their relay key, so it
    has to survive being typed into a terminal and read over a phone."""
    first = (name or "").strip().split()[0] if (name or "").strip() else ""
    return re.sub(r"[^a-z]", "", first.lower())


def mint_key(office_key: str) -> str:
    groups = ["".join(secrets.choice(KEY_CHARS) for _ in range(5))
              for _ in range(KEY_GROUPS)]
    return "%s-%s" % (office_key.upper(), "-".join(groups))


def label_for(name: str) -> str:
    first = (name or "").strip().split()[0]
    return "%s's Local Office" % first


def _hours(text: str, fallback) -> tuple:
    """'13:30-20:30' -> ('13:30', '20:30')."""
    if not text:
        return fallback
    m = re.match(r"^\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*$", text)
    if not m:
        raise SystemExit("Hours look like 13:30-20:30, not %r" % text)
    return (m.group(1), m.group(2))


def find_slack_id(name: str, log=print) -> str:
    """Exactly one match is a fact; anything else is a question for a person."""
    try:
        from automations.icd_alerts import whois
        needles = [p.lower() for p in name.split() if len(p) > 2]
        hits = whois.workspace(needles, log=lambda *a, **k: None)
    except Exception as e:  # noqa: BLE001 — Slack being slow must not block this
        log("  (could not search Slack: %s)" % type(e).__name__)
        return ""
    if len(hits) == 1:
        log("  Slack: %s (%s)" % (hits[0].get("id"), hits[0].get("name")))
        return hits[0].get("id") or ""
    if not hits:
        log("  Slack: nobody matched %r — nudges are off until you add an id" % name)
    else:
        log("  Slack: %d people match %r, so it is not obvious which:" % (len(hits), name))
        for h in hits[:6]:
            log("     %s  %s  %s" % (h.get("id"), h.get("name"), h.get("real")))
    log("     settle it with:  python -m automations.icd_alerts.whois \"%s\"" % name)
    return ""


def entry_text(key: str, owner: str, label: str, tz: str, slack_id: str,
               day, sat, saturday: bool, platform: str = "mac",
               hours_known: bool = False, campaign: str = "att") -> str:
    note = ("        # Their OWN hours, as they gave them on the sign-up form.\n"
            if hours_known else
            "        # Hours are the ORG DEFAULT, not this owner's own -- nobody\n"
            "        # has told us theirs yet. Correct them here when they do.\n")
    # WHAT AN OFFICE SELLS DECIDES WHAT CAN BE READ FOR THEM, so the row says
    # it out loud rather than leaning on the default. Written for the first
    # NDS office, 2026-09-16.
    camp = (
        '        campaign="%s",\n' % campaign if campaign != "att" else
        '        # AT&T fiber, which is also the default -- said plainly so the\n'
        '        # next person does not have to know what the default is.\n'
        '        campaign="att",\n')
    return (
        '    "%s": AlertOffice(\n'
        '        key="%s", owner="%s", label="%s",\n'
        '        # UNROUTED on purpose: the installer asks them where they want\n'
        '        # their alerts, and a human approves it. Nothing posts until then.\n'
        '        channels=(),\n'
        '        timezone="%s", active=True, platform="%s",\n'
        '        slack_user_id="%s",\n'
        '%s'
        '        day_start="%s", day_end="%s",\n'
        '        sat_start="%s", sat_end="%s", saturday=%s,\n'
        '%s'
        '    ),\n'
        % (key, key, owner, label, tz, platform, slack_id, note,
           day[0], day[1], sat[0], sat[1], saturday, camp))


def add_to_offices_py(text: str) -> None:
    src = OFFICES_PY.read_text()
    marker = "\n}\n"
    at = src.index("OFFICES: Dict[str, AlertOffice] = {")
    end = src.index(marker, at)
    OFFICES_PY.write_text(src[:end + 1] + text + src[end + 1:])


def add_to_public_json(key: str, owner: str, label: str, tz: str,
                       day, sat, saturday: bool) -> None:
    pub = json.loads(PUBLIC_JSON.read_text())
    template = next(iter((pub.get("offices") or {}).values()), {})
    pub.setdefault("offices", {})[key] = {
        "office_key": key,
        "owner": owner,
        "label": label,
        "timezone": tz,
        # Copied from an existing office: the picker is the same question for
        # everyone, and re-deriving it here is one more place to drift.
        "knocks_picker": template.get("knocks_picker", []),
        "knocks_default_hours": {
            "day_start": day[0], "day_end": day[1],
            "sat_start": sat[0], "sat_end": sat[1],
            "saturday": saturday, "tz": tz,
        },
    }
    PUBLIC_JSON.write_text(json.dumps(pub, indent=2) + "\n")


def add_relay_key(key: str, owner: str, relay_key: str, log=print) -> None:
    from automations.icd_alerts import post as P
    from automations.recruiting_report.fill import open_by_key

    book = open_by_key(P.RELAY_SPREADSHEET_ID)
    tab = book.worksheet("Relay Keys")
    tab.append_row([key, relay_key, "TRUE", "added by enroll for %s" % owner])
    log("  key written to the 'Relay Keys' tab, Active=TRUE")


def _git(*args: str) -> tuple:
    p = subprocess.run(["git", "-C", str(REPO), *args],
                       capture_output=True, text=True)
    return p.returncode, (p.stdout or p.stderr).strip()


def push(key: str, owner: str, log=print) -> bool:
    """Commit and push ONLY the two roster files.

    Pushed because an office that is not on GitHub does not exist: install.sh
    fetches offices_public.json from main, so skipping this produces an
    enrollment that looks complete and cannot possibly work.

    Only these two paths are staged. Other sessions have work in flight in this
    repo constantly, and `git add .` here would sweep it into an unrelated
    commit.
    """
    for path in (OFFICES_PY, PUBLIC_JSON):
        rc, out = _git("add", str(path.relative_to(REPO)))
        if rc:
            log("  could not stage %s: %s" % (path.name, out))
            return False
    rc, out = _git("commit", "-m",
                   "enroll %s (%s)\n\nAdded by icd_alerts.enroll: roster entry, "
                   "public record and relay key.\n\n"
                   "Co-Authored-By: Claude <noreply@anthropic.com>" % (key, owner))
    if rc:
        log("  nothing to commit (already there?): %s" % out[:120])
    rc, out = _git("pull", "--rebase", "-c", "rebase.autoStash=true", "--quiet")
    rc, out = _git("push", "origin", "HEAD")
    if rc:
        log("  PUSH FAILED -- their install cannot work until this lands: %s" % out[:200])
        return False
    log("  pushed")
    return True


def enroll(name: str, *, office: Optional[str] = None, tz: str = DEFAULT_TZ,
           day=DEFAULT_DAY, sat=DEFAULT_SAT, saturday: bool = True,
           slack_id: Optional[str] = None, do_push: bool = True,
           platform: str = "mac", label: Optional[str] = None,
           hours_known: bool = False, campaign: str = "att",
           log=print) -> int:
    from automations.icd_alerts import offices as O

    # WHAT THEY SELL, CHECKED AGAINST THE REAL LIST. This command was written
    # when every office was AT&T fiber and quietly defaulted to it -- so
    # enrolling the first NDS office through it would have pinned OwnerVille
    # to campaign id 3 instead of 1, read the wrong grid for their knocks
    # board, and handed them the AT&T hype tier, on which an NDS rep's Int is
    # structurally zero and EVERY sale they ever make reads "regular".
    #
    # None of that raises. It is three silent wrongnesses on a machine nobody
    # can reach, which is why a typo here has to stop the enrolment rather
    # than become a default.
    campaign = (campaign or "att").strip().lower()
    from automations.icd_signup.schema import CAMPAIGNS
    known = [c[0] for c in CAMPAIGNS]
    if campaign not in known:
        raise SystemExit(
            "I do not know the campaign %r. It has to be one of: %s\n"
            "This decides which grid is read and how their sales are "
            "announced, so guessing it is worse than stopping."
            % (campaign, ", ".join(known)))

    owner = " ".join((name or "").split())
    if not owner:
        raise SystemExit("Give me their name, e.g. enroll \"Cyrus Wade\"")
    key = (office or office_key_for(owner)).lower()
    if not key:
        raise SystemExit("Could not make an office name out of %r" % owner)
    if O.get(key) or key in json.loads(PUBLIC_JSON.read_text()).get("offices", {}):
        raise SystemExit(
            "%s already exists. To re-send their link:\n"
            "  python -m automations.icd_alerts.invite %s" % (key, key))

    label = label or label_for(owner)
    log("\nEnrolling %s as '%s' on %s" % (owner, key, campaign))
    if slack_id is None:
        slack_id = find_slack_id(owner, log=log)

    relay_key = mint_key(key)
    add_to_offices_py(entry_text(key, owner, label, tz, slack_id, day, sat,
                                 saturday, platform, hours_known, campaign))
    add_to_public_json(key, owner, label, tz, day, sat, saturday)
    log("  roster + public record written")

    # BEFORE the key and the push: a roster file that does not import would
    # take every office down, not just this one.
    rc = subprocess.run([sys.executable, "-c",
                         "from automations.icd_alerts import offices as O; "
                         "assert O.get(%r), 'not found'" % key],
                        cwd=str(REPO), capture_output=True, text=True)
    if rc.returncode:
        raise SystemExit("The roster did not import after editing -- nothing "
                         "was sent.\n%s" % (rc.stderr or rc.stdout)[:400])

    add_relay_key(key, owner, relay_key, log=log)
    if do_push and not push(key, owner, log=log):
        log("\nEverything is written but NOT pushed. Push it, then run:")
        log("  python -m automations.icd_alerts.invite %s" % key)
        return 1

    log("")
    from automations.icd_alerts import invite
    invite.show(key, {key: {"key": relay_key, "active": True}}, log=log)
    if not slack_id:
        log("  NOTE: no Slack id yet, so the offline nudge cannot reach them.")
        log("        python -m automations.icd_alerts.whois \"%s\"" % owner)
        log("")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Enroll an ICD office by name. One command.")
    ap.add_argument("name", help='their full name, e.g. "Cyrus Wade"')
    ap.add_argument("--office", help="override the derived office name")
    ap.add_argument("--timezone", default=DEFAULT_TZ)
    ap.add_argument("--hours", help="M-F, like 13:30-20:30")
    ap.add_argument("--saturday", help="like 10:45-17:00, or 'none'")
    ap.add_argument("--slack-id", help="skip the lookup and use this id")
    ap.add_argument("--campaign", default="att",
                    help="what this office sells: att (default), nds, "
                         "b2b_att, b2b_box, energy. It decides which "
                         "OwnerVille campaign their board reads and how their "
                         "sales are announced -- wrong is silent, so it is "
                         "checked against the real list.")
    ap.add_argument("--no-push", action="store_true",
                    help="write everything but do not push (their install "
                         "cannot work until you do)")
    a = ap.parse_args(argv)
    sat_text = (a.saturday or "").strip().lower()
    return enroll(
        a.name, office=a.office, tz=a.timezone,
        day=_hours(a.hours, DEFAULT_DAY),
        sat=DEFAULT_SAT if sat_text in ("", "none") else _hours(a.saturday, DEFAULT_SAT),
        saturday=sat_text != "none",
        slack_id=a.slack_id, do_push=not a.no_push, campaign=a.campaign)


if __name__ == "__main__":
    sys.exit(main())
