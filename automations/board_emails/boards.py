"""Which boards get an email, and everything that differs between them.

Adding a third board is one entry here — email_send.py and review_gate.py read
this and name no board themselves.

THE IMAGE IS NOT REBUILT HERE. Each board already renders itself for its Slack
DM (`<module>.slack_post.build_png`), label-driven and cross-checked, and that
is the function this calls. One renderer per board, two delivery channels — so
the email can never disagree with the DM, and a board that changes shape is
fixed in one place.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List

# Rafael and Maud, and nobody else (Eve, 2026-07-30). Kept as one list per board
# so a change to who reads one board is visibly a change to that board.
RAFAEL = "raffi127@gmail.com"
MAUD = "maudmiller4@gmail.com"


def _country_png():
    from automations.country_sales_board.slack_post import build_png
    return build_png()


def _all_units_png():
    from automations.all_campaigns_board.slack_post import build_png
    return build_png()


@dataclass(frozen=True)
class Board:
    key: str            # --board value, and the folder name under output/
    name: str           # what the email calls itself (subject + banner)
    build_png: Callable  # () -> (Path, str): the rendered board + its A1 range
    to: List[str]       # real recipients
    drive_folder: str   # Drive folder the review PDF lands in
    review_title: str   # first line of the Slack review post, + " — M/D"
    report_id: str      # Hub card / orchestrator id
    hub_name: str       # display name used when publishing a Hub run row
    banner_bg: str = "#d9d9d9"
    banner_fg: str = "#8a0000"


BOARDS: List[Board] = [
    Board(
        key="country",
        name="Country Sales Board",
        build_png=_country_png,
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
    Board(
        key="all-units",
        name="All Units Org Sales Board",
        build_png=_all_units_png,
        to=[RAFAEL, MAUD],
        drive_folder="All Units Sales Board - correos para revisar",
        review_title="All Units Board Email",
        report_id="all-units-board-email",
        hub_name="All Units Org Sales Board Email",
    ),
]

BY_KEY = {b.key: b for b in BOARDS}
KEYS = [b.key for b in BOARDS]


def get(key: str) -> Board:
    try:
        return BY_KEY[key]
    except KeyError:
        raise SystemExit(f"unknown board {key!r}. Known: {', '.join(KEYS)}")
