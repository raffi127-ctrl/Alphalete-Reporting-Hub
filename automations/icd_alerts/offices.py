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

from typing import Dict, List, NamedTuple, Optional


# Where alerts go when an office is relaying but nobody has decided its
# channel yet. NOT a team room: a guess that lands in front of 20 people is
# worse than one that lands in front of Megan. New ICDs will not already be
# enrolled in anything (Megan 2026-09-11), so this is the normal state for a
# day or two, not an error -- the alerts are real and they are held, not lost.
HOLDING_DM = "U04G5HJBGFN"          # Megan
HOLDING_LABEL = "Megan (no channel set yet)"

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

    def display(self) -> str:
        where = ", ".join(c.name for c in self.channels) or "no channel set yet"
        return "%s (%s)" % (self.label, where)


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
    ),
}


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


def get(key: str) -> Optional[AlertOffice]:
    return OFFICES.get((key or "").strip().lower())


def active() -> List[AlertOffice]:
    return [o for o in OFFICES.values() if o.active]


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
