"""Post who still needs doing by hand to #rafs-office-recruiting-11280.

Correct skips are NOT listed — no-shows, terminations, people already marked.
They would bury the names that need acting on, which is the same call
blueink_docs makes and the reason its summary is readable at 8am.
"""
from __future__ import annotations

import os
from typing import List, Tuple

from automations.digi_docs import config

# #rafs-office-recruiting-11280 — confirmed by Megan
# 2026-08-25, not just inherited from blueink_docs because it sits next
# to it. Same room as the other two new-start steps.
CHANNEL = os.environ.get("DIGI_DOCS_SLACK_CHANNEL", "C0AUAS88FGW")
HEADER = "🗂️ Digi Docs"


def post(sent: int, refused: List[str], attested: List[Tuple],
         *, fatal: str = "", dry_run: bool = True) -> bool:
    # NOTHING TO SAY -> SAY NOTHING. Nobody needing documents is a normal quiet
    # week, not news, and "*0* new starts sent digi docs" is exactly the blank
    # board that trains people to stop reading the channel. A run that stopped
    # early is never quiet, so `fatal` counts as something to say even when the
    # counts are zero.
    #
    # `refused` deliberately does NOT count. Every failure has already been
    # posted above, by name, the moment it happened — so a pass that sent
    # nobody and only failed has said everything it has to say, and a summary
    # under it would just be a "*0* sent" line nobody needs.
    if not (sent or fatal):
        print("\n(nothing sent — no Slack summary; any failures were posted as they happened)")
        return False

    # One line, not three. Everything the run did to a person happens together
    # -- the bundle goes out and the boxes get ticked in the same pass -- so
    # splitting it across a headline and a trailing note just made the reader
    # assemble it themselves (Megan 2026-08-25).
    if fatal:
        # The loudest case, and the one that used to be silent: the run threw
        # before it reached this post, so the morning where NOBODY got their
        # documents was the one morning the channel heard nothing. Lead with
        # it -- the count underneath is what got out before it stopped, not a
        # result.
        lines = [f"*Digi Docs stopped before it finished* — {fatal}",
                 f"*{sent}* sent before it stopped; everyone else was not "
                 f"attempted. Needs a re-run."]
    else:
        lines = [f"*{sent}* new start{'' if sent == 1 else 's'} sent digi docs "
                 f">> BG & drug test checked"]
    if fatal:
        # A run that stopped early has no per-person list, but somebody still
        # has to pick it up -- that is the whole point of tagging.
        lines.append("")
        lines.append(_tags())
    # No separate attestation line: the headline above already says the boxes
    # were ticked. The NAMES still matter -- the drug-test box asserts a
    # completed review to AT&T, not a status -- so they stay in the run log,
    # per rep and per box, where they are recoverable without putting thirty
    # names between the reader and the lines they have to act on.

    body = "\n".join(lines)
    if dry_run:
        print(f"\n--- Slack (dry run, NOT posted) -> {CHANNEL} ---")
        print(body)
        return False
    from automations.shared import slack_metrics_post as smp
    smp.post_reply_text_only(body, thread_ts=_thread_ts(smp),
                             channel_id=CHANNEL)
    _mark_reported()
    return True


# Written the moment ANY alert goes out, and read by deploy/digi_docs.sh. It is
# how the wrapper knows a failure has already been reported, so its own
# last-resort alert only fires for a run that died without saying anything --
# killed at a timeout, OOM, the machine going down mid-batch. Without it the
# wrapper would either double-post every ordinary refusal or stay silent for
# exactly the failures nothing else can catch.
REPORTED_MARKER = "output/logs/.digi-docs-reported"


def _thread_ts(smp) -> str:
    """Today's Digi Docs thread ts — the STRING, not the dict around it.

    ensure_named_thread returns {"ok":…, "existed":…, "thread_ts": ts}, and
    both callers here passed that whole dict as thread_ts. Slack answered
    `invalid_thread_ts` every time, so the header posted and the reply under it
    never did — which is why 2026-08-31 8:09 was a bare header with no reply,
    and why nobody had ever seen this thread carry a body."""
    parent = smp.ensure_named_thread(HEADER, channel_id=CHANNEL)
    if isinstance(parent, dict):
        ts = parent.get("thread_ts")
        if not ts:
            raise smp.SlackPostError(f"no thread_ts in {parent!r}")
        return ts
    return parent


def post_added(added: List[str], refused: List[str] | None = None,
               *, dry_run: bool = True) -> bool:
    """Say who was put into OwnerVille, in the day's thread (Megan 2026-08-31).

    The add pass mails nobody, so it used to say nothing at all — and on a
    morning when it died at 5 of 54 the only way to learn that was to read a
    log on the machine it ran on. NEVER posts an empty board: nothing added and
    nothing refused means there was nothing to say."""
    if not added and not refused:
        return False
    lines = [f"*New starts added to OV* — {len(added)} added"]
    lines += [f"• {n}" for n in added]
    if refused:
        lines.append("")
        lines.append(f"*Not added ({len(refused)})* — these will have nothing "
                     f"to generate against when their send comes round:")
        lines += [f"• {r}" for r in refused]
    body = "\n".join(lines)
    if dry_run:
        print(f"\n--- Slack (dry run, NOT posted) -> {CHANNEL} ---")
        print(body)
        return False
    from automations.shared import slack_metrics_post as smp
    smp.post_reply_text_only(body, thread_ts=_thread_ts(smp),
                             channel_id=CHANNEL)
    return True


def _mark_reported() -> None:
    import os
    try:
        os.makedirs(os.path.dirname(REPORTED_MARKER), exist_ok=True)
        with open(REPORTED_MARKER, "w") as fh:
            fh.write("1")
    except Exception:                                       # noqa: BLE001
        pass


def clear_reported() -> None:
    """Called at the START of a run, so the marker only ever describes THIS
    run rather than the last one that failed."""
    import os
    try:
        os.remove(REPORTED_MARKER)
    except Exception:                                       # noqa: BLE001
        pass


def _alerted_today_path() -> str:
    import datetime as _dt
    return f"output/logs/.digi-docs-alerted-{_dt.date.today().isoformat()}.json"


def _already_alerted(line: str) -> bool:
    """Have we already said this today?

    THE SEND PASS IS A TICK NOW. It fires every five minutes all Monday, and a
    failure that persists -- a rep OwnerVille cannot find, a blank Start Time --
    is still true on the next tick and the next. Without this, one such person
    would ping Alisson, Tiff and Aimee roughly 150 times before lunch, and the
    third time is already the point where people mute the channel.

    Keyed on the whole line, so the SAME problem stays quiet while a new one
    still gets through immediately.
    """
    import json
    import os
    path = _alerted_today_path()
    try:
        with open(path) as fh:
            seen = set(json.load(fh))
    except Exception:                                       # noqa: BLE001
        seen = set()
    if line in seen:
        return True
    seen.add(line)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(sorted(seen), fh)
    except Exception:                                       # noqa: BLE001
        pass       # a dedupe we cannot persist must not stop the alert
    return False


def alert_failure(line: str, *, dry_run: bool = True) -> bool:
    """One failure, posted the MOMENT it happens (Megan 2026-08-26: "if
    anything fails it needs to alert right away").

    Waiting for the end of the run was fine when this was one 7:45 batch. It
    is not now: a send goes 30 minutes before that person starts, so a failure
    sitting in a summary until the pass finishes eats the window somebody has
    to fix it in.

    The end-of-run summary still goes out, but it COUNTS these rather than
    repeating them — the same failure twice in one channel is how a channel
    stops being read.
    """
    if not dry_run and _already_alerted(line):
        print(f"  (already alerted today, not repeating: {line[:60]})")
        return False
    body = f"*Digi Docs — could not send* {_tags()}\n• {line}"
    if dry_run:
        print(f"\n--- Slack ALERT (dry run, NOT posted) -> {CHANNEL} ---")
        print(body)
        return False
    from automations.shared import slack_metrics_post as smp
    smp.post_reply_text_only(body, thread_ts=_thread_ts(smp),
                             channel_id=CHANNEL)
    _mark_reported()
    return True


def _tags() -> str:
    """The @-mentions for whoever has to act, or "" if nobody is configured.

    By ID (`<@U...>`), never by @handle: a display-name change silently turns an
    @handle into plain text, and an alert nobody is pinged by is the same as no
    alert at all.
    """
    return " ".join(f"<@{uid}>" for _name, uid in config.ESCALATE_ON_FAILURE)
