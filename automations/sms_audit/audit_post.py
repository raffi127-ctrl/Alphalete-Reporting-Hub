"""The booking-call audit, posted to each account's own Slack channel.

Raf via Megan, 2026-10-20: a DAILY audit so the day's offenders get coached
the same day, and a WEEKLY overall after it. One channel per AppStream
account, named for the account number.

ONE SHORT HEADER, EVERYTHING ELSE IN THE THREAD. Raf does not read long
header posts and the header is what the whole channel sees in their sidebar.
So the parent is a title and nothing else; the day's numbers are the first
reply and each flagged person gets their own reply after that.
[[feedback_short_header_posts]] [[feedback_clean_parent_posts]]

WHAT GETS FLAGGED, AND WHY IT IS NOT THE SCORE. Four separate tests on 857
graded calls found that nothing in how the call is run predicts whether the
applicant turns up -- not the script, not the caller, not the lead time for
phone bookings, not reply speed. So a scorecard built on the rubric would be
measuring compliance while implying it drives show-up, and the first person
to raise their score without raising their shows would stop believing it.

This flags COMPLIANCE instead: things that are wrong whether or not they
move the number. Saying the old office address is wrong because the
applicant drives to the wrong city. Calling it a retail job is wrong because
it is not one. Those need no statistical defence.

The account-level numbers DO carry the one thing that predicts show-up --
whether the applicant ever texted back -- because that is where the lever
actually is. [[project_ringover_call_audit]]

    python -m automations.sms_audit.audit_post --office 11280            # print
    python -m automations.sms_audit.audit_post --office 11280 --post     # send
    python -m automations.sms_audit.audit_post --office 11280 --weekly

READ-ONLY on every source. Posts nothing without --post.
"""
from __future__ import annotations  # Lucy runs Python 3.9 -- keep lazy

import argparse
import collections
import datetime as dt
import json
import sys
from pathlib import Path

from automations.sms_audit import call_grade as G

GRADES = (Path(__file__).resolve().parents[2]
          / "output" / "call_audit" / "sept" / "grades")

# Account -> (owner, Slack channel). resources/owner-slack-ids.md is the
# canonical list; 23965 and 24065 have no channel yet and are skipped with a
# printed reason rather than posted somewhere arbitrary.
ACCOUNTS = {
    "11280": ("Rafael Hidalgo", "C0AUAS88FGW"),
    "11580": ("Carlos Hidalgo", "C09L1S3MQ1E"),
    "23965": ("Tiffani Brown", "C0CAV0P4RRS"),
    # Keyed on the ACCOUNT number, which is what the bookings, the SMS
    # log and the grades are all keyed on. (This channel read 24064
    # until Megan renamed it 2026-10-20; the id was unaffected.)
    "24065": ("Maria Quintero", "C0CBLLEF2CQ"),
}

# The red-flag items worth waking someone up about. Deliberately a SUBSET of
# the rubric's red flags: these are factually wrong, not merely off-script.
FLAGS = ("wrong_place", "retail", "base_pay", "quoted_pay", "nine_to_five",
         "unsure")

# SPOKEN NAME -> THE PERSON ON THE ROSTER.
#
# The roster is not a guess: it is the 26 distinct `sent_by` values on
# 11280's SMS log. Every merge below is a spoken name that (a) is on ONE
# Ringover line 100% of the time and (b) matches a real sender on that
# account. Counts are from 789 graded calls.
#   George  n=164  Jorge Pena's line      -> Jorge Pena (anglicised)
#   Danny   n= 37  Rafael Hidalgo's line  -> Dani Pena
#   Mariana n= 25  Rafael Hidalgo's line  -> Mariana Gamboa
#   Dulce   n=  5  Rafael Hidalgo's line  -> Dulce Lamb APT
#   Letty / Lettie / Luddy / Leslie       -> Leticia Robinson
#
# Leslie (n=58) is the one inference rather than a match: there is no
# Leslie among the 26 senders, she is on Leticia Robinson's line 100% of
# the time, and Lettie and Luddy are already Whisper mis-hearings of the
# same person off the same line. If a real Leslie turns up, split it.
#
# NOTE the two spellings: the roster says "Leticia Robinson", Ringover
# says "Letty Robinson". [[feedback_alias_list]]
CANON = {"George": "Jorge Pena",
         "Danny": "Dani Pena",
         "Mariana": "Mariana Gamboa",
         "Dulce": "Dulce Lamb APT",
         "Letty": "Leticia Robinson", "Lettie": "Leticia Robinson",
         "Luddy": "Leticia Robinson", "Leslie": "Leticia Robinson",
         "Letty Robinson": "Leticia Robinson"}

# NOT RECRUITERS. Megan 2026-10-20: "Taylor and corey were testing for
# CS calls". Their calls are not recruiting calls, so they are dropped
# from the audit entirely rather than merely left unmerged — grading a
# customer-service test against a booking-call rubric is noise, and it
# would put two people at the top of an offenders list they do not
# belong on.
NOT_RECRUITING = {"Taylor", "Corey", "Korea", "Square", "Cory"}

# "this is who", "this is how", "this is for" -- the intro regex catches
# these and they are not people. A real name also recurs; a one-off is
# far more likely a mis-hearing than a caller.
NOT_A_NAME = {"who", "how", "what", "for", "the", "mr", "mrs", "miss",
              "a", "an", "and", "but", "so", "it", "that", "this",
              "there", "here", "just", "still", "going", "called"}
MIN_CALLS = 3
# How many people get their own reply before the rest are one line.
MAX_PEOPLE = 5
# Marks the DAY STREAK — a calendar, because it counts DAYS. Not a flag:
# "flags" is what the day's findings are called, and using the same
# symbol for both is what made the first version unreadable.
STREAK_MARK = "\U0001F4C5"


def _spoken(rec):
    n = (rec.get("said_their_name") or "").strip()
    if n.lower() in NOT_A_NAME:
        return ""
    return CANON.get(n, n)


def is_recruiting(rec):
    """False for the CS test calls, which are not recruiting at all."""
    return (rec.get("said_their_name") or "").strip() not in NOT_RECRUITING


def _who(rec, seen=None):
    """Who to credit the call to.

    The spoken name when there is a believable one, else the Ringover
    line. The line is NOT the person -- Raf's line alone is used by
    three different callers -- so the spoken name wins when we have it."""
    n = _spoken(rec)
    if n and (seen is None or seen.get(n, 0) >= MIN_CALLS):
        return n
    return (rec.get("line") or "unknown")


def _roster(rows):
    """How often each spoken name appears, so a one-off mis-hearing does
    not become a person with a scorecard."""
    c = collections.Counter()
    for r in rows:
        n = _spoken(r)
        if n:
            c[n] += 1
    return c


def load(office, day=None):
    """Graded calls for one account, optionally one day.

    CS test calls are not recruiting calls and never reach the audit."""
    out = []
    for f in sorted(GRADES.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("skip") or d.get("office") != office:
            continue
        if day and (d.get("when") or "")[:10] != day.isoformat():
            continue
        if not is_recruiting(d):
            continue
        out.append(d)
    return out


def offenders(rows):
    """{person: [(flag, quote, at, uuid)]} -- only the factual flags."""
    seen = _roster(rows)
    by = collections.defaultdict(list)
    for r in rows:
        for key in FLAGS:
            it = (r.get("items") or {}).get(key) or {}
            if it.get("happened"):
                by[_who(r, seen)].append((key, (it.get("quote") or "").strip(),
                                    (it.get("at") or "").strip(), r.get("uuid")))
    return by


def week_days(day):
    """The Mon-Fri of `day`'s week, up to and including it."""
    monday = day - dt.timedelta(days=day.weekday())
    out = []
    for i in range(5):                       # Mon..Fri only
        d = monday + dt.timedelta(days=i)
        if d <= day:
            out.append(d)
    return out


def streaks(office, day):
    """{person: days flagged IN A ROW ending today}, Mon-Fri, max 5.

    Megan 2026-10-20: "red flag emojis for how many days in a row they
    have been flagged M-F so up to 5 flags and reset". So the count is
    a streak, not a tally: flagged Mon, Tue, clean Wed, flagged Thu is
    a streak of ONE on Thursday, because the point is to show who is
    still doing it after being told, not who has ever done it. It
    starts again every Monday."""
    days = week_days(day)
    flagged_on = {}
    for d in days:
        flagged_on[d] = set(offenders(load(office, d)))
    out = {}
    for person in flagged_on.get(day, set()):
        run = 0
        for d in reversed(days):             # today backwards
            if person in flagged_on[d]:
                run += 1
            else:
                break
        out[person] = min(run, 5)
    return out


def summary(rows):
    """The first reply: the day in a few lines, with the one number that
    actually predicts show-up rather than the rubric score."""
    n = len(rows)
    flagged = len(offenders(rows))
    seen = _roster(rows)
    people = len({_who(r, seen) for r in rows})
    clean = sum(1 for r in rows
                if not any((r.get("items") or {}).get(k, {}).get("happened")
                           for k in FLAGS))
    # Labelled, because this thread is the whole recruiting audit, not
    # just the calls: texts, AppStream settings and the
    # confirmation-call check are sections that join it here.
    out = ["*Booking calls* — {} audited · {} caller{} · {} clean, "
           "{} with a flag"
           .format(n, people, "" if people == 1 else "s", clean, n - clean)]
    shown = [r for r in rows if r.get("shown") is not None]
    if shown:
        s = sum(1 for r in shown if r["shown"])
        out.append("Of the {} with a known outcome so far, {:.0f}% showed."
                   .format(len(shown), 100.0 * s / len(shown)))
    if flagged:
        out.append("{} caller{} below.".format(
            flagged, "" if flagged == 1 else "s"))
    return "\n".join(out)


def person_block(name, hits, streak=0):
    """One reply per flagged caller: what they said, and when they said it.

    The quote is the point. "You named a location on 3 calls" is an argument;
    "We are located in Irving, Texas, at 0:31" is a fact."""
    # TWO COUNTS, SO TWO SYMBOLS. Megan 2026-10-20: "calling both
    # flags and then using a flag to mark the day is confusing" —
    # and on the row that prompted it both numbers were 4, so there
    # was no telling them apart. The calendars count DAYS IN A ROW,
    # the flags are what they did wrong today, and each number says
    # in words which one it is.
    lines = []
    head = "*{}* — {} flag{} today".format(
        name, len(hits), "" if len(hits) == 1 else "s")
    if streak > 1:
        head = "{} {}  ·  {} days in a row".format(
            STREAK_MARK * streak, head, streak)
    lines.append(head)
    seen = collections.Counter(h[0] for h in hits)
    for key, cnt in seen.most_common():
        lines.append("• {}{}".format(G.SHORT.get(key, key),
                                     "" if cnt == 1 else " ×{}".format(cnt)))
    for key, quote, at, _uuid in hits[:3]:
        if quote:
            lines.append("> _{}_{}".format(quote[:160],
                                           "  ({})".format(at) if at else ""))
    return "\n".join(lines)


def _ordinal(n):
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return "{}{}".format(n, suf)


def header(office, day=None, weekly=False):
    """Megan 2026-10-20: "Recruiting Audit Mon 18th - 11280 (Rafael
    Hidalgo)". The date sits INSIDE the title, not appended after it,
    so this does not use ensure_named_thread's dated header.

    No leading emoji, deliberately. Slack stores a literal emoji as its
    :shortcode:, the header lookup then never matches its own post, and
    the report posts a fresh thread every run — five of them in this
    same channel on 2026-09-07."""
    day = day or dt.date.today()
    owner, _ch = ACCOUNTS.get(office, (office, ""))
    when = ("Week to {} {}".format(day.strftime("%b"), _ordinal(day.day))
            if weekly else
            "{} {}".format(day.strftime("%a"), _ordinal(day.day)))
    return "Recruiting Audit {} - {} ({})".format(when, office, owner)


def build(office, day=None, weekly=False):
    """(title, [reply, ...]) or (None, why) when there is nothing to post."""
    rows = load(office, day)
    if not rows:
        return None, ("no graded calls for {} on {}"
                      .format(office, day or "the window"))
    title = header(office, day, weekly)
    run = streaks(office, day) if (day and not weekly) else {}
    return title, compose(rows, run)


def compose(rows, run=None):
    """The thread: the day in one reply, then the worst few callers.

    `run` is {person: days in a row flagged}; worst streak first, then
    most flags today."""
    run = run or {}
    replies = [summary(rows)]
    # Worst first, and capped. A thread with twenty replies is a long
    # post wearing a disguise, and nobody coaches twenty people in a
    # day. [[feedback_short_header_posts]]
    ranked = sorted(offenders(rows).items(),
                    key=lambda kv: (-run.get(kv[0], 0), -len(kv[1])))
    for name, hits in ranked[:MAX_PEOPLE]:
        replies.append(person_block(name, hits, run.get(name, 0)))
    rest = ranked[MAX_PEOPLE:]
    if rest:
        replies.append("_Also flagged, fewer each:_ {}".format(
            ", ".join("{} ({})".format(n, len(h)) for n, h in rest)))
    return replies


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--office", default="11280", help="account number")
    ap.add_argument("--date", default="", help="YYYY-MM-DD, default all")
    ap.add_argument("--weekly", action="store_true")
    ap.add_argument("--post", action="store_true",
                    help="actually send it; without this it only prints")
    a = ap.parse_args(argv)
    day = dt.date.fromisoformat(a.date) if a.date else None

    title, replies = build(a.office, day, a.weekly)
    if title is None:
        # [[feedback_never_post_blank]] -- a day with nothing audited is not
        # a day worth posting an empty board about.
        print("[audit_post] nothing to post: {}".format(replies))
        return 0

    channel = ACCOUNTS.get(a.office, ("", ""))[1]
    print("HEADER: {}".format(title))
    for r in replies:
        print("\n--- thread reply ---\n{}".format(r))
    if not a.post:
        print("\n[audit_post] print only. --post to send to {}"
              .format(channel or "(no channel)"))
        return 0
    if not channel:
        print("[audit_post] {} has no Slack channel in ACCOUNTS -- not posted."
              .format(a.office), file=sys.stderr)
        return 1

    from automations.shared import slack_metrics_post as SP
    head = SP.ensure_named_thread(title, channel_id=channel)
    ts = head.get("thread_ts")
    if not ts:
        print("[audit_post] no thread ts: {}".format(head), file=sys.stderr)
        return 1
    for r in replies:
        SP.post_reply_text_only(r, thread_ts=ts, channel_id=channel)
    print("[audit_post] posted {} repl{} to {}".format(
        len(replies), "y" if len(replies) == 1 else "ies", channel))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
