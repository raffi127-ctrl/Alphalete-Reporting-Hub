"""Which boards get an email, and everything that differs between them.

Adding a third board is one entry here — email_send.py and review_gate.py read
this and name no board themselves.

THE IMAGES ARE NOT REBUILT HERE. Each board already renders itself for its Slack
DM (`<module>.slack_post`), label-driven and cross-checked, and that is the module
this calls. One renderer per board, two delivery channels — so the email can never
disagree with the DM, and a board that changes shape is fixed in one place. The
DM stitches the blocks into one file because Slack takes one file; the email keeps
them separate so each block gets the full width of the mail column.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Callable, List, Optional

# Rafael and Maud, and nobody else (Eve, 2026-07-30). Kept as one list per board
# so a change to who reads one board is visibly a change to that board.
RAFAEL = "raffi127@gmail.com"
MAUD = "maudmiller4@gmail.com"


def _country_pngs():
    from automations.country_sales_board.slack_post import build_pngs
    return build_pngs()


def _headcount_pngs():
    from automations.org_active_headcount.email_send import build_parts
    return build_parts()


def _headcount_subject(reported: dt.date) -> str:
    # The subject it had before the gate (%a %m/%d: Windows-safe, no %-m).
    return f"Org Active Headcount — through {reported:%a %m/%d}"


def _headcount_to() -> List[str]:
    from automations.org_active_headcount.email_send import RECIPIENTS
    return list(RECIPIENTS)


@dataclass(frozen=True)
class Board:
    key: str            # --board value, and the folder name under output/
    name: str           # what the email calls itself (subject + banner)
    # () -> ([(name, Path)], str): ONE IMAGE PER BLOCK + the A1 ranges rendered.
    # Not one stitched image: stitching pads every block out to the width of the
    # widest one, so in a 900px mail column the narrow tables were painted at a
    # fraction of the space available and came out unreadable (Eve 2026-07-31).
    # The Slack DM still stitches — it takes a single file — off these same
    # blocks and the same renderer, so the two channels can't disagree.
    build_pngs: Callable
    to: List[str]       # real recipients
    drive_folder: str   # Drive folder the review PDF lands in
    review_title: str   # first line of the Slack review post, + " — M/D"
    report_id: str      # Hub card / orchestrator id
    hub_name: str       # display name used when publishing a Hub run row
    banner_bg: str = "#d9d9d9"
    banner_fg: str = "#8a0000"
    # (reported day) -> subject. None = "<name> M/D".
    subject: Optional[Callable[[dt.date], str]] = None


BOARDS: List[Board] = [
    Board(
        key="country",
        name="Country Sales Board",
        build_pngs=_country_pngs,
        to=[RAFAEL, MAUD],
        drive_folder="Country Sales Board - correos para revisar",
        # NOTE the review titles below deliberately do NOT contain the exact
        # string "Org Sales Board Email". The Org board's own gate finds its
        # post by that phrase and shares this channel, so a title containing it
        # would let the two gates read each other's posts — and a checkmark
        # meant for one board would release the other.
        review_title="Country Sales Board Email",
        report_id="country-sales-board-email",
        hub_name="Country Sales Board Email",
    ),
    # Eve 2026-09-24: "agreguemos un gate a Org Active Headcount a
    # revision-emails". It used to mail itself as soon as the morning fill was
    # done; now the scheduled run posts the PDF and a checkmark sends it, like
    # Country. Recipients stay where they were (org_active_headcount.email_send
    # .RECIPIENTS — one list, not a copy).
    Board(
        key="headcount",
        name="Org Active Headcount",
        build_pngs=_headcount_pngs,
        to=_headcount_to(),
        drive_folder="Org Active Headcount - correos para revisar",
        review_title="Org Active Headcount Email",
        report_id="org-active-headcount-email",
        hub_name="Org Active Headcount - Email",
        subject=_headcount_subject,
    ),
    # RETIRED 2026-07-31 — the All Units Org Sales Board is no longer its own
    # email. Eve: "lo que antes eran dos mails, hay que juntarlos en uno". It is
    # now the second section of the Alphalete Org Sales Board email, below a
    # labelled divider, built by org_sales_board.screenshot_email (see
    # ALLUNITS_PREFIX there). Deleting the entry rather than leaving it in place
    # is deliberate: two live senders for one board is how a report goes out
    # twice, and this gate shares its Slack channel with three others.
    # The orchestrator slot `all_units_board_email` is switched off to match.
    # Its renderer still exists — all_campaigns_board.slack_post.build_pngs.
]

BY_KEY = {b.key: b for b in BOARDS}
KEYS = [b.key for b in BOARDS]


def get(key: str) -> Board:
    try:
        return BY_KEY[key]
    except KeyError:
        raise SystemExit(f"unknown board {key!r}. Known: {', '.join(KEYS)}")
