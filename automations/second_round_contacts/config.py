"""Second-round applicants -> each new owner's reception Google Contacts.

Raf, #l10-alphalete 2026-10-30 ("Daily Update / Google Contacts / Lucy ECHO
for New Owners"): a new owner gets a reception Gmail on the checklist, logs
into it on the laptop and the phone, and from then on every second round
conducted (or booked) lands in that account's contacts automatically -- so
the owner doing the hiring calls already has the numbers. Then the audit, so
the phone does not drown in contacts (people have complained about the one
list we use):

  * not hired / left as a message after 1 week            -> removed
  * a new start who never showed, 3 weeks after the date  -> removed
  * never fully badged (OwnerVille View Progress < 100%)
    3 weeks after showing up                               -> removed
  * terminated or gone later                               -> KEPT (Raf: we
    may rehire them months down the road)

Carlos 2026-10-31: owners update ApplicantStream late, so read 2-3 times a
day; "fully badged" = OwnerVille -> Onboard -> View Progress -> campaign
(most are RES-AT&T) -> search the rep -> Progress column = 100%.

WHO IS SYNCED is the "2R Contacts" tab Megan / Eve keep on the Org workbook
(next to Eve's "New Owners" bank): one row per owner -- their ApplicantStream
office id (when an owner moves to a new funnel: "new, old", e.g. "24232, 24153",
and both are read), their reception Gmail, Active Yes/No. A row only runs once that
Gmail's Contacts token is on the machine (contacts-rw-token-<local>.json,
made once with fiber_owners_distro.contacts_write --authorize).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "second_round_contacts"
STATE_PATH = OUT_DIR / "state.json"

# The roster tab, on the Org workbook (org_sales_board.run.SHEET_ID), next to
# Eve's "New Owners" bank. Created with headers on first use, never cleared.
ROSTER_TAB = "2R Contacts"
# "Slack User ID" and "Timezone" are for an owner who is NOT on ECO yet
# (Megan, 2026-11-18: Algemar and Vincent are "mid launch so not on ECO yet").
# An ECO office record already carries a Slack id, a timezone and a day_end, so
# for those owners these two stay BLANK and the office stays the one source of
# truth -- filling them in as well is how the two drift apart. They exist
# because a pre-ECO owner still has second rounds to call and no office record
# to look up, and the 6pm nudge would otherwise reach 3 of 5 owners.
ROSTER_HEADERS = ["Owner", "ApplicantStream Office ID", "Reception Email",
                  "Active", "OwnerVille Campaign", "Start Date", "Notes",
                  "Slack User ID", "Timezone", "Last Run", "Last Result"]
ACTIVE_YES = "Yes"
DEFAULT_OV_CAMPAIGN = "RES-AT&T"

# Contact groups inside each reception account.
GROUP = "2nd Rounds"            # every applicant this job adds, while tracked
FORMER_GROUP = "Former Applicants"   # where a removed-but-worth-keeping card goes
NAME_TAG = "2R"                 # "First Last (2R 10/31)"

# Retention Details rows (ApplicantStream -> Reports -> Retention Details).
LABEL_BOOKED = "Second Interviews Booked"
LABEL_HELD = "Total Second Interviews"
LABEL_SHOWED = "Second Interviews Showed Up"
LABEL_OFFERED = "Offered Job From Second Round"
# WHAT THE PAGE ACTUALLY CALLS IT (probed 2026-11-18, office 11280). It is
# "Total Daily Bob", under "Administrative Booking Data: -> Retention Call
# List". We asked for "Brought on Board Booked" for a day and a half; no such
# row exists, so the read came back empty for every owner and the keeper guard
# removed nobody. Every other label on this list probed OK, which is why the
# empty read looked like a real zero rather than a miss. Do not reword this
# from a screenshot of the Second Interviews page -- that page and this report
# word things differently, and that assumption is what cost the day and a half.
LABEL_BOB = "Total Daily Bob"
LABEL_NS_SCHED = "Total New Starts Scheduled"
LABEL_NS_SHOWED = "New Starts Showed Up"
ADD_LABELS = (LABEL_BOOKED, LABEL_HELD)
AUDIT_LABELS = (LABEL_SHOWED, LABEL_OFFERED, LABEL_BOB, LABEL_NS_SCHED,
                LABEL_NS_SHOWED)

# Raf's clocks.
# THE EVENING PASS CLEANS UP THE SAME DAY (Raf, 2026-11-17). A second round
# that is over and was marked NEITHER "showed up" NOR "offered" is somebody who
# did not come, and keeping them in reception's contacts for a week teaches
# people the group is full of names that mean nothing. The earlier passes never
# do this: at 6am and 11:30 the day is still running and a blank only means
# nobody has marked it yet, which is the same rule the onboarding board lives
# by.
#
# AND IT LOOKS AT THE DAY BEFORE TOO (Megan, 2026-11-17: "look again at the day
# before on the 7pm scan just to make sure no one was marked differently").
# Recruiters mark late -- after 7pm, or the next morning -- and the first pass
# to see that mark has to be able to act on it both ways round: somebody still
# blank from yesterday comes out, and somebody the evening rule took out
# yesterday who has since been marked showed up or offered goes back in. One
# day, not the whole week: a mark that lands later than that is a hand re-add,
# because the further back the window reaches the more it is re-litigating
# removals the standing rules already made.
EVENING_HOUR = 19
EVENING_LOOKBACK_DAYS = 1

# WHAT KEEPS SOMEBODY IN (Megan, 2026-11-17, over the Second Interviews page):
# "anyone that isn't marked BOB should be removed". The keeper is the BOB mark
# -- Follow Up Status "BOB - Booked" on that page, which the Retention report
# counts in its "Total Daily Bob" row. NOT "showed up" and NOT "offered": a
# second round can be marked showed up, or even offered the position, and still
# never turn into a start, and those names are what fill reception's group with
# people who mean nothing.
EVENING_KEEPER = LABEL_BOB
NOT_HIRED_DAYS = 7
NO_SHOW_DAYS = 21
BADGE_DAYS = 21
AUDIT_LOOKBACK_DAYS = 35        # how far back the audit re-reads the report

# HOW FAR FORWARD THE BOB MARK IS READ (2026-11-17).
#
# WHY THIS WAS ADDED, AND WHY THAT REASON IS NOW IN DOUBT. It was added to
# explain an empty keeper read: the Second Interviews page files a BOB as
# "Brought on Board (Nov 30)", so the mark looked like it was dated by the day
# somebody STARTS, and a backward-only window would miss exactly the people who
# ARE marked. That read is now explained by something simpler and proven -- the
# row label was wrong (see LABEL_BOB above), so no window of any shape could
# have found it.
#
# This report's row is called "Total Daily Bob" and breaks down by RECRUITER,
# which reads much more like a count of BOBs MADE that day than of starts due
# that day. If that is right, the forward window finds nothing and the backward
# one is what matters. Costs nothing to leave on: the report shows one week at a
# time, so a date column outside it simply is not found. Settle it by looking at
# WHICH dates come back non-zero on the next dry pass, not by re-reasoning.
# 60 days is comfortably past the furthest start anyone books.
BOB_FORWARD_DAYS = 60


def today() -> dt.date:
    return dt.date.today()
