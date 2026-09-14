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
#
# THIS IS THE CHANNEL FOR WORK, NOT FOR FAULTS. It is an OFFICE channel: the
# people in it act on "here is who still needs doing by hand". They are not the
# people who fix a crashed run.
CHANNEL = os.environ.get("DIGI_DOCS_SLACK_CHANNEL", "C0AUAS88FGW")

# WHERE RUN-LEVEL FAULTS GO (Megan 2026-09-02: "if something is an error it goes
# into the correct channel"). #claudecorrections-and-requests — the standing home
# for the day's failures, where they are triaged, marked :pending: while someone
# works them, and closed with a ✅.
#
# WHAT WENT WRONG. alert_failure() posted to CHANNEL, so on 2026-09-02 a crashed
# run put "Digi Docs — could not send @Alisson Rodriguez @tiff @Aimee Garibay •
# the run was killed before it could report — exit 1, see output/logs/…" into
# Raf's office channel, @-ing three people over a log file on a machine they do
# not have. In an office channel a stack-trace-shaped message is noise that
# trains people to stop reading the room where their actual to-do list lands —
# and the send pass is a 5-minute tick, so a persistent fault would have kept
# doing it (only _already_alerted held it to one).
#
# THEN IT OVERCORRECTED (Megan 2026-09-07: "this posted in the wrong channel —
# it should be in the 11280 channel"). The 09-02 fix moved EVERY alert here,
# including the per-person ones, so "Ly Quan Milligan: not in the Add Sales Rep
# employee list" landed in corrections. That is not a fault — nothing is broken
# and there is nothing to triage. It is one name that needs a human in Raf's
# office to add them, i.e. exactly the "who still needs doing by hand" this
# report exists to publish, and in corrections the people who can act on it
# never see it.
#
# THE SPLIT, and it is about WHO ACTS, not about severity:
#   fault=True  -> here. The RUN broke: killed, OOM, exit non-zero, machine
#                  down. Whoever fixes Lucy 3 acts. Nobody in the office can.
#   fault=False -> the office channel, in today's thread, next to the summary.
#                  One PERSON could not be processed. Someone in 11280 acts.
ALERT_CHANNEL = os.environ.get("DIGI_DOCS_ALERT_CHANNEL", "C0BK5PRG259")
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


# TODAY'S THREAD, RESOLVED ONCE PER RUN. Not a cache for speed — it is what
# stops the channel being flooded. See _thread_ts.
_THREAD_TS = None


def _thread_ts(smp) -> str:
    """The ts of today's Digi Docs header. One per RUN, whatever happens.

    Two bugs met here on 2026-08-31 and the second only became visible when the
    first was fixed.

    1. ensure_named_thread returns {"ok":…, "existed":…, "thread_ts": ts}, and
       both callers passed that whole DICT as thread_ts. Slack answered
       `invalid_thread_ts` every time, so the header posted and the body under
       it never did — this thread had never once carried a reply.

    2. _refuse alerts on EVERY refusal, by design (Megan 2026-08-26: "if
       anything fails it needs to alert right away"). Each alert called
       ensure_named_thread, whose search does not find a header posted seconds
       earlier — so each one posted its OWN header. With bug 1 in place that
       was an occasional orphan header nobody noticed. Fix bug 1 alone and a
       run that refuses fifty people posts fifty headers, each tagging three
       people, thirteen seconds apart. It did.

    So resolve it ONCE and hold it for the process. Every later alert in the
    same run replies under the same header, however many there are.

    3. A PROCESS IS NOT A DAY (Megan 2026-09-07: "this shouldn't have 2 threads
       in the 11280 channel"). The send pass is a five-minute tick, so every
       firing is a NEW process with an empty _THREAD_TS, and each one asks
       ensure_named_thread again. That search is a conversations_history scan
       for today's dated header — and when it comes back empty, for any reason
       at all, the answer is to POST ANOTHER HEADER. It did: 12:13 PM and
       12:43 PM, two "Digi Docs — September 7th 2026" threads in the same
       channel, replies split across both.

       So the ts is written down for the DAY, not held for the process. The
       first tick that needs a thread resolves it and records it; every later
       tick today reads the file and never searches at all. A search that can
       fail open cannot be the thing standing between us and a duplicate
       header."""
    global _THREAD_TS
    if _THREAD_TS:
        return _THREAD_TS
    import os
    path = _thread_marker_path()
    try:
        with open(path) as fh:
            ts = fh.read().strip()
        if ts:
            _THREAD_TS = ts
            return ts
    except Exception:                                       # noqa: BLE001
        pass            # no marker yet, or unreadable — resolve it below
    parent = smp.ensure_named_thread(HEADER, channel_id=CHANNEL)
    ts = parent.get("thread_ts") if isinstance(parent, dict) else parent
    if not ts:
        raise smp.SlackPostError(f"no thread_ts in {parent!r}")
    _THREAD_TS = ts
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(str(ts))
    except Exception:                                       # noqa: BLE001
        pass    # worst case the next tick searches, exactly as it used to
    return ts


def _thread_marker_path() -> str:
    """Today's Digi Docs thread ts. Dated, so tomorrow starts a new thread on
    its own and nothing has to clean this up."""
    import datetime as _dt
    return f"output/logs/.digi-docs-thread-{_dt.date.today().isoformat()}"


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

    Keyed on the line with its NUMBERS removed, so the same problem stays quiet
    while a new one still gets through immediately.

    The numbers have to go (2026-08-31). "the 'Start Time' column is not on
    this tab — 31 people cannot be scheduled" is one problem, but the count
    moves as the chart is edited, and a key that includes it makes 30 and 31
    two different problems: the tick re-posted the same missing column all
    afternoon while Megan deleted them. Same sentence, different number, same
    problem.

    KEY ON THE PERSON, NOT THE SENTENCE (2026-09-14). Normalising the numbers
    was not enough once the refusal started carrying evidence: "(saw 584
    option(s); 0 share the surname 'garvin'; closest: 'Alysia Garcia')" has a
    different closest-list on almost every tick, because the directory grows as
    people are added. Fifteen people produced THIRTY-SIX posts in one thread,
    each one a paragraph tagging the same three people -- past the point where
    anybody reads any of them, which is the exact failure this function exists
    to prevent. A person plus what went wrong IS the problem; the evidence is
    just how we phrased it that minute.
    """
    import json
    import os
    path = _alerted_today_path()
    try:
        with open(path) as fh:
            seen = set(json.load(fh))
    except Exception:                                       # noqa: BLE001
        seen = set()
    who = (line or "").split(":", 1)[0].strip()
    key = f"{who}|{headline_and_need(line)[0]}" if who else (line or "")
    if key in seen:
        return True
    seen.add(key)      # store the KEY, not the line, or nothing dedupes
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(sorted(seen), fh)
    except Exception:                                       # noqa: BLE001
        pass       # a dedupe we cannot persist must not stop the alert
    return False


def headline_and_need(line: str):
    """(headline, what-is-needed) for ONE failure line.

    Its own function so the same words can be applied to a message that
    ALREADY went out. Today's thread was posted before these branches
    existed, and rewording the code without rewording the fifteen posts
    sitting in front of the office leaves them reading the old sentence.
    """
    low = (line or "").lower()
    need = ""
    if "bundle sent" in low:
        head = "Digi Docs — SENT, but the attestation boxes are not ticked"
    elif "not sent and not finished" in low:
        head = "Digi Docs — not sent, and nothing will retry it"
    elif "employees match" in low or "employee id" in low:
        head = "Digi Docs — two people in OwnerVille share this name"
        need = ("*What's needed:* find the right person's employee id in the "
                "OwnerVille directory and reply with it here — we will not "
                "guess between two people, because the wrong one is somebody "
                "else's contract. Nothing has been sent to them.")
    elif "add sales rep" in low:
        head = "Digi Docs — needs adding to OwnerVille before anything can send"
        need = ("*What's needed:* add them in OwnerVille → *Add Sales Rep*, "
                "campaign *RES-AT&T*. Nothing has been sent to them and "
                "nothing can be until they exist there. Once they do, the "
                "next pass picks them up and sends on its own — no re-run "
                "needed. It stops at *4:00pm*; after that nobody is sent "
                "automatically.")
        # NOT "the 5-minute pass" (2026-09-14). The tick FIRES every five
        # minutes, but a pass working a full cohort runs about twenty, and one
        # cannot start while another holds the browser — so somebody added
        # mid-pass waits for the next one, not for five minutes. Telling the
        # office five is how a working system looks broken at minute six.
    else:
        head = "Digi Docs — could not send"
    return head, need


def post_add_summary(ready: int, total: int, failed: List[str], *,
                     dry_run: bool = True) -> bool:
    """One line at the end of the 10:30 pass: how many are in OwnerVille, and
    when their documents go.

    Megan 2026-09-14: "it should alert #/# added to OV and will be send digi
    docs 30min prior to start time or something like that."

    WHY A COUNT AND NOT A LIST. The question anybody has at 10:30 is whether
    this morning's people are going to get their documents. "46/48" answers it
    in one glance. The names only matter for the two who did not make it, and
    those are the only ones that pull an @-mention — which is the whole lesson
    of 9/14, when fifteen names became thirty-six posts and tagged the same
    three people on every one.

    IT POSTS EVEN WHEN EVERYTHING WORKED, unlike most of this report. A clean
    count is not a blank board: it is the confirmation that the morning is
    handled, and it is what makes its ABSENCE meaningful — no post at 10:30
    means the pass did not run at all, which is worth noticing.
    """
    ready = max(0, int(ready))
    total = max(0, int(total))
    head = f"*{HEADER} — {ready}/{total} in OwnerVille*"
    lines = [head,
             "Their documents go out 30 minutes before each start time."]
    if failed:
        lines.append(f"\n*Could not add* ({len(failed)}):")
        lines += [f"   • {f}" for f in failed]
        # THE RECOVERY, SAID ONCE (Megan 2026-09-14: "it also needs to say in
        # the alert, if these get manually added to the onboarding page before
        # their start time then Lucy will still send them their bundles").
        #
        # It is the most useful sentence in the post and the least obvious:
        # every name above looks like a dead end, and on 9/14 the office spent
        # the afternoon assuming each hand-add also needed somebody to come
        # back and re-run something. It does not. `roster.due_now` counts
        # anyone whose send moment has ARRIVED, so a person added at noon is
        # picked up by the next tick and sent, with nothing asked of anybody.
        #
        # The 4pm stop is part of the same sentence on purpose. Without it this
        # reads as "any time is fine", and a 4:15 add would silently get
        # nothing -- which is the one way this promise could become untrue.
        # WHAT THE ADMINS ARE TOLD (Megan 2026-09-14: "the admins just need
        # to be told to get them added 30 min prior to their start time").
        #
        # The system is in fact more forgiving — due_now counts anyone whose
        # send moment has ARRIVED, so a 12:00 start added at 2pm still goes,
        # which is what rescued most of 9/14. But an instruction and a
        # tolerance are different things, and the instruction has to produce
        # the outcome we actually want: the rep holding their documents when
        # they walk in, not receiving them at 3pm on their first day.
        #
        # The 4:00pm line stays because it is the one real cliff. Past it
        # nothing goes at all, and somebody adding a person at 4:15 in good
        # faith would otherwise never find out.
        lines.append(
            "\n_Add them in OwnerVille at least *30 minutes before their start "
            "time* and Lucy sends their bundle automatically — nothing to "
            "re-run and nobody to tell. Nothing goes out after *4:00pm*._")
        lines.append(_tags())
    body = "\n".join(l for l in lines if l).rstrip()
    if dry_run:
        print(f"\n--- Slack add summary (dry run, NOT posted) ---\n{body}")
        return False
    from automations.shared import slack_metrics_post as smp
    try:
        smp.post_reply_text_only(body, thread_ts=_thread_ts(smp),
                                 channel_id=CHANNEL)
    except Exception as e:                                  # noqa: BLE001
        print(f"  (add summary to {CHANNEL} FAILED: "
              f"{type(e).__name__}: {str(e)[:120]})")
        return False
    _mark_reported()
    return True


def alert_failure(line: str, *, fault: bool = False,
                  dry_run: bool = True) -> bool:
    """One failure, posted the MOMENT it happens (Megan 2026-08-26: "if
    anything fails it needs to alert right away").

    Waiting for the end of the run was fine when this was one 7:45 batch. It
    is not now: a send goes 30 minutes before that person starts, so a failure
    sitting in a summary until the pass finishes eats the window somebody has
    to fix it in.

    The end-of-run summary still goes out, but it COUNTS these rather than
    repeating them — the same failure twice in one channel is how a channel
    stops being read.

    `fault` picks the room, by WHO CAN ACT on the line (see ALERT_CHANNEL):
    the default False is a per-person refusal and belongs in the office
    channel's thread; True is the run itself breaking and belongs in
    corrections. Only the wrapper's last-resort alert passes True.
    """
    if not dry_run and _already_alerted(line):
        print(f"  (already alerted today, not repeating: {line[:60]})")
        return False
    # THE HEADLINE HAS TO MATCH THE LINE (Megan 2026-08-31). Every alert said
    # "could not send", including the ones whose body said the bundle WAS sent
    # and only the attestation boxes failed — a headline contradicting its own
    # first line is how a day of "nothing went out" got believed. The line
    # knows what happened; read it.
    #
    # AND AN ADD FAILURE IS NOT A SEND FAILURE (Megan 2026-09-14, reading the
    # thread: "why did it post that in the slack already if nothing has been
    # sent?"). Fifteen people who could not be ADDED to OwnerVille at 11:00 —
    # ninety minutes before the first bundle was even due — were announced as
    # "could not send", because an add refusal matched neither branch above and
    # fell through to the default. The thread read as a cohort whose documents
    # had failed to go out. Nothing had been attempted yet.
    #
    # These also get a WHAT'S NEEDED line. "not in the Add Sales Rep employee
    # list" describes what the page did; it does not tell the three people
    # tagged underneath what to do about it, and they are the whole reason the
    # message is in their channel rather than in corrections.
    head, need = headline_and_need(line)
    # NAME THE REPORT, but only where it is not already named. In the office
    # channel this hangs under the "🗂️ Digi Docs" header, which says it for us;
    # in corrections it sits among every other report's failures, so there the
    # line has to identify itself.
    #
    # THE TAGS STAY, BUT NOT ON THE HEADLINE (2026-09-07). Alisson/Tiff/Aimee
    # are pinged on every refusal on purpose (Megan 2026-08-26: a failure has to
    # get picked up fast), and moving the message into their own office channel
    # does not change that. What had to change is WHERE they sit: "*Digi Docs —
    # could not send* @Alisson @tiff @Aimee" reads as three people who did not
    # get documents, directly above a bullet naming a fourth person who is the
    # one who actually failed. Under the line instead, they read as what they
    # are — who should pick it up.
    if fault:
        body = f"*{head}* {_tags()}\n• {line}"
    else:
        # The ask goes ABOVE the tags, so the last thing read before the names
        # is what those names are being asked to do.
        body = f"*{head}*\n• {line}\n"
        if need:
            body += f"{need}\n"
        body = (body + _tags()).rstrip()
    channel = ALERT_CHANNEL if fault else CHANNEL
    if dry_run:
        print(f"\n--- Slack ALERT (dry run, NOT posted) -> {channel} ---")
        print(body)
        return False
    from automations.shared import slack_metrics_post as smp
    try:
        if fault:
            # A FAULT GOES TO THE FAULT CHANNEL, as its OWN top-level message.
            # Top-level because that is the corrections channel's convention:
            # one message per failure, so it can be triaged, marked :pending:
            # while somebody works it, and closed with a ✅.
            #
            # chat_postMessage direct, the same way appstream_watch._alert
            # posts there: slack_metrics_post's helpers are all thread-reply
            # shaped, and there is no thread to reply to here.
            smp._client().chat_postMessage(channel=ALERT_CHANNEL, text=body)
        else:
            # A PERSON GOES IN TODAY'S THREAD, under the one header, beside the
            # summary that counts them. Never top-level: the send pass is a
            # 5-minute tick and fifty refusals as fifty top-level posts is the
            # flood _thread_ts was written to stop.
            smp.post_reply_text_only(body, thread_ts=_thread_ts(smp),
                                     channel_id=CHANNEL)
    except Exception as e:  # noqa: BLE001
        # NEVER let a failed alert take down the run it is reporting on — but do
        # not swallow it either: an alert nobody sees is the same as no alert.
        print(f"  (Digi Docs alert to {channel} FAILED: "
              f"{type(e).__name__}: {str(e)[:120]})")
        return False
    _mark_reported()
    return True


def _tags() -> str:
    """The @-mentions for whoever has to act, or "" if nobody is configured.

    By ID (`<@U...>`), never by @handle: a display-name change silently turns an
    @handle into plain text, and an alert nobody is pinged by is the same as no
    alert at all.
    """
    return " ".join(f"<@{uid}>" for _name, uid in config.ESCALATE_ON_FAILURE)
