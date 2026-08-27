"""Everything about this email a human might want to change -- above all the
COPY, which lives here as plain text so Megan can reword it without touching
code.

No row or column indices: the OBCL columns are found by header LABEL and the
week by the dated tab, per the no-hardcoded-columns rule in CLAUDE.md.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# The workbook and the tab convention are the new-start family's, shared with
# Blue Ink / Digi Docs / BG Check -- see automations/shared/new_start_steps.py.
from automations.shared.new_start_steps import SHEET_ID, DATED_TAB_PREFIX  # noqa: F401,E402

# The mailbox this goes out from. Reception, not alphaletereporting@ -- new
# starts have corresponded with reception and reply to it. It needs its OWN
# Gmail token; see gmail_reception.py.
FROM_ACCOUNT = "alphaletereception@gmail.com"

# What the recipients see in the From line.
FROM_NAME = "Alphalete Marketing"

MACHINE = "Lucy 1"

SUBJECT = "Welcome to Alphalete \u2014 3 apps to set up before orientation"

# What the re-send guard searches reception's Sent mail for. NOT the full
# subject: that carries an em dash and a slash-free but punctuated phrase, and
# Gmail's search treats punctuation unevenly -- a query that quietly matches
# nothing would let the cohort be mailed twice, which is the one mistake this
# guard exists to prevent. So the guard looks for a distinctive, punctuation-
# free run of words instead. A test asserts it is still a substring of SUBJECT,
# so rewording the subject can't silently orphan the guard.
SUBJECT_SEARCH = "3 apps to set up before orientation"

# --- The copy ---------------------------------------------------------------
# Edit freely. ONE template renders BOTH parts of the email, so the HTML and
# the plain-text fallback can never drift apart.
#
# `[[Word->slack]]` and `[[Word->skool]]` become:
#     HTML  : <a href="...">Word</a>          the link sits on the word
#     text  : Word <https://...>              the URL stays visible
#
# The plain-text part keeps the bare URL on purpose. It is what a text-only
# client renders and what a cautious reader checks, and to fifty people who
# have never had an email from reception before, a visible destination reads
# as more trustworthy than a naked hyperlink.
#
# Corrected from the version reception sent by hand through 2026-08-24:
#   * "W2 & I9" -> "I-9 and W-4". A W-2 is the year-end form the COMPANY sends
#     the employee in January; a new hire fills out a W-4. This was the one
#     substantive error in the old copy.
#   * Subject "Slack / Skool" -> "Welcome to Alphalete - 3 apps to set up
#     before orientation" (Megan picked this from three, 2026-08-26). It has
#     to carry the COMPANY NAME: this arrives from an address the recipient
#     has never seen, with no visible To: line, and the From name truncates on
#     a phone -- the subject is the only trust signal left. It also has to name
#     the TASK, because "Slack / Skool" means nothing to someone who has not
#     heard of Skool yet. No caps, no exclamation, no emoji: this email's only
#     real failure mode is landing in Promotions.
#   * "Hey!" -> "Good morning, and welcome to Alphalete Marketing!" (Megan
#     picked this from three, 2026-08-26: professional, warm, and "good
#     morning" is only ACCURATE because this goes at 8am on the day itself.
#     If the send time ever moves off the morning, this line moves with it.)
#   * "School" -> "Skool" (the platform is skool.com).
#   * "Telemapper 3.0" -> "TeleMapper 3 by KLE". The App Store listing is
#     "TeleMapper 3" (capital M, no ".0"), published by KLE -- verified from
#     the store page 2026-08-26. Someone searching for "Telemapper 3.0" is
#     searching for something that isn't there, and this is the one app in
#     the list with no join link to route them, so the NAME is all they have.
#     Naming the publisher instead of linking keeps it right on Android too;
#     the store page Megan sent is iOS, and an iOS link would strand everyone
#     on a Pixel.
#   * "Blue Ink" -> "Blueink" (one word on their own site).
#   * Dropped 'an email titled " Alphalete Marketing BLUEINK"'. Our Blueink
#     sends label each envelope with the signer's OWN name
#     (blueink_docs/ui_send.py), so that subject line is not what lands in
#     their inbox, and sending someone hunting for a subject that doesn't
#     exist is worse than naming the sender.
BODY = """Good morning, and welcome to Alphalete Marketing!

We're excited to have you at orientation today. Before you arrive, please
download these three apps and set up your accounts.

1. [[Slack->slack]] - download the app first, then join through this link.

2. [[Skool->skool]] - download the app first, then join through this link.

3. TeleMapper 3 by KLE - just download it, no login needed yet.

You'll also get a separate email from Blueink with your I-9 and W-4. Please
fill those out before you come in - it speeds everything up on your first day.

See you soon!

Alphalete Marketing
"""

# --- The links --------------------------------------------------------------
# NOT in this file and NOT in the repo. The repo is PUBLIC: a Slack invite link
# committed here lets any stranger who finds it join the workspace.
#
#   slack-skool-creds.json          (repo root, gitignored by *-creds.json*)
#   {
#     "slack_invite_link": "https://join.slack.com/t/ao-pbns/shared_invite/...",
#     "skool_link":        "https://www.skool.com/alphalete-marketing-8578/...",
#     "slack_link_updated": "2026-08-31"
#   }
#
# Paste both links by COPYING them (Slack: workspace menu -> Invite people ->
# Copy Invite Link; Skool: the class invite link). Never retype them from a
# screenshot -- one wrong character and nobody can join, and the send looks
# perfectly successful.
LINKS_PATH = REPO_ROOT / "slack-skool-creds.json"

# Slack invite links CANNOT be made permanent. Per Slack's own docs a shared
# invite link lasts **30 days maximum** and is good for **400 uses**; "Edit
# link settings" lets you pick an expiry date within that ceiling, not remove
# it. So this link always has to be repasted -- the only question is how often,
# and setting it to the 30-day max turns a weekly chore into a monthly one.
#
# There is deliberately no "never expires" escape hatch in this config. One
# would be a footgun: somebody ticks it believing Slack was configured that
# way, the nag goes quiet, and the link dies at day 30 with nobody warned --
# which is exactly the silent failure everything else here guards against.
#
# Warn from day 25, so a dying link surfaces on a Monday BEFORE the Monday a
# new start clicks it and can't get in.
#
# The 400-use cap matters too at ~52 new starts a week: a link is spent in
# roughly eight weeks regardless of its expiry date.
SLACK_LINK_STALE_DAYS = 25


def _links() -> dict:
    try:
        return json.loads(LINKS_PATH.read_text())
    except Exception:
        return {}


def slack_invite_link() -> str:
    return str(_links().get("slack_invite_link")
               or os.environ.get("SLACK_INVITE_LINK", "")).strip()


def skool_link() -> str:
    return str(_links().get("skool_link")
               or os.environ.get("SKOOL_LINK", "")).strip()


def slack_link_age_days():
    """How many days since the Slack invite link was last refreshed, or None
    if the creds file doesn't say."""
    raw = str(_links().get("slack_link_updated", "")).strip()
    if not raw:
        return None
    try:
        when = dt.date.fromisoformat(raw)
    except ValueError:
        return None
    return (dt.date.today() - when).days


def validate_links(slack: str, skool: str, *, slack_is_live: bool) -> list:
    """Everything wrong with these two links, as human sentences. Empty means
    good to send.

    `slack_is_live` says the link was just read out of Slack itself, in which
    case it cannot be stale and the age check is meaningless. It only applies
    to a link sitting in the creds file, where nothing but a date tells us how
    close to Slack's 30-day ceiling it is.
    """
    out = []
    if not slack:
        out.append(
            "No Slack invite link. Normally it is read out of Slack at send "
            "time; if that isn't set up on this machine, seed it with "
            "`python -m automations.slack_skool_email.slack_invite --login` "
            "or drop one in {} as \"slack_invite_link\"."
            .format(LINKS_PATH.name))
    elif "join.slack.com" not in slack:
        out.append("The Slack link doesn't look like a join.slack.com invite: "
                   "{!r}".format(slack[:60]))
    if not skool:
        out.append("No Skool link. Put one in {} as \"skool_link\"."
                   .format(LINKS_PATH.name))
    elif "skool.com" not in skool:
        out.append("The Skool link doesn't look like a skool.com link: {!r}"
                   .format(skool[:60]))

    if slack and not slack_is_live:
        age = slack_link_age_days()
        if age is None:
            out.append(
                "This Slack link came from the creds file and it doesn't say "
                "when it was pasted (\"slack_link_updated\": \"YYYY-MM-DD\"), "
                "so we can't tell how close it is to expiring.")
        elif age > SLACK_LINK_STALE_DAYS:
            out.append(
                "The Slack link in the creds file was pasted {} days ago. "
                "Slack expires these after 30 days maximum, so refresh it "
                "before this sends or a new start clicks a dead link."
                .format(age))
    return out


def link_problems() -> list:
    """Validation of whatever is in the creds file alone. The scheduled run
    resolves the Slack link out of Slack first -- see run._resolve_links."""
    return validate_links(slack_invite_link(), skool_link(),
                          slack_is_live=False)
