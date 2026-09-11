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


class AlertOffice(NamedTuple):
    key: str                  # matches office_metrics.offices, and the relay
    owner: str
    label: str
    channel_id: str
    channel_name: str
    timezone: str
    active: bool = True

    def display(self) -> str:
        return "%s (%s)" % (self.label, self.channel_name)


# Kash is the pilot (Megan 2026-09-10). Everything about him was already wired
# by office_metrics -- office key, owner, channel, timezone -- so the only new
# thing in his rollout is the laptop agent.
OFFICES: Dict[str, AlertOffice] = {
    "kash": AlertOffice(
        key="kash", owner="Kash Rai", label="Kash's Local Office",
        channel_id="C09AVM17PAR", channel_name="#palace-sales",
        timezone="America/Chicago", active=True,
    ),
}


def get(key: str) -> Optional[AlertOffice]:
    return OFFICES.get((key or "").strip().lower())


def active() -> List[AlertOffice]:
    return [o for o in OFFICES.values() if o.active]


def is_enrolled(key: str) -> bool:
    """True only for an office that exists AND is switched on. A relay row from
    anywhere else is ignored rather than errored: a laptop we have revoked is
    expected to keep talking for a while, and that is not a fault."""
    o = get(key)
    return bool(o and o.active)
