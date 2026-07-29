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
    # The "Promoted to" single-select. The leader sets the level for the batch —
    # we no longer infer it from the board (it can already be bumped). Default to
    # the first choice (Level 1), the most common promotion.
    level_opts = [{"text": {"type": "plain_text", "text": lbl}, "value": rec}
                  for (lbl, rec) in C.LEVEL_CHOICES]
    level_select = {
        "type": "static_select", "action_id": C.ACTION_LEVEL,
        "placeholder": {"type": "plain_text", "text": "Level…"},
        "options": level_opts, "initial_option": level_opts[0],
    }
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": title}},
        {"type": "section", "text": {"type": "mrkdwn", "text": ask}},
        # A multi-select is only valid as a section ACCESSORY (Slack rejects it in
        # an actions block). block_id is what the handler reads from state.values.
        {"type": "section", "block_id": C.BLOCK_CALLBACK,
         "text": {"type": "mrkdwn", "text": "*Who got promoted* (grouped by team)"},
         "accessory": select},
        {"type": "section", "block_id": C.ACTION_LEVEL,
         "text": {"type": "mrkdwn", "text": "*Promoted to*"},
         "accessory": level_select},
        {"type": "actions", "elements": [
            {"type": "button", "action_id": C.ACTION_SUBMIT, "style": "primary",
             "value": "preview" if preview else "live",
             "text": {"type": "plain_text", "text": "✅ Log promotions"}},
            {"type": "button", "action_id": C.ACTION_NONE,
             "text": {"type": "plain_text", "text": "No promotions this week"}},
            {"type": "button", "action_id": C.ACTION_REMOVE,
             "text": {"type": "plain_text", "text": "✏️ Remove a mistake"}},
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


def remove_modal(week_label, logged, *, channel: str = "", ts: str = ""):
    """A modal listing what OUR office logged this week, to un-log a mistake.
    `logged` = [(rep, recognition)]. private_metadata carries the card's channel+ts
    so the submission can reply under it."""
    import json
    pm = json.dumps({"channel": channel, "ts": ts, "week": week_label})
    if not logged:
        return {
            "type": "modal", "callback_id": C.REMOVE_CALLBACK,
            "private_metadata": pm,
            "title": {"type": "plain_text", "text": "Remove a promotion"},
            "close": {"type": "plain_text", "text": "Close"},
            "blocks": [{"type": "section", "text": {"type": "mrkdwn",
                "text": f"Nothing is logged yet for *{week_label}* from this office "
                        "— nothing to remove."}}],
        }
    opts = [{"text": {"type": "plain_text",
                      "text": f"{rep} · {rec}"[:75]}, "value": rep[:75]}
            for (rep, rec) in logged]
    return {
        "type": "modal", "callback_id": C.REMOVE_CALLBACK, "private_metadata": pm,
        "title": {"type": "plain_text", "text": "Remove a promotion"},
        "submit": {"type": "plain_text", "text": "Remove"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn",
             "text": f"Pick anyone logged by mistake for *{week_label}* — I'll clear "
                     "their row from the recognition sheet."}},
            {"type": "input", "block_id": C.ACTION_REMOVE_PICK,
             "label": {"type": "plain_text", "text": "Remove from the sheet"},
             "element": {"type": "multi_static_select", "action_id": "v",
                         "placeholder": {"type": "plain_text", "text": "Pick reps to remove…"},
                         "options": opts}},
        ],
    }


def removed_blocks(week_label, result, *, actor: str = ""):
    """Thread receipt after a removal."""
    removed = result.get("removed", [])
    by = f" by <@{actor}>" if actor else ""
    if removed:
        lines = "\n".join(f"• *{name}*" for name in removed)
        note = "" if result.get("wrote") else "  _(preview — sheet not changed)_"
        return [{"type": "section", "text": {"type": "mrkdwn",
                 "text": f":wastebasket: *Removed {len(removed)}{by}* from the "
                         f"<{result['link']}|{result['tab']} tab>{note}:\n{lines}"}}]
    return [{"type": "section", "text": {"type": "mrkdwn",
             "text": f":information_source: Nothing removed{by} — those reps weren't "
                     "found among this office's logged rows."}}]


def none_blocks(week_label, *, actor: str = ""):
    by = f" <@{actor}>" if actor else ""
    return [{"type": "section", "text": {"type": "mrkdwn",
             "text": f":white_check_mark: No promotions logged for *{week_label}*"
                     f" — thanks{by}."}}]
