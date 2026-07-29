"""Build the interactive check-in message (Block Kit).

Deliberately un-blocky: a header, one line of ask, and a single tidy
multi-select grouped by team — leaders just open the dropdown and tick names,
then hit one button. No wall of text listing every rep.

Slack note: in a POSTED message (not a modal) the multi-select's current
selection rides along in every later `block_actions` payload as
`state.values`, so the "Log promotions" button can read what was picked.
"""
from __future__ import annotations

from . import config as C


def _opt(rep):
    # value = the rep's cleaned name; the handler re-reads the board to resolve
    # trainer + next level, so the value stays short (< 75 char Slack cap).
    label = f"{rep.name} · {rep.level}"
    if rep.field:
        label += f" ({rep.field})"
    return {"text": {"type": "plain_text", "text": label[:75]}, "value": rep.name[:75]}


def build_message(week_label, reps_by_team, *, final_call: bool = False,
                  preview: bool = False):
    """`reps_by_team` = {team: [Rep]} of PROMOTABLE reps. Returns Block Kit blocks.

    `preview=True` stamps the submit button so the handler NEVER writes the sheet
    for this card, regardless of the listener's PROMO_WRITE — used for the test DM.
    """
    n = sum(len(v) for v in reps_by_team.values())
    groups = []
    for team, reps in reps_by_team.items():
        if not reps:
            continue
        groups.append({
            "label": {"type": "plain_text", "text": team[:75]},
            "options": [_opt(r) for r in reps],
        })

    if final_call:
        title = f"⏰ Final Call — Promotions · {week_label}"
        ask = ("*Last chance before the Leader's Call.* Anyone who leveled up "
               "this week and isn't logged yet — pick them now and hit "
               "*Log promotions*.")
    else:
        title = f"🏆 Weekly Promotion Check-In · {week_label}"
        ask = ("*Did anyone level up this week?* Pick every rep who got promoted "
               "and hit *Log promotions* — I'll add them to tonight's recognition "
               "sheet with their trainer.")

    select = {
        "type": "multi_static_select",
        "action_id": C.ACTION_PICK,
        "placeholder": {"type": "plain_text", "text": "Pick reps who got promoted…"},
        "option_groups": groups,
    }
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": title}},
        {"type": "section", "text": {"type": "mrkdwn", "text": ask}},
        {"type": "actions", "block_id": C.BLOCK_CALLBACK, "elements": [select]},
        {"type": "actions", "elements": [
            {"type": "button", "action_id": C.ACTION_SUBMIT, "style": "primary",
             "value": "preview" if preview else "live",
             "text": {"type": "plain_text", "text": "✅ Log promotions"}},
            {"type": "button", "action_id": C.ACTION_NONE,
             "text": {"type": "plain_text", "text": "No promotions this week"}},
        ]},
        {"type": "context", "elements": [{"type": "mrkdwn",
            "text": f"Reading the Sales Board · {week_label} · {n} reps eligible · "
                    f"promotions log to Monday's recognition sheet"}]},
    ]
    return blocks


def confirmation_blocks(week_label, result, *, actor: str = ""):
    """Replace the card after a submit. `result` = recognition.append_promotions()."""
    added = result.get("added", [])
    dup = result.get("skipped_dup", [])
    by = f" by <@{actor}>" if actor else ""
    if added:
        lines = "\n".join(f"• *{name}*" for name in added)
        head = (f":trophy: *Logged {len(added)} promotion"
                f"{'s' if len(added) != 1 else ''}{by}* to the "
                f"<{result['link']}|{result['tab']} recognition tab>:")
        text = f"{head}\n{lines}"
        if dup:
            text += f"\n_Already on the sheet (skipped): {', '.join(dup)}._"
    else:
        text = (f":information_source: Nothing new to log{by}"
                + (f" — already on the sheet: {', '.join(dup)}." if dup
                   else " for this week."))
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


def none_blocks(week_label, *, actor: str = ""):
    by = f" <@{actor}>" if actor else ""
    return [{"type": "section", "text": {"type": "mrkdwn",
             "text": f":white_check_mark: No promotions logged for *{week_label}*"
                     f" — thanks{by}."}}]
