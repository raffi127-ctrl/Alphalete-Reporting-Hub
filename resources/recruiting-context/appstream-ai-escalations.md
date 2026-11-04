# AppStream AI escalations — the 11280 / 24065 build

Written 2026-11-03, covering work done 29–30 Oct 2026 by Megan with Claude.
Companion to [appstream-ai-settings.md](appstream-ai-settings.md), which covers
the **Settings** tab. This file covers the **Escalations** tab: what the four
routing modes actually do, the approved reply set, and how both accounts are
configured now.

Accounts: **11280** (Alphalete Marketing — production) and **24065**
(Alphalete FULL AI). 24065 was built to match 11280 exactly.

---

## 1. The four routing modes — this is the thing to understand first

Confirmed by Jovanna De La Torre (eStream) on 2026-10-29. Every escalation row
is set to exactly one of these, and only one of them sends the words you wrote.

| Mode | What actually happens | Raises a flag? |
|---|---|---|
| **Don't Escalate** | Sends your stored custom message **verbatim**, and the AI stays in the conversation. | **No** |
| **Clarify** | Two-step. The AI writes **its own** deflection. Your custom message is not part of the flow. | Yes |
| **Escalate** | The AI writes **its own** closing line and stops the conversation. | Yes |
| **Silent** | Nothing is sent. The thread is flagged. | Yes |

Two consequences worth internalising:

- **If you want your approved wording to reach an applicant, the row must be on
  Don't Escalate.** Clarify and Escalate both paraphrase.
- **Don't Escalate raises no flag.** Any row where a human genuinely has to act
  must stay on Escalate, even though that means the applicant gets the AI's
  words rather than yours. That trade-off is item 6 on the eStream asks list —
  we want a mode that sends our words *and* flags.

A custom message must exist before Don't Escalate can be selected. An empty
message box keeps the row locked out of Don't Escalate, which is deliberately
how the six Escalate rows are left: nobody can later flip one into a silent
auto-reply with no flag.

**Before this work, zero of 11280's 51 rows were on Don't Escalate.** All 16
custom messages that existed had never reached a single applicant.

## 2. How both accounts are configured now

Verified 2026-10-30 by reading the radio buttons directly (not the row
captions), after eStream turned the accounts off and back on. **0 mismatches on
either account.**

| | 11280 | 24065 |
|---|---|---|
| Don't Escalate | 31 | 31 |
| Escalate (message box deliberately empty) | 6 | 6 |
| Silent | 6 | 6 |
| Locked "Silent Only" (no radio to set) | 8 | 8 |
| **Total rows** | **51** | **51** |

**Escalate — a person must act, message left empty:** All Timeslots Booked ·
Request Outside Available Timeframes · Scheduling Dead End · Scheduling Impasse
/ Repeated Rejection · External Context Reference · Work Location

**Silent, no message:** Hostile or Threatening Language · Offensive Language /
Swear Words · Applicant Not Qualified · Fails Welcome Message Requirement ·
Scam Indicators

**Silent but holding a message on purpose:** Single Word Rejection Response —
the message is saved so it is ready, but the row stays Silent until eStream
confirms whether "stop" reaches the row or is intercepted as a carrier opt-out
first. Replying to someone who has opted out is the thing to avoid.

**Locked Silent Only (platform won't allow anything else):** Mentions
"Bot"/"AI"/"ChatGPT" · Group Duplicate · AI Response Max Retries · Dummy Phone
Number · Email Already Brought On Board · Non-English Language Detected ·
Removed or Completed Applicant · System Failure

Non-English being locked is a real loss — Spanish is the 3rd most common thing
applicants say (6.7 per 1,000; 9.5 at 11580) and today those applicants get
nothing. Unlocking it is on the eStream list.

## 3. The approved reply set

All 32 signed off by Megan over 29–30 Oct. Every one of these is live on both
accounts and was checksum-verified against this list on 2026-10-30.

| Row | Message |
|---|---|
| **Request to talk via Phone** | Will do, you're on the call list! Happy to carry on right here over text too if that works better for you? |
| **Third-Party Response Detected** | Thanks for letting me know! Is there a better way to reach them, or could you let them know we reached out? |
| **Company Name Confusion** | Ha, no worries - job hunting can be overwhelming! You applied on {jobBoard} for the {adPostingTitle} role here at {officeName}, working with our client AT&T. Does that sound familiar? |
| **Confusion About Role Type** | Good question - it's our open {adPostingTitle} role at {officeName}, working with our client AT&T - the one you applied to on {jobBoard}. Does that ring a bell? |
| **Request for Unprovided Information** | Happy to help! The full listing is on your {jobBoard} profile. Anything specific you'd like to know - I can answer it right here. |
| **Compensation** | On average our team earns $1,000-$1,500 a week, plus bonuses and commission, depending on background and experience. Was there a specific range you were looking for? |
| **Parental Leave** | Good question! That's something we look at case by case, so it's open for discussion if you're offered a position. Anything else I can help with? |
| **Vacations / Paid Time Off / Time Off** | Good question! Time off is something we work out case by case, so there's room to talk it through if you're offered a position. Anything else I can help with? |
| **Conversational Dead End / Disengagement** | No worries at all - just text me whenever you're ready! |
| **Deferred or Non-Committal Time Response** | Sounds good - take your time! Just text me when you know and we'll lock in a time. |
| **Job Description** | Sure thing! You applied to our {adPostingTitle} role at {officeName} - so providing customer service and sales for our client AT&T. Is that something you'd like to pursue? |
| **Disabilities / Accommodations** | Of course - if you need anything to make the interview work for you, just let me know. |
| **Diversity and Inclusion** | Great question! We hire on work ethic - no experience needed, and we train you on everything. Anything else I can help with? |
| **Full-Time / Part-Time Definitions** | It's a full-time position and it's in person. Training is paid and starts on day one. Is full-time what you're looking for? |
| **Age Requirement Inquiry** | Good question! You need to be 18 or older for this one - our client requires a background check. If you're turning 18 soon, just reach back out! |
| **Commute Distance Rejection** | Totally understand - just so you have it, we're at 5217 Tennyson Pkwy Suite 100, Plano TX. If that's more doable than you thought, just say the word! |
| **Lack of Transportation** | No problem at all - what matters is being able to get to the office each day. Is that something you can manage? |
| **Visa Sponsorship / Work Authorization** | Good question! We aren't able to sponsor visas for this role - you'd need to already be authorized to work in the US. |
| **Does Not Remember Applying** | All good! It's the {adPostingTitle} role at {officeName} you applied to on {jobBoard}, working with our client AT&T. Does that ring a bell? |
| **User Not Interested / Wants to Opt Out** | No problem at all - I'll take you off our list. Thanks for letting us know, and best of luck! |
| **Applicant Requested Directions** | We're at {officeAddress1}, {officeCity} {officeState} {officeZip}. Can you make that daily commute if offered a position? |
| **Interview Format (1-on-1 vs Group)** | It's a small group - usually just a couple of others going for the same role. The goal is really to get to know you and answer any questions you have. |
| **Repeated Request for Unavailable Time** | I wish I could make that one work - it isn't on the calendar. Which of the times I sent would be easiest for you? |
| **Scheduling Medium Rejected** | The first interview is over Zoom - it keeps it quick, and you can join from anywhere. Does that work for you? |
| **Empathetic Reason / Personal Hardship** | I'm so sorry to hear that. Would you like to look at another time now, or would you rather reach back out when things settle? |
| **Remote Work** | It's in person - you applied to our {adPostingTitle} role. We're at {officeAddress1}, {officeCity} {officeState} {officeZip}. Is that a commute you can commit to? |
| **Travel** | Great question! All of our work is around the local area - no long-distance travel. Anything else I can help with? |
| **Work Days** | It's a full-time position and it's in person. Training is paid and starts on day one. Is full-time what you're looking for? |
| **Work Flexibility (Remote/Flex hours)** | Good question! It's in person rather than remote - you applied to our {adPostingTitle} role, and it's full-time. Is that what you're looking for? |
| **Work Hours** | It's a full-time position and it's in person. Training is paid and starts on day one. Is full-time what you're looking for? |
| **Mentions "Scam"** | I understand wanting to check! We're {officeName}, and our office is at {officeAddress1}, {officeCity} {officeState} {officeZip}. Happy to answer anything else you'd like to know. |
| **Single Word Rejection Response** *(Silent — held, not sending)* | No problem at all - thanks for letting me know, and best of luck out there! |

## 4. Rules for writing these messages

- **250 character limit** on the box. The counter is the truth — if it reads
  0/250 your text did not register.
- **Hyphens, never em or en dashes.** An em dash is not GSM-7. One of them flips
  the whole SMS to UCS-2 and the per-segment limit drops from 160 characters to
  70, so a one-segment message silently becomes two and costs double. 48 dashes
  were swapped out across both accounts on 30 Oct for exactly this reason.
- **Over 160 characters costs an extra segment.** Four of the approved messages
  are over; Megan's call was to leave them (2026-10-29).
- **Merge variables: brackets are optional since 2026-10-30.** See section 5.
- Live SMS variables: `applicantFirstName`, `adPostingTitle`, `jobBoard`,
  `officeName`, `officeAddress1`, `officeCity`, `officeState`, `officeZip`,
  `nextInterviewDay`, `videoIview`. Email-only: `officePhone`,
  `officeAddress2`, `recruiterName` — a text can never name a person, which is
  why the escalation contact name has never once rendered in six weeks.
- **Address lines are read from fields, not typed.** Writing the address by hand
  is how 11280 ended up with a Suite 207 / Suite 100 contradiction. Use the
  variables so it cannot drift.

## 5. The 30 Oct variable incident — read this before touching a message

**What happened.** AI SMS went out with the variable names visible in the text.
Travis Clater raised it 9:37am. Moshiur Ahmed's first call was "take the curly
brackets out", so Travis stripped brackets on both accounts and set roughly ten
rows per account to **silent escalate** as a stopgap.

**The actual fix** (William Kraft, in prod ~10:57am): the AI now resolves
`officeName`, `jobBoard`, `adPostingTitle` and the address variables itself
before the text goes out, **with or without the brackets**. Before that day only
a few bare names — `adPostingTitle` among them — happened to work, which is why
the stripped versions were still misfiring. He ran every message on both
accounts through it plus a live test.

**Validation changed the same day.** The compliance check never knew which
variables existed; it only flagged invented ones like `{companyTBD}` because
they read as draft text. There is now a real check: any variable the platform
cannot fill is flagged, the ones that work are listed, and it refuses the save.
That closes defect #2 on the eStream asks list.

**So:** both accounts currently hold the **bare** form (`jobBoard`). The table
in section 3 is written **with** brackets. Both are correct and both work —
**do not "fix" either one.** This was nearly mis-diagnosed as a regression.

## 6. The AI Preferences numbers — the ICD-wide standard

Full evidence in `resources/appstream-ai-preferences-standard.md`. Short version,
and both accounts are set this way:

| Setting | Standard | Never |
|---|---|---|
| Timeslot Buffer — times **offered by AI** | **180** | below 60 |
| Timeslot Buffer — times **accepted by candidates** | **300** | 5 |
| Ghosting Threshold | 60 (30 where someone works the queue) | — |

These are per office, nothing surfaces them, and no two offices were found set
the same. **Check them on every ICD.**

The accepted buffer matters most: at 5 minutes, 36% of the people who reply find
the slot already released. 950 offers measured — median reply 2 minutes, but
only 63.5% inside 5 minutes against 92.4% inside 300. Late repliers were ~3x
more likely to be re-offered times (19.6% vs 7.0%).

## 7. Is it working? — first measurement, 30 Oct

Pulled from the SMS List Report (p=336) and the AI bookings page (p=1500).
**Treat as indicative only** — it was the day of the variable incident, so the
morning ran with raw variables and ten rows on silent.

Texts that day: 11280 2,407 total (1,820 out / 587 in, 670 of them AI);
24065 684 total (500 out / 184 in, 207 AI). Failure rate 1.6% vs **3.4%** —
24065's is worth a look.

Same-day bookings: 11280 57 AI / 31 other; 24065 21 AI / 9 other.

AI answered 40.9% of inbound on 11280 and 45.7% on 24065, median reply **1
minute** (human median is 18).

Show rates off the fully-marked calendar that evening:

| Cohort | Showed / total | Rate |
|---|---|---|
| Booked for the same day, by AI | 24 / 44 | 54.5% |
| Booked for the same day, by a person | 31 / 46 | 67.4% |
| Booked for a later day, by AI | 42 / 80 | 52.5% |
| Booked for a later day, by a person | 4 / 13 | 30.8% |

Same-day booking beat booked-ahead overall (61.1% vs 49.5%, p=0.11), but the
effect came from the human bookings (67.4% vs 30.8%, p=0.018), not the AI
(54.5% vs 52.5%, p=0.83). **The AI did not show the same-day lift the
booking-lead-time analysis predicted.** One dirty day — do not act on it.

**This matches an independent finding.** The audit in
[appstream-audit-findings.md](appstream-audit-findings.md) tested the related
question — whether the AI *offering* a same-day slot lifts attendance — over
501 AI offer messages across 11280 and 11580, 19–23 Oct: **47.4% same-day
offered vs 47.0% next-day only, p=1.00.** Different week, different offices,
different measure, same answer: no same-day lift from the AI. Two null results
on one assumption is worth taking seriously, though both are single-week
samples.

Note what this does *not* overturn: the 180-minute offered buffer still keeps
the AI out of the sub-3-hour band, and the 300-minute accepted buffer is
justified on reply timing, not on show rate.

**The question still unanswered:** retention when we book someone *the same day
we first talk to them*. That needs first-contact date joined to booking and
show-up; the calendar has no app-created column and the applicant list would not
filter cleanly. The route is an Action History export, not these screens.

## 8. Working the Escalations UI — hard-won mechanics

- **`form_input` does not work here.** Setting the DOM value leaves AppStream's
  model untouched — the character counter stays 0/250 and the save silently
  does nothing. Use real keystrokes.
- **The first click into the dialog's textarea usually misses.** Click it, wait,
  click again, then type. On a row with existing text, select-all before typing
  or you will append.
- **Clicking by element reference is unreliable on this table; coordinates
  work.** Use the DataTables **Search** box to filter to one row first — that
  puts everything at fixed, predictable positions.
- **Validation takes 10–15 seconds** and can hard-fail with "not compliant with
  the guidelines". To keep your wording, tick *"I've read the AI's concerns and
  want to use my wording as written. My office is responsible for this
  message"* and press **Save Anyway**. The tick-box renders as an empty square
  either way; the tell is that **Save Anyway turns from faded to solid**.
- **Reload before you believe a page.** A tab left open from before a change
  will happily show the old configuration. On 30 Oct a stale tab showed 11280
  with zero Don't Escalate rows; a reload showed all 31 correct.
- **The SMS List Report is pinned to today.** The date fields reset on submit
  and URL parameters are ignored, so there is no historical SMS pull from that
  screen. The AI bookings page (p=1500) *does* take a date range.
- The session times out overnight and the credential is not on Megan's laptop —
  she has to sign in before any of this can be read.

## 9. Open items

- **eStream asks document is still unsent** (`output/estream-asks-2026-10-26.md`).
  Nine items, including: a mode that sends our words *and* flags; unlocking
  Don't Escalate on Non-English and Bot/AI; whether "stop" reaches Single Word
  Rejection; and a preference *window* for offered times rather than a floor.
- **Three validator objections were overridden on substance**, not just tone —
  Request for Unprovided Information, Deferred or Non-Committal, Diversity and
  Inclusion. Worth revisiting together.
- **Compensation wording on 11280 was changed** from the older "Starting pay is
  $1,000 to $1,500 a week, and there's no ceiling on it..." to the approved
  line in section 3. Megan kept the change; flagged here because it was not part
  of the hyphen sweep she asked for.
- **Only 11280 and 24065 were checked.** William mentioned a live test on
  account 105. If other offices had brackets stripped in the same sweep, nobody
  has verified them.
- **A clean measurement day** — the 30 Oct numbers are from the day of the
  incident.
