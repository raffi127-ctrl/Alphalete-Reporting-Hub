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

    print("\nTab: {!r}   ({} people on it, all charts)".format(
        ws.title, len(people)))
    print("From: {} ({})".format(config.FROM_ACCOUNT, config.MACHINE))
    print("Subject: {}\n".format(config.SUBJECT))

    print("WOULD BCC ({}):".format(len(send_to)))
    for p in people:
        if p.eligible:
            print("  - {:28} row {:>3}  {}".format(p.name, p.row, p.email))

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
    stray = bir.unparsed_email_rows(values, people)
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

    ws, send_to, slack, skool = _guarded_recipients(tab_name)
    if not send_to:
        return 1

    who = gm.assert_right_mailbox()

    if not force:
        try:
            if gm.already_sent_today(config.SUBJECT_SEARCH):
                print("Already sent from {} today (subject {!r}). Not sending "
                      "again - pass --force if you really mean to."
                      .format(who, config.SUBJECT))
                return 0
        except gm.GuardUnavailable as exc:
            print(exc)
            return 1

    msg = message.build(send_to, slack_link=slack, skool_link=skool)
    res = gm.send(msg)
    print("Sent from {} to {} BCC recipient(s) off {!r}. id={}".format(
        who, len(send_to), ws.title, res.get("id", "?")))

    if slack:
        from automations.slack_skool_email import slack_post
        _ws2, _v2, people = _people(ws.title)
        slack_post.post(ws.title, send_to, problems=_no_email(people),
                        dry_run=False)
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
