"""Tell Evelyn when the PNL hasn't got the week the fill needs.

The report is useless the moment 'Got Paid' for the SOURCE week is empty, and
that failure is silent from the sheet's side: every cell would just read '-'.
The run already refuses to write in that case (run.MIN_REAL_SHARE) — this is
the other half, so somebody hears about it instead of finding out next
Thursday.

Remember the one-week lag when reading the message: it names BOTH weeks,
because "the PNL is missing 8/2" and "the 8/9 column can't be filled" are the
same sentence and quoting only one of them sends people to the wrong column.

Sent as Lucy (the xoxp user token every other Slack post here uses — there is
no bot app on the mini). [[reference_lucy-slack-identity]]

One DM per source week: the orchestrator can run the report more than once in
a morning, and three identical alerts read like three separate outages.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

EVELYN = "U088E2KJEV8"          # Evelyn Sobrino
STATE = Path("output") / "reps_gross_paycheck" / "last_alert.txt"


def _already_sent(source_week: dt.date) -> bool:
    try:
        return STATE.read_text(encoding="utf-8").strip() == source_week.isoformat()
    except Exception:
        return False


def _mark(source_week: dt.date) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(source_week.isoformat(), encoding="utf-8")


def compose(target: dt.date, source: dt.date, cells: int, real: int) -> str:
    md = lambda d: f"{d.month}/{d.day}"      # noqa: E731
    return (
        f"⚠️ *Reps Gross Paycheck records* couldn't run.\n"
        f"*'Got Paid' for WE {md(source)}* in `Raf PNL 2026` looks empty — "
        f"only {real} of {cells} reps carry a number.\n"
        f"That's the week that feeds the *WE {md(target)}* column on the rep "
        f"tabs (the paycheck is always the week before), so nothing was "
        f"written — the tabs are untouched rather than filled with dashes.\n"
        f"Once the PNL has that week, re-run it from the Hub "
        f"(*Reps Gross Paycheck records → Fill This Week*) and it'll catch up."
    )


def notify(target: dt.date, source: dt.date, cells: int, real: int,
           *, dry_run: bool = False) -> bool:
    """DM Evelyn. Returns True if a message went out."""
    if _already_sent(source):
        print(f"  (Evelyn already alerted about WE {source.month}/{source.day})")
        return False
    text = compose(target, source, cells, real)
    if dry_run:
        print("  --- Slack DM to Evelyn (not sent) ---")
        print("  " + text.replace("\n", "\n  "))
        return False
    try:
        from automations.shared import slack_metrics_post as smp
        client = smp._client()
        # Post straight to the user id. The obvious route — conversations.open
        # then post to the channel it hands back — needs the `im:write` scope,
        # which the Lucy token does NOT carry (checked 2026-08-07: it has
        # chat:write, mpim:write, files:write, but no im:write, so the open
        # call 400s with missing_scope). Posting to the user id works on
        # chat:write alone. conversations.open stays as the fallback for a
        # token that has it.
        try:
            client.chat_postMessage(channel=EVELYN, text=text)
        except Exception:                               # noqa: BLE001
            channel = client.conversations_open(users=EVELYN)["channel"]["id"]
            client.chat_postMessage(channel=channel, text=text)
    except Exception as e:                              # noqa: BLE001
        # A failed alert must not also fail the report — the refusal to write
        # is the real protection; this is the notification on top of it.
        print(f"  ⚠ couldn't DM Evelyn ({type(e).__name__}: {str(e)[:120]})")
        return False
    _mark(source)
    print("  DM'd Evelyn: the PNL is missing the source week")
    return True
