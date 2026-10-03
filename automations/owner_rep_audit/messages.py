"""Every text this job sends. Pure functions so the tests pin the wording.

Owner DMs are short and in English (the AO workspace language). The channel
posts follow the Late Join Audit style Eve picked on 10/1: little text, one
line per office, names under `>`.
"""
from __future__ import annotations

from typing import Dict, List

from automations.owner_rep_audit import config as C


def first_name(owner: str) -> str:
    return (owner or "").split()[0].title() if owner else "there"


def owner_dm(owner: str, reps: List[str], month: str) -> str:
    lines = "\n".join(f"{i}. {r}" for i, r in enumerate(reps, 1))
    return (f"Hi {first_name(owner)}! Monthly roster check ({month}).\n"
            f"These are the reps still ACTIVE in your OwnerVille:\n\n{lines}\n\n"
            "Reply with the *numbers* of anyone who is no longer with you "
            "(e.g. `3, 7`). If everyone is still active, reply `none`.")


def confirm_prompt(names: List[str], bad: List[int]) -> str:
    who = "\n".join(f"• {n}" for n in names)
    extra = (f"\n_(ignored {', '.join(map(str, bad))}: not on the list)_"
             if bad else "")
    return (f"Got it, these would be removed from Slack and OwnerVille:\n{who}"
            f"{extra}\n\nReply *{C.CONFIRM_WORD}* to confirm, or send the "
            "numbers again to change the list.")


def done(names: List[str]) -> str:
    # Says "OwnerVille will follow" because the OwnerVille retire is still a
    # hand step (config.OV_RETIRE_AUTOMATED) -- never claim a removal that
    # hasn't happened yet.
    return ("Done! Removed from Slack:\n" + "\n".join(f"• {n}" for n in names)
            + "\nOwnerVille will follow. Thanks for keeping things clean!")


def none_ack() -> str:
    return "Thanks! Nobody removed this month."


def unclear() -> str:
    return ("Sorry, I couldn't read that. Reply with the *numbers* from the "
            "list (e.g. `3, 7`), or `none` if everyone is still active.")


def awaiting_remove() -> str:
    return (f"Just checking: reply *{C.CONFIRM_WORD}* to remove the reps "
            "above, or send new numbers to change the list.")


def reminder(owner: str) -> str:
    return (f"Hi {first_name(owner)}, quick reminder about the roster check "
            "above: reply with the numbers of anyone who left, or `none`.")


def thread_title(month: str) -> str:
    return C.THREAD_TITLE.format(month=month)


def thread_intro(month: str) -> str:
    return (f"{thread_title(month)}\n_Informative only. Each owner confirms "
            "their own terminations; Lucy removes them from Slack and "
            "OwnerVille. Nothing to approve here._")


def summary(offices: List[Dict]) -> str:
    """The month's results, edited in place as owners answer.

    offices: [{owner, office, status, removed:[names], confirmed_on}]"""
    done_ = [o for o in offices if o["status"] == "done" and o["removed"]]
    n = sum(len(o["removed"]) for o in done_)
    out = [f"{C.SUMMARY_HEAD}: {n} people removed from AO across "
           f"{len(done_)} offices"]
    for o in done_:
        out.append(f"🏢 *{o['owner']}* ({o['office']}) · Owner confirmed "
                   f"termination {o.get('confirmed_on', '')}".rstrip())
        out += [f"> {name}" for name in o["removed"]]
    clean = [o for o in offices if o["status"] == "done" and not o["removed"]]
    if clean:
        out.append("✅ Nobody left: " + ", ".join(
            f"{o['owner']} ({o['office']})" for o in clean))
    waiting = [o for o in offices if o["status"] != "done"]
    if waiting:
        out.append("⚠️ No reply yet: " + ", ".join(
            f"{o['owner']} ({o['office']})" for o in waiting))
    ov = [n for o in done_ for n in o.get("ov_pending", [])]
    if ov:
        out.append(f"📝 To retire in OwnerVille by hand: {', '.join(ov)}")
    return "\n".join(out)


def pending_for_evelyn(offices: List[Dict]) -> str:
    """Posted (not edited -- an edit doesn't notify) at the close: every owner
    who didn't finish, with the list they were sent, so Evelyn can call them.

    offices: [{owner, office, slack_id, status, reps:[names]}]"""
    out = [f"{C.PENDING_HEAD} <@{C.EVELYN}>: they didn't answer the monthly "
           "roster check (reminder sent). Their lists, to follow up in person:"]
    for o in offices:
        why = {"no_slack": "no Slack account found",
               "unclear": "answered, but unclear",
               "selected": f"picked names, never sent {C.CONFIRM_WORD}"
               }.get(o["status"], "no reply")
        tag = f" <@{o['slack_id']}>" if o.get("slack_id") else ""
        out.append(f"🏢 *{o['owner']}* ({o['office']}){tag} · {why}")
        out += [f"> {i}. {r}" for i, r in enumerate(o["reps"], 1)]
    return "\n".join(out)
