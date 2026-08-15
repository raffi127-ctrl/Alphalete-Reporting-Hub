"""The Slack post — Evelyn's wording, character for character.

Her 8/13 post is the spec (thread reply 1786708291.575689 in #alphalete-sales):

    *Energy Cross-reference*
    *Cross-reference completed for Energy 8.13*
    • Slack: 11 sales
    • Sales Board: 11 sales
    • Webform: 6 sales submitted, 5 missing
    Hey, guys! Reminder, _*we don't get paid out …*_, please *fill out* in the
    future *as soon as you finish the sale* in the field!
    Please submit yesterday's sales and respond "submitted" once done so we can
    confirm its done! @Charley Perez @Edgar Camunez @Zoria Johnson
                      @Rafael Hidalgo @Dylan Twaddle

The reps who owe a form are tagged FIRST, alphabetically, then Rafael and Dylan
— always, whether or not anyone is short.

TWO PLACES THE TEXT BENDS, both because the day earned it:
  * nobody missing — the reminder to go fill the form out is dropped (there is
    nothing to fill out) and the bullet says so. Rafael and Dylan are still
    tagged, so the thread still shows the check ran.
  * a duplicate form — an extra bullet names it. Without that line the numbers
    don't add up on their face (a rep with 2 forms shown as 1 short) and the
    first reply is always "but I submitted twice".
"""
from __future__ import annotations

import datetime as dt

from automations.energy_crossref.crossref import Result
from automations.energy_crossref.roster import display

# Tagged on every post regardless of the day: the two people who chase this.
ALWAYS_TAG = ["Rafael Hidalgo", "Dylan Twaddle"]

REMINDER = (
    "Hey, guys! Reminder, _*we don't get paid out on sales if the webform "
    "isn't filled out*_, please *fill out* in the future *as soon as you "
    "finish the sale* in the field!")

ASK = ("Please submit yesterday’s sales and respond \"submitted\" once "
       "done so we can confirm its done!")


def day_label(day: dt.date) -> str:
    """'8.13' — the same m.d the daily post's images are captioned with. Built by
    hand: %-m is glibc-only and this has to run on Windows too."""
    return f"{day.month}.{day.day}"


def build(res: Result, tags: list[tuple[str, str]]) -> str:
    """The message text. `tags` is [(board name, slack id or '')] in tag order.

    A rep with no id is written as their plain BOLD NAME rather than dropped: the
    point of the post is that the person who owes a form reads their own name in
    it, and their manager is tagged either way."""
    missing = res.missing_total
    if missing:
        forms = f"{res.forms_total} sales submitted, {missing} missing"
    else:
        forms = f"{res.forms_total} sales submitted — all accounted for"

    lines = [
        "*Energy Cross-reference*",
        f"*Cross-reference completed for Energy {day_label(res.day)}*",
        f"• Slack: {res.slack_total} sales",
        f"• Sales Board: {res.board_total} sales",
        f"• Webform: {forms}",
    ]
    dupes = res.dupes
    if dupes:
        lines.append(
            f"• Duplicate webforms not counted: {len(dupes)} "
            f"({'; '.join(name for name, _why in dupes)})")

    mentions = " ".join(f"<@{uid}>" if uid else f"*{display(name)}*"
                        for name, uid in tags)
    if missing:
        lines.append(REMINDER)
        lines.append(f"{ASK} {mentions}".strip())
    else:
        lines.append(f"Every Energy sale has its webform — nice work! "
                     f"{mentions}".strip())
    return "\n".join(lines)


def tag_names(res: Result) -> list[str]:
    """Who to mention, in order: the reps who owe a form, then Rafael + Dylan."""
    return [r.board_name for r in res.short] + ALWAYS_TAG


