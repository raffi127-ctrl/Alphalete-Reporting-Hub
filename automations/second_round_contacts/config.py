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
ROSTER_HEADERS = ["Owner", "ApplicantStream Office ID", "Reception Email",
                  "Active", "OwnerVille Campaign", "Start Date", "Notes",
                  "Last Run", "Last Result"]
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
LABEL_BOB = "Brought on Board Booked"
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
# counts as "Brought on Board Booked". NOT "showed up" and NOT "offered": a
# second round can be marked showed up, or even offered the position, and still
# never turn into a start, and those names are what fill reception's group with
# people who mean nothing.
EVENING_KEEPER = LABEL_BOB
NOT_HIRED_DAYS = 7
NO_SHOW_DAYS = 21
BADGE_DAYS = 21
AUDIT_LOOKBACK_DAYS = 35        # how far back the audit re-reads the report

# HOW FAR FORWARD THE BOB MARK IS READ (2026-11-17). Every other metric here is
# an event that already happened, so looking backwards finds it. A BOB is not:
# the Second Interviews page files it as "Brought on Board (Nov 30)" -- the day
# they are due to START, which is in the future. A backward-only window
# therefore returns NOTHING for exactly the people who ARE marked, which is how
# the first live preview came back with the keeper empty for all five owners
# while the page plainly showed three people marked BOB - Booked that morning.
# 60 days is comfortably past the furthest start anyone books.
BOB_FORWARD_DAYS = 60


def today() -> dt.date:
    return dt.date.today()
