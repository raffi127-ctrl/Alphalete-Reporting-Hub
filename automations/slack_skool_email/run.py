"""Slack / Skool email -- 8am Monday, to this week's new starts.

    # who WOULD get it, and the exact message. Sends nothing.
    python -m automations.slack_skool_email.run

    # land it in reception's Drafts for a human to eyeball and press send
    python -m automations.slack_skool_email.run --draft

    # send it for real, then post the summary to Slack
    python -m automations.slack_skool_email.run --send --slack

DRY RUN IS THE DEFAULT. Nothing leaves the mailbox without --send.

The roster, and who is skipped, is deliberately the SAME reading Blue Ink uses
(automations.blueink_docs.roster) rather than a second parser over the same
tab. That module already survived the two bugs these tabs cause -- a chart runs
to a BLANK row, and a second chart can inherit the first's header -- and a
person who is not starting should not be told "see you at orientation today"
any more than they should be mailed a contract. One reading, one answer.
"""
from __future__ import annotations

import argparse
import sys
from typing import List

from automations.slack_skool_email import config, message


def _open_tab(tab_name: str = ""):
    from automations.recruiting_report.fill import open_by_key
    from automations.blueink_docs import roster as bir
    wb = open_by_key(config.SHEET_ID)
    ws = bir.current_tab(wb, tab_name)
    return ws, ws.get_all_values()


def _people(tab_name: str = ""):
    from automations.blueink_docs import roster as bir
    ws, values = _open_tab(tab_name)
    people = bir.parse_tab(values, ws.title)
    # Their own start date, off the chart each of them sits in. The day this
    # email names comes from here, so it is attached before anybody is
    # grouped (Megan, 2026-11-18: "change the day to be correct for when they
    # actually start").
    bir.attach_chart_dates(values, people, ws.title)
    return ws, values, people


def _no_email(people):
    """People who SHOULD have been emailed and couldn't be.

    Deliberately narrower than "wasn't sent". Someone who quit, failed their
    background check or declined Friday is the report working, and listing
    fourteen of them every Monday buries the one name that needs a human. What
    belongs here is only the person nobody decided to exclude -- they are
    starting on Monday and the sheet just has no usable address for them, so
    they will turn up having installed nothing and nobody will know why.

    Returns [(name, row, reason)].
    """
    out = []
    for p_ in people:
        why = (p_.skip_reason or "")
        if "email" in why.lower():
            out.append((p_.name, p_.row, why))
    return out


def _recipients(people) -> List[str]:
    """Eligible addresses, de-duplicated, order preserved.

    Duplicates are real: someone added to both of Monday's charts would
    otherwise get two copies of the same email.
    """
    seen, out = set(), []
    for p in people:
        if not p.eligible:
            continue
        addr = (p.email or "").strip()
        key = addr.lower()
        if addr and key not in seen:
            seen.add(key)
            out.append(addr)
    return out


def _groups(people, today=None):
    """[(start_date, [address, ...])] for everybody due, earliest day first.

    ONE GROUP PER START DATE, because the email names the day and every
    recipient of one BCC reads the same sentence. Two people starting on
    different days cannot share a send any more -- that is the whole change.

    Only people who are DUE: their floor is SEND_LEAD_DAYS before their own
    start (automations.shared.new_start_timing). Somebody starting later is
    not here yet and will be on a later morning's run.

    A person with no readable start date is left out and reported by
    `_undated` rather than quietly folded into the nearest group. An email
    that names the wrong day is worse than one that is late.
    """
    import datetime as _dt

    from automations.shared import new_start_timing as timing

    today = today or _dt.date.today()
    by_day = {}
    seen = set()
    for p_ in people:
        if not p_.eligible:
            continue
        addr = (p_.email or "").strip()
        key = addr.lower()
        if not addr or key in seen:
            continue                      # same de-dupe as _recipients
        if not isinstance(p_.chart_date, _dt.date):
            continue
        if p_.chart_date < today:
            continue                      # see _already_started
        if not timing.due(p_.chart_date, today, config.SEND_LEAD_DAYS):
            continue
        seen.add(key)
        by_day.setdefault(p_.chart_date, []).append(addr)
    return sorted(by_day.items())


def _already_started(people, today=None):
    """Eligible people whose start day has already passed. They get nothing.

    THE ONE PLACE THIS EMAIL DIFFERS FROM THE PAPERWORK. `new_start_timing`
    treats the lead as a floor and keeps saying "due" after somebody's start,
    which is right for Blue Ink -- an unsigned I-9 does not stop mattering
    because Monday happened. It is wrong here: this email says "we're excited
    to have you at orientation on Monday, November 16", and sending that on
    the Wednesday after is worse than sending nothing.

    Caught by the live preview on 2026-11-18, where the newest tab was still
    dated 11.16 and the grouping had cheerfully lined up 46 people for an
    email naming a day that had gone. `_wrong_week` would have stopped the
    send that time, but that is a gate on the TAB -- the per-person rule is
    what decides now, so it has to hold on its own.
    """
    import datetime as _dt
    today = today or _dt.date.today()
    return [p_ for p_ in people
            if p_.eligible and (p_.email or "").strip()
            and isinstance(p_.chart_date, _dt.date) and p_.chart_date < today]


def _undated(people):
    """Eligible people whose chart carries no date we can read.

    Reported loudly: these are the only people a per-person clock cannot
    place, and they get no email at all until somebody writes the date above
    their chart.
    """
    import datetime as _dt
    return [p_ for p_ in people
            if p_.eligible and (p_.email or "").strip()
            and not isinstance(p_.chart_date, _dt.date)]


def _not_yet(people, today=None):
    """Eligible people whose day is further off than the lead. Not a problem."""
    import datetime as _dt

    from automations.shared import new_start_timing as timing

    today = today or _dt.date.today()
    return [p_ for p_ in people
            if p_.eligible and isinstance(p_.chart_date, _dt.date)
            and not timing.due(p_.chart_date, today, config.SEND_LEAD_DAYS)]


def _wrong_week(tab_title: str, *, explicit: bool = False, today=None):
    """A refusal message if this tab isn't THIS week's, or None if it's fine.

    The run always reads the NEWEST dated tab, which is right every week the
    team builds the new one on time -- and catastrophic the week they don't.
    On a Monday with no new tab, "newest" is LAST week's, and fifty-two people
    who started a week ago would each be told "we're excited to have you at
    orientation today". There is no unsend and no way to explain it away.

    So the tab has to be dated for today. A tab that isn't means the lineup
    hasn't been built yet, which is a person's job to fix, not something an
    8am timer should paper over by mailing the wrong cohort.

    Naming a tab with --tab is a human being deliberate, so that bypasses the
    gate -- loudly.
    """
    import datetime as _dt
    from automations.blueink_docs import roster as bir

    today = today or _dt.date.today()
    dated = bir._tab_date(tab_title)

    if explicit:
        if dated and dated != today:
            print("NOTE: {!r} is dated {} , not today. Sending it because you "
                  "named it explicitly.".format(tab_title, dated))
        return None

    if dated is None:
        return ("Refusing to send: can't read a date out of the tab name {!r}, "
                "so there's no way to tell whether it's this week's lineup."
                .format(tab_title))
    # With a per-person lead (Megan 2026-11-18) the tab we want is no longer
    # only today's: two days before a Monday start, the people who are due sit
    # on NEXT week's tab. A lead of 0 leaves this exactly as it was.
    lead = getattr(config, "SEND_LEAD_DAYS", 0) or 0
    if lead and today <= dated <= today + _dt.timedelta(days=lead):
        return None
    if dated > today:
        # A tab further out than the lead. NOT the fault below -- the lineup
        # has been built, nobody on it is due yet, and saying "this week's
        # lineup hasn't been built" about next week's tab sends somebody
        # looking for a problem that isn't there.
        return ("Nothing to send yet: the newest tab is {!r} (dated {}), and "
                "theirs goes out {} day(s) before they start. Nobody is due "
                "until {}.".format(
                    tab_title, dated, lead,
                    (dated - _dt.timedelta(days=lead)).isoformat()))
    if dated != today:
        return (
            "Refusing to send: the newest tab is {!r} (dated {}), but today is "
            "{}.\n"
            "  That means this week's lineup hasn't been built yet. Sending "
            "would email LAST week's\n"
            "  new starts 'we're excited to have you at orientation today' - "
            "with no unsend.\n"
            "  Build the new D2D OBCL tab, then re-run. To send an older tab "
            "on purpose, name it:\n"
            "      --tab {!r}".format(tab_title, dated, today, tab_title))
    return None


def _resolve_links(*, live: bool = True, logfn=print):
    """(slack, skool, source, problems).

    The Slack link is READ OUT OF SLACK at send time, the same click a person
    makes on Monday morning. Slack caps invite links at 30 days and offers no
    API for them, so fetching it every week is the only way this is ever
    hands-off rather than a weekly copy-paste chore wearing an automation's
    clothes (Megan, 2026-08-26).

    The creds file stays as a manual override for the week Slack changes its
    markup: put a link in it and that one wins, so a broken fetch is a
    five-second fix rather than a blocked Monday.
    """
    from automations.slack_skool_email import slack_invite

    skool = config.skool_link()
    override = config.slack_invite_link()
    if override:
        logfn("Using the Slack link from {} (manual override)."
              .format(config.LINKS_PATH.name))
        return override, skool, "creds file", config.validate_links(
            override, skool, slack_is_live=False)

    if not live:
        return "", skool, "not fetched", config.validate_links(
            "", skool, slack_is_live=False)

    try:
        link = slack_invite.fetch(logfn=logfn)
    except slack_invite.InviteError as exc:
        return "", skool, "Slack (failed)", [str(exc)]
    return link, skool, "Slack, just now", config.validate_links(
        link, skool, slack_is_live=True)


def preview(tab_name: str = "", *, fetch_link: bool = True) -> int:
    from automations.blueink_docs import roster as bir

    ws, values, people = _people(tab_name)
    send_to = _recipients(people)
    skipped = [p for p in people if not p.eligible]

    print("\nTab: {!r}   ({} people on it, this week's charts)".format(
        ws.title, len(people)))
    for line in bir.describe_other_week_charts(values, ws.title):
        print("  " + line)
    print("From: {} ({})".format(config.FROM_ACCOUNT, config.MACHINE))
    print("Subject: {}\n".format(config.SUBJECT))

    # GROUPED BY THE DAY THEY START, because that is one send each and each
    # one says a different day. The preview has to show the DAY as the email
    # will word it -- that sentence is the whole point of the change, and a
    # flat list of addresses would hide the one thing worth checking.
    groups = _groups(people)
    if groups:
        print("WOULD SEND {} email(s), one per start day:".format(len(groups)))
        for start, addrs in groups:
            print('\n  {} -> "...at orientation {}"  ({} recipient(s))'.format(
                start.isoformat(), config.when_phrase(start), len(addrs)))
            for p in people:
                if (p.email or "").strip() in addrs:
                    print("     - {:28} row {:>3}  {}".format(
                        p.name, p.row, p.email))
    else:
        print("NOBODY IS DUE TODAY - no email would go out.")

    waiting = _not_yet(people)
    if waiting:
        print("\nNOT DUE YET ({}) - theirs goes {} day(s) before they "
              "start:".format(len(waiting), config.SEND_LEAD_DAYS))
        for p in waiting:
            print("  - {:28} starts {}".format(p.name,
                                               p.chart_date.isoformat()))

    gone = _already_started(people)
    if gone:
        print("\nTHEIR DAY HAS PASSED ({}) - no welcome email, because it "
              "would name a day that is gone:".format(len(gone)))
        for p in gone:
            print("  - {:28} started {}".format(p.name,
                                                p.chart_date.isoformat()))

    nodate = _undated(people)
    if nodate:
        print("\nNO START DATE ON THEIR CHART ({}) - these get NO email at "
              "all, because there is no day to tell them:".format(len(nodate)))
        for p in nodate:
            print("  !! {:28} row {:>3}".format(p.name, p.row))

    print("\n(eligible on the tab: {})".format(len(send_to)))

    missing = _no_email(people)
    if missing:
        print("\nNOT SENT BUT SHOULD HAVE BEEN ({}) - nobody excluded these "
              "people, the sheet just has no usable address:".format(
                  len(missing)))
        for name, row, why in missing:
            print("  !! {:28} row {:>3}  {}".format(name, row, why))

    print("\nSKIPPED ({}) - correctly, they aren't starting:".format(
        len(skipped) - len(missing)))
    for p in skipped:
        if "email" not in (p.skip_reason or "").lower():
            print("  - {:28} row {:>3}  {}".format(p.name, p.row,
                                                   p.skip_reason))

    # Anyone the parser did NOT turn into a person but who has an email on the
    # tab. Silence is the failure mode that matters: nobody notices the new
    # start who didn't get the email.
    stray = bir.unparsed_email_rows(values, people, ws.title)
    if stray:
        print("\nNOT READ AS PEOPLE ({}) -- check none of these should have "
              "been included:".format(len(stray)))
        for row, addr, label in stray:
            print("  - row {:>3}  {:34} {}".format(row, addr, label))

    slack, skool, source, problems = _resolve_links(live=fetch_link)
    print("\nLINKS:")
    if problems:
        for prob in problems:
            print("  !! {}".format(prob))
    else:
        print("  Slack: {}   [{}]".format(slack, source))
        print("  Skool: {}".format(skool))

    print("\n--- MESSAGE " + "-" * 55)
    try:
        print(message.render_body(slack_link=slack, skool_link=skool))
    except message.CopyError as exc:
        print("  !! {}".format(exc))
    print("-" * 67)

    if problems:
        print("\nWould NOT send: fix the link problem(s) above first.")
    else:
        print("\nDry run - nothing sent. Add --send to mail these {} people, "
              "or --draft to review it in Gmail first.".format(len(send_to)))
    return 0


def _guarded_recipients(tab_name: str):
    """(worksheet, recipients, slack, skool) -- or Nones, with a printed
    reason, if we must not send."""
    slack, skool, _source, problems = _resolve_links()
    if problems:
        print("Refusing to send - the links aren't right yet:")
        for prob in problems:
            print("  !! {}".format(prob))
        return None, None, "", ""

    ws, _values, people = _people(tab_name)

    stale = _wrong_week(ws.title, explicit=bool(tab_name))
    if stale:
        print(stale)
        return None, None, "", ""

    send_to = _recipients(people)
    if not send_to:
        # Standing rule: never post/send a blank board. An empty cohort is a
        # quiet week, not a reason to mail nobody and claim success.
        print("Nobody eligible on {!r} - not sending.".format(ws.title))
        return None, None, "", ""
    return ws, send_to, slack, skool


def send(tab_name: str = "", *, force: bool = False, slack: bool = False) -> int:
    from automations.slack_skool_email import gmail_reception as gm

    # The copy and the clock have to agree. Checked HERE, at the send, and not
    # only at import: whoever turns the lead up will be editing config.py, and
    # this is the line that stops the first run after they do.
    blocked = config.early_send_blocked_by_copy()
    if blocked:
        print(blocked)
        return 1

    ws, send_to, slack, skool = _guarded_recipients(tab_name)
    if not send_to:
        return 1

    who = gm.assert_right_mailbox()

    # NO WHOLE-DAY GUARD ANY MORE. `already_sent_today` would send the first
    # group due this morning and silently swallow the second -- and two groups
    # really can fall due together (a late BOB starting tomorrow alongside the
    # Monday cohort). The guard is per person now, applied below, which cannot
    # drop anybody. See gmail_reception.already_sent_to.

    # ONE SEND PER START DATE. Each group is told its own day, so they cannot
    # share a BCC -- see _groups.
    _ws3, _v3, people = _people(ws.title)
    groups = _groups(people)
    if not groups:
        print("Nobody is due today off {!r} - not sending.".format(ws.title))
        return 0

    sent_total, skipped = 0, []
    for start, addrs in groups:
        when = config.when_phrase(start)
        fresh = []
        for addr in addrs:
            try:
                if not force and gm.already_sent_to(addr,
                                                    config.SUBJECT_SEARCH):
                    skipped.append(addr)
                    continue
            except gm.GuardUnavailable as exc:
                # Never "send anyway" on a broken guard. Stopping here leaves
                # the earlier groups sent and says so, which is recoverable;
                # carrying on could mail somebody their welcome twice.
                print(exc)
                print("Stopped after {} send(s).".format(sent_total))
                return 1
            fresh.append(addr)
        if not fresh:
            print("  {} ({}): everybody has already had theirs.".format(
                start.isoformat(), when))
            continue
        msg = message.build(fresh, slack_link=slack, skool_link=skool,
                            when=when)
        res = gm.send(msg)
        sent_total += len(fresh)
        print("Sent from {} to {} BCC recipient(s) starting {} ({}). "
              "id={}".format(who, len(fresh), start.isoformat(), when,
                             res.get("id", "?")))

    if skipped:
        print("{} person/people already had theirs and were left out.".format(
            len(skipped)))
    for p_ in _already_started(people):
        print("  - {} started {} - no welcome email, their day has "
              "passed.".format(p_.name, p_.chart_date.isoformat()))
    for p_ in _undated(people):
        print("  !! {} has no start date on their chart - NOT emailed, "
              "because there is no day to tell them.".format(p_.name))
    waiting = _not_yet(people)
    if waiting:
        print("{} person/people start later; theirs goes {} day(s) "
              "before.".format(len(waiting), config.SEND_LEAD_DAYS))

    if slack:
        from automations.slack_skool_email import slack_post
        slack_post.post(ws.title, [a for _d, g in groups for a in g],
                        problems=_no_email(people), dry_run=False)
    return 0


def draft(tab_name: str = "") -> int:
    from automations.slack_skool_email import gmail_reception as gm

    ws, send_to, slack, skool = _guarded_recipients(tab_name)
    if not send_to:
        return 1

    who = gm.assert_right_mailbox()
    res = gm.create_draft(
        message.build(send_to, slack_link=slack, skool_link=skool))
    print("Draft created in {}'s mailbox: {} BCC recipient(s) off {!r}. "
          "Open Gmail -> Drafts to review and send. id={}".format(
              who, len(send_to), ws.title, res.get("id", "?")))
    return 0


def check_mailbox() -> int:
    """Prove the Gmail token on THIS machine works and belongs to reception.
    Sends nothing, drafts nothing, reads no roster.

    The preview never touches Gmail, so a machine can pass a full dry run with
    a token that is missing, expired, or authorized as the wrong account -- and
    only find out at 8am Monday, when the thing it was supposed to do is mail
    fifty-two people. This is the preflight that closes that gap.
    """
    from automations.slack_skool_email import gmail_reception as gm

    try:
        who = gm.assert_right_mailbox()
    except Exception as exc:
        print("Gmail is NOT ready on this machine:\n  {}".format(exc))
        return 1
    print("Gmail OK - this machine sends as {}".format(who))

    try:
        sent = gm.already_sent_today(config.SUBJECT_SEARCH)
    except gm.GuardUnavailable as exc:
        print("But the re-send guard can't run:\n  {}".format(exc))
        return 1
    print("Re-send guard OK - searched Sent mail, already sent today: {}"
          .format(sent))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Email this week's new starts their Slack + Skool links.")
    ap.add_argument("--send", action="store_true",
                    help="actually send it (no undo)")
    ap.add_argument("--draft", action="store_true",
                    help="create it as a Gmail draft for a human to send")
    ap.add_argument("--slack", action="store_true",
                    help="post the summary to Slack after a real send")
    ap.add_argument("--force", action="store_true",
                    help="send even if one already went out today")
    ap.add_argument("--check-mailbox", action="store_true",
                    help="preflight: prove this machine's Gmail token works "
                         "and is reception's. Sends nothing.")
    ap.add_argument("--no-fetch", action="store_true",
                    help="preview without opening Slack to read the invite "
                         "link (for a machine with no Slack session)")
    ap.add_argument("--tab", default="",
                    help="an explicit 'D2D OBCL <m.d>' tab (default: newest)")
    args = ap.parse_args(argv)

    if args.check_mailbox:
        return check_mailbox()
    if args.send and args.draft:
        ap.error("--send and --draft do different things; pick one")
    if args.send:
        return send(args.tab, force=args.force, slack=args.slack)
    if args.draft:
        return draft(args.tab)
    return preview(args.tab, fetch_link=not args.no_fetch)


if __name__ == "__main__":
    sys.exit(main())
