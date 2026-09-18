"""Which ICD offices get credit-check alerts, and where each one's go.

ONE ROW PER OFFICE, and `active` is the revoke switch. Turning an office off
here stops the posting even if their laptop keeps relaying happily -- which is
the whole reason the posting lives on our side. Nothing on their machine has to
cooperate with being switched off.

The channel ids are the ones office_metrics already posts each office's metrics
into, so Lucy is a member and `chat_postMessage` is already proven for them.
#palace-sales is PRIVATE: if Lucy is ever removed, Slack answers
`channel_not_found` rather than `not_in_channel` -- it will not admit a private
channel exists to a non-member -- so that error means MEMBERSHIP, not a bad id.

Adding an office is a row here plus a relay key. Nothing else.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, NamedTuple, Optional


# Where alerts go when an office is relaying but nobody has decided its
# channel yet. NOT a team room: a guess that lands in front of 20 people is
# worse than one that lands in front of Megan. New ICDs will not already be
# enrolled in anything (Megan 2026-09-11), so this is the normal state for a
# day or two, not an error -- the alerts are real and they are held, not lost.
HOLDING_DM = "U04G5HJBGFN"

# WHO CAN FINISH AN OFFICE'S SET-UP, and who has to be in the room before one
# is switched on (Megan 2026-09-13: "I want it so Eve or I can complete the
# set up"). Either of them runs the approval; the check reports on ALL of
# them, so it does not matter which.
#
# Eve is Evelyn Sobrino, and the id was RESOLVED rather than guessed: a search
# for "Eve" returned twenty-odd people, while her full name matched exactly
# one. That difference matters -- everything here is used to decide whether a
# room is ready, and a wrong id says a person is missing who is standing right
# there, or present when they are not.
APPROVERS = {
    "U04G5HJBGFN": "Megan",
    "U088E2KJEV8": "Eve",        # Evelyn Sobrino, @Evelyn Sobrino
}          # Megan
HOLDING_LABEL = "Megan (no channel set yet)"

# Where OUR problems go: an office gone quiet, an enrolment waiting on a
# human. #claudecorrections-and-requests, not Megan's DM (Megan 2026-09-12).
#
# A DM is one person's inbox, and these are things anyone on the team may need
# to pick up -- the channel is where every other report already reports its
# failures, so this stops being a separate place to remember to look.
# HELD OFFICE ALERTS still go to the DM: those are an office's real numbers
# waiting on a routing decision, not an operational fault, and a channel of
# failures is the wrong place for somebody's credit checks.
OPS_CHANNEL = "C0BK5PRG259"         # #claudecorrections-and-requests

# The Apps Script web app every laptop hands its totals to. One url for every
# office -- the KEY is what identifies and authorises, not the address, so
# there is nothing per-office to get wrong here. Deployed from
# resources/icd-alerts-relay.gs against the 'Lucy Access App' workbook.
RELAY_URL = ("https://script.google.com/macros/s/"
             "AKfycbwl4YR_SsJyWWRFV3cEQrNGq3vzqFDMUBGm4v692ZBJnfHVFMvnTfFm9vxG_r5cE4Wn"
             "/exec")


class Channel(NamedTuple):
    id: str
    name: str                 # for logs and previews; Slack only needs the id


class AlertOffice(NamedTuple):
    """One office's alerts, and everywhere they go.

    THE CHANNELS LIVE HERE, NOT ON THE LAPTOP, and that is deliberate (Megan
    2026-09-11 asked whether the installer should ask). A laptop that could
    name its own channel could name ANY channel in the AO workspace, and the
    whole reason the posting stays on our side is that it cannot. Changing
    where an office posts is a line in this file, not something 52 people can
    each decide.

    A TUPLE, because an office can have more than one room -- an owner's own
    channel plus a regional one, say. One is the common case and reads the
    same.
    """
    key: str                  # matches office_metrics.offices, and the relay
    owner: str
    label: str
    channels: tuple
    timezone: str
    active: bool = True
    # WHICH LAUNCHER THEIR PACKAGE CARRIES, recorded once so nobody has to
    # remember. It is not cosmetic: GMAIL STRIPS .bat EVEN INSIDE A ZIP, so a
    # "both" package cannot reliably be emailed at all and the bounce does not
    # say why. Knowing the office's platform is what lets the build be right
    # the first time instead of after a rebuild.
    platform: str = "mac"
    # The OWNER's Slack id, for the 11am nudge when their laptop has not
    # checked in. Empty = nudge Megan only, which is the safe default: a DM to
    # the wrong person about a machine they do not own is worse than no DM.
    # Fill it with `python -m automations.icd_alerts.whois "Kash Rai"`, or from
    # Slack: click their name, the three dots, Copy member ID.
    slack_user_id: str = ""
    # WHEN THIS OFFICE'S REPS ARE ACTUALLY OUT, on their own clock. The knocks
    # board only posts inside these hours: a board at 9pm about an office that
    # stopped at 8:30 is a report on a finished day, and a gap alert after the
    # last knock is noise with somebody's name on it.
    #
    # PER OFFICE, not one shared default. Kash finishes at 8:30 and Cyrus at
    # 8:30, but their Saturdays differ by 45 minutes at the start and an hour
    # at the end (Megan 2026-09-12) -- and a single org-wide window would have
    # posted into both of their quiet time.
    day_start: str = "13:30"
    day_end: str = "20:30"
    sat_start: str = "10:45"
    sat_end: str = "17:00"
    saturday: bool = True
    # Which campaign this office's board is. Defaults to AT&T: every office
    # enrolled before campaigns existed was on it.
    campaign: str = "att"

    def display(self) -> str:
        where = ", ".join(c.name for c in self.channels) or "no channel set yet"
        return "%s (%s)" % (self.label, where)


# CARLOS'S TWO CAMPAIGNS SHARE ONE ROOM, ON PURPOSE (Megan, 2026-09-16:
# "keep it shared"). Box and B2B AT&T both post to #alphalete-gp-sales. It
# looks like a routing mistake and is not one -- the board header names the
# campaign, and he wants them together. Do not "fix" it.
#
# Kash is the pilot (Megan 2026-09-10). Everything about him was already wired
# by office_metrics -- office key, owner, channel, timezone -- so the only new
# thing in his rollout is the laptop agent.
OFFICES: Dict[str, AlertOffice] = {
    "kash": AlertOffice(
        key="kash", owner="Kash Rai", label="Kash's Local Office",
        # NO CHANNEL CONFIRMED YET. #palace-sales (C09AVM17PAR) is where
        # office_metrics posts his metrics and where the Tableau trackers go,
        # so Lucy is already a member and it is the obvious candidate -- but
        # Megan has not confirmed Kash wants his credit-check pings there
        # (2026-09-11: "Idk if he wants the palace sales channel"). Until she
        # says so, his alerts go to the holding DM. Putting them in front of
        # his whole team on a guess is not a thing to undo.
        channels=(),
        timezone="America/Chicago", active=True, platform="mac",
        slack_user_id="U046XBPN0G2",     # Kash Rai, @palace.kash
        # WHAT HIS OFFICE ACTUALLY WORKS, read off his own relayed Time
        # Tracker rather than asked for again (Megan 2026-09-17: "fix kash
        # and cyrus's hours to their real ones"). He gave 13:30-20:30 on
        # 2026-09-12 and his reps do not work it: across 09-14, 09-15 and
        # 09-16 the first knock landed 1:14-1:24pm and the LAST landed
        # 9:02-9:09pm, better than half an hour past the recorded close.
        #
        # That half hour was not cosmetic. in_field_hours gates the knocks
        # board, so his last board of the day went out at 20:09 while 14 of
        # his 18 reps were still knocking -- and the close-out gate judges a
        # day finished against day_end, so a too-early one calls a short day
        # complete. Ends 21:15, which covers the observed 9:09pm and still
        # sits inside the agent's own 21:30 window.
        #
        # 13:00, not 13:15: his earliest observed first knock is 1:14pm and
        # a window that opens a minute before it is a window that will be
        # wrong the first time somebody starts early. Opening too early costs
        # nothing -- there is simply no data to draw yet.
        #
        # SATURDAY IS LEFT ALONE: 10:40am-4:57pm observed on 09-12 fits the
        # 10:30-17:00 already recorded. One Saturday of data, so it is not
        # worth moving on.
        day_start="13:00", day_end="21:15",
        sat_start="10:30", sat_end="17:00",
    ),
    "cyrus": AlertOffice(
        key="cyrus", owner="Cyrus Wade", label="Cyrus's Local Office",
        # UNROUTED until he asks and Megan approves, same as Kash.
        # #ambient-sales-1 (C0B1DHEFVLH, private, 53 people) is where
        # office_metrics already posts his daily metrics, so Lucy is a member
        # and it is the obvious candidate -- but "obvious to us" is not the
        # same as "what he wants his credit-check pings in", and the installer
        # asks him.
        channels=(),
        timezone="America/Chicago", active=True,     # Tyler, TX
        platform="mac",                              # confirmed 2026-09-12
        # HE IS "Cy Wade" IN SLACK, not Cyrus Wade -- which is why a search on
        # his canonical name found nobody in his own channel. Found by
        # searching #ambient-sales-1 for 'wade'; @wadebusiness7 is the only
        # Wade in the room. Worth a glance from Megan before the first nudge:
        # this id is a DM recipient, and the cost of the wrong one is a
        # message to a stranger about a machine they do not own.
        slack_user_id="U06A1QA642X",     # Cy Wade, @wadebusiness7
        # HIS REAL HOURS, from his own relayed Time Tracker (Megan
        # 2026-09-17). What he gave on 2026-09-12 was wrong at both ends of
        # both windows:
        #   weekday  13:30-20:30 recorded; observed first knock 12:47pm
        #            (09-14) and 1:10pm (09-16), last knock 9:11pm and
        #            9:09pm. 09-15 is excluded -- his agent died at 14:52,
        #            so that day's end time is an artefact, not an early
        #            finish.
        #   Saturday 11:15-16:00 recorded; observed 11:11am to 5:00pm on
        #            09-12. A FULL HOUR past the recorded close, so his
        #            Saturday board stopped while the office was still out.
        #
        # One Saturday of data, so 17:15 is a margin on a single reading
        # rather than a settled fact; worth re-checking once a few more
        # Saturdays have relayed.
        # 11:30, not 12:45: his 09-15 first knock was 11:47am, a full hour
        # before the other days. Opening early costs nothing; opening after
        # the office has started means no board while they work.
        day_start="11:30", day_end="21:15",
        sat_start="11:00", sat_end="17:15",
    ),
    # A STRAY FROM A FIRST SIGN-UP ATTEMPT, switched off (Megan, 2026-09-16).
    # Khalil enrolled twice and installed as "khalil-nds", which is the live
    # office; this key has never relayed and never will. Left active it would
    # have reported itself as a quiet office every morning forever, and a
    # standing false alarm is how the real ones stop being read.
    #
    # `active` is the revoke switch and the code table wins over the sign-up
    # tab, so this needs no edit to anybody's sheet. The row is otherwise a
    # copy of what he filled in, so nothing here contradicts the form.
    "khalil": AlertOffice(
        key="khalil", owner="Khalil Mansour", label="Khalil's Local Office",
        channels=(),
        timezone="America/Chicago", active=False, platform="mac",
        slack_user_id="U045F9JCPJT",     # Khalil Mansour
        day_start="13:30", day_end="21:00",
        sat_start="10:45", sat_end="20:00", saturday=True,
        campaign="nds",
    ),
    # NEVER RELAYED, NOT ONCE, and switched off for it (Megan 2026-09-16).
    # A test enrolment that stayed on the books: left active it reported
    # itself as a quiet office every morning, which is a standing false alarm
    # of exactly the kind that teaches people to skim the real ones.
    "ztest": AlertOffice(
        key="ztest", owner="Test Office", label="Test Office",
        channels=(), timezone="America/Chicago", active=False,
        platform="mac", campaign="b2b_box",
    ),
    # Her sign-up came through as "Roshan Amin  ahmad" -- a double space and a
    # lowercase surname, which is what a form field gives you. It shows in the
    # quiet-machine nudge and on her Hub card, so it is spelled properly here.
    # OwnerVille already has it right ("Roshan Amin Ahmad").
    #
    # Everything else is HER form answer, copied rather than defaulted: the
    # 10:30-18:30 day is a B2B office's, not a typo for a D2D one.
    "roshan": AlertOffice(
        key="roshan", owner="Roshan Amin Ahmad",
        label="Roshan's Local Office",
        channels=(),
        timezone="America/Chicago", active=True, platform="mac",
        # Looked up 2026-09-18. Without it the quiet nudge said "No Slack id
        # on file -- nudge them yourself", so every alert about her machine
        # reached Megan and Eve and never the one person who could walk to it.
        # Slack spells her "Amin Ahmad Roshan"; we spell her the other way
        # round, which is why a name match alone was not enough to trust.
        slack_user_id="U066B1ZUT4J",
        day_start="10:30", day_end="18:30",
        sat_start="10:30", sat_end="17:00", saturday=True,
        campaign="b2b_box",
    ),

    "aya": AlertOffice(
        key="aya", owner="Aya Al-Khafaji", label="Aya's Local Office",
        # UNROUTED on purpose: the installer asks them where they want
        # their alerts, and a human approves it. Nothing posts until then.
        channels=(),
        timezone="America/New_York", active=True, platform="mac",
        slack_user_id="U07QGLA10EN",
        # HER OWN ANSWERS, off the sign-up form (2026-09-17) -- not the org
        # default. They have to be copied here because all_offices() merges
        # the sign-up tab and then the code table, CODE WINNING, so a row
        # here silently overrides whatever the owner typed into the form.
        # Left at the default it cost her the last hour of Saturday (she
        # sells to 18:00, the default stops at 17:00) and the first half hour
        # of every weekday.
        day_start="13:00", day_end="20:30",
        sat_start="11:00", sat_end="18:00", saturday=True,
        # AT&T fiber, which is also the default -- said plainly so the
        # next person does not have to know what the default is.
        campaign="att",
    ),

}


def in_field_hours(office: "AlertOffice", now=None) -> bool:
    """Is this office's field actually out right now, on their own clock?

    Sunday is off for everyone. Each office carries its own window, because
    they genuinely differ -- and posting a board into a room whose day ended
    an hour ago is how a useful feed becomes one people mute.
    """
    now = now or office_now(office)
    if now.weekday() == 6:
        return False
    if now.weekday() == 5:
        if not office.saturday:
            return False
        start, end = office.sat_start, office.sat_end
    else:
        start, end = office.day_start, office.day_end
    return _hm(start) <= (now.hour, now.minute) <= _hm(end)


def _hm(text: str):
    h, m = str(text).split(":")
    return int(h), int(m)


def office_now(office: "AlertOffice", fallback=None):
    """Now, on THIS office's clock.

    Everything that judges an office judges it here: a board saying a rep has
    been quiet 48 minutes is a claim about their evening, and 11am means 11am
    where they are. An Eastern office is an hour further into its morning than
    a Central one, and a single shared cutoff would nag one early and let the
    other slide.
    """
    import datetime as _dt
    if fallback is not None:
        return fallback
    try:
        from zoneinfo import ZoneInfo
        return _dt.datetime.now(ZoneInfo(office.timezone)).replace(tzinfo=None)
    except Exception:  # noqa: BLE001 — a missing tzdata must not stop a report
        return _dt.datetime.now()



# ---------------------------------------------------------------------------
# OFFICES THAT SIGNED THEMSELVES UP.
#
# The table above is hand-written and needs a commit and a push. That was the
# whole four-step enrolment Megan cut down on 2026-09-13 -- and it cannot work
# at all for the flow she asked for next: the sign-up form runs on Streamlit's
# servers, not on a machine with this repo, so it can mint a key and write a
# row but can never write Python. An office that signs up has to become real
# without anybody pushing anything.
#
# So the roster is the code table PLUS the sign-up tab. The CODE ALWAYS WINS
# on a key that appears in both: kash and cyrus carry hand-checked Slack ids
# and hours that a form answer must never quietly overwrite.
#
# READ THROUGH A FILE CACHE. The poster runs as a fresh process every two
# minutes, and a Sheets read per tick would spend the quota that the office
# writes actually need [[reference_sheets_write_quota_429]]. Ten minutes is
# far quicker than anybody can install.
# ---------------------------------------------------------------------------
SHEET_CACHE = (Path.home() / ".config" / "recruiting-report"
               / "icd_sheet_offices.json")
SHEET_CACHE_TTL_S = 600


def _office_from_signup(row: Dict) -> Optional[AlertOffice]:
    key = str(row.get("office_key") or "").strip().lower()
    if not key:
        return None
    status = str(row.get("status") or "").strip().lower()
    def _b(v):
        return str(v).strip().upper() in ("TRUE", "YES", "Y", "1")
    saturday = _b(row.get("saturday"))
    return AlertOffice(
        key=key,
        owner=str(row.get("owner") or "").strip(),
        label=(str(row.get("office_label") or "").strip()
               or "%s's Local Office" % (str(row.get("owner") or "there")
                                         .strip().split() or ["there"])[0]),
        # NEVER ROUTED FROM THE FORM. What they typed is a request on the
        # 'Office Channels' tab; a human approves it. A sign-up that could
        # name its own channel would be an office enrolling itself into
        # somebody else's room.
        channels=(),
        timezone=str(row.get("timezone") or "America/Chicago").strip(),
        # A DECLINED office is switched off; everything else stays on. An
        # office that has installed but is not approved yet must still be
        # ACCEPTED by the relay -- its numbers are real and are simply held
        # until somebody says where they go [[destinations]].
        active=status != "declined",
        platform=str(row.get("platform") or "mac").strip().lower(),
        slack_user_id=str(row.get("slack_user_id") or "").strip(),
        day_start=str(row.get("day_start") or "13:30").strip(),
        day_end=str(row.get("day_end") or "20:30").strip(),
        sat_start=str(row.get("sat_start") or "10:45").strip(),
        sat_end=str(row.get("sat_end") or "17:00").strip(),
        saturday=saturday,
        campaign=str(row.get("campaign") or "att").strip().lower(),
    )


def _read_signup_tab() -> List[Dict]:
    from automations.icd_alerts import post as P
    from automations.recruiting_report.fill import open_by_key
    book = open_by_key(P.RELAY_SPREADSHEET_ID)
    return book.worksheet("ICD Signup").get_all_records()


def sheet_offices(force: bool = False) -> Dict[str, AlertOffice]:
    """Signed-up offices, from the cache unless it is stale.

    NEVER RAISES. This sits under get() and active(), which every posting path
    calls; an exception here would take out the offices that ARE working in
    order to report a problem with one that is not.
    """
    import json
    import time

    if not force:
        try:
            age = time.time() - SHEET_CACHE.stat().st_mtime
            if age < SHEET_CACHE_TTL_S:
                rows = json.loads(SHEET_CACHE.read_text())
                return {k: o for k, o in
                        ((r.get("office_key"), _office_from_signup(r))
                         for r in rows) if k and o}
        except Exception:  # noqa: BLE001
            pass
    try:
        rows = _read_signup_tab()
    except Exception:  # noqa: BLE001 — fall back to whatever the cache holds
        try:
            rows = json.loads(SHEET_CACHE.read_text())
        except Exception:  # noqa: BLE001
            return {}
    else:
        try:
            SHEET_CACHE.parent.mkdir(parents=True, exist_ok=True)
            SHEET_CACHE.write_text(json.dumps(rows, indent=2, default=str))
        except Exception:  # noqa: BLE001
            pass
    out = {}
    for r in rows:
        o = _office_from_signup(r)
        if o:
            out[o.key] = o
    return out


# WHO ELSE ACTUALLY DOES AN OFFICE'S MACHINE WORK.
#
# Khalil's computer is looked after by Francia, not by Khalil (Megan,
# 2026-09-18: "For khalil's alerts it should include Francia in the DM"). She
# ran every sign-in step on it for two days while the alerts went to him and
# to us -- so the one person walking to that machine was the only one not
# being told when it needed her.
#
# KEYED HERE, not a field on AlertOffice, because an office can come from the
# SIGN-UP TAB rather than the code table -- khalil-nds does -- and a code row
# added just to carry this would silently override whatever the owner typed
# into the form. That cost Aya an hour of her Saturday on 2026-09-17.
#
# ADDED TO the owner, never instead.
HELPERS = {
    "khalil": ("U0543NQEWMD",),        # Francia Olivares
    "khalil-nds": ("U0543NQEWMD",),    # same machine, the live enrolment
}


def helpers_for(key: str) -> tuple:
    """Extra Slack ids to tell alongside the owner. Never raises."""
    return tuple(HELPERS.get((key or "").strip().lower()) or ())


def all_offices() -> Dict[str, AlertOffice]:
    """The code table plus the sign-up tab, code winning on a shared key."""
    merged = dict(sheet_offices())
    merged.update(OFFICES)
    return merged


# The fields an OWNER chooses for themselves on the sign-up form. A code row
# that disagrees with one of these is overriding a person's own answer.
OWNER_CHOSEN = ("campaign", "timezone", "day_start", "day_end",
                "sat_start", "sat_end", "saturday")


def shadowed(sheet=None) -> Dict[str, Dict]:
    """Offices whose code row contradicts what they typed into the form.

    all_offices() merges the sign-up tab and then the code table, CODE
    WINNING -- which is right for an office that predates the form, and wrong
    the moment the owner answers for themselves. The override is SILENT: the
    form accepts their hours, shows them as saved, and something else is
    served.

    It cost Aya the last hour of her Saturday on 2026-09-17 (she sells to
    18:00; the org default in her code row stopped at 17:00) and nobody would
    have found it from either side alone -- the form says 18:00 and the code
    says 17:00 and neither is aware of the other.

    Returns {office_key: {field: (form_value, code_value)}}. Empty is good.
    """
    rows = sheet if sheet is not None else sheet_offices()
    out: Dict[str, Dict] = {}
    for key, signed in rows.items():
        coded = OFFICES.get(key)
        if not coded:
            continue
        diff = {f: (getattr(signed, f, None), getattr(coded, f, None))
                for f in OWNER_CHOSEN
                if getattr(signed, f, None) != getattr(coded, f, None)}
        if diff:
            out[key] = diff
    return out


def get(key: str) -> Optional[AlertOffice]:
    return all_offices().get((key or "").strip().lower())


def active() -> List[AlertOffice]:
    return [o for o in all_offices().values() if o.active]


def destinations(office: "AlertOffice", approved=None):
    """Where this office's alerts actually go right now.

    `approved` is what the 'Office Channels' tab says a human has signed off.
    It WINS over the code, because the person approving must not need a commit
    to do it -- an approval that waits on an engineer is an approval that does
    not happen. The code row stays as the fallback for offices that predate
    the tab.

    Never empty. An office with nothing approved is HELD, not dropped: the
    alerts are real, somebody just has not said where they belong yet.
    """
    if approved:
        return list(approved), False
    if office.channels:
        return list(office.channels), False
    return [Channel(HOLDING_DM, HOLDING_LABEL)], True


def is_enrolled(key: str) -> bool:
    """True only for an office that exists AND is switched on. A relay row from
    anywhere else is ignored rather than errored: a laptop we have revoked is
    expected to keep talking for a while, and that is not a fault."""
    o = get(key)
    return bool(o and o.active)
