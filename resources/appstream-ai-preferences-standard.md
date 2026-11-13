# AppStream AI Preferences — the standard, and why

**Check these three numbers on every ICD.** They sit under
AI → Settings → AI Preferences, they are per office, and nothing surfaces them —
an office can run for months on whatever it was set up with.

| Setting | Standard | Never |
|---|---|---|
| Timeslot Buffer — times **offered by AI** | **60** | above 120 (kills same-day) · under 30 |
| Timeslot Buffer — times **accepted by candidates** | **60** | above 120 (kills same-day) · under 30 |
| Ghosting Threshold | 60, or 30 where someone works the queue | — |

Set 2026-11-13 by Megan. Replaces the old 180 / 300 standard (see "What changed").

---

## What the two buffers actually do

Confirmed by Aptel (Cruise Turner with William Kraft, 2026-11-13):

- **Offered buffer** — the AI will not *offer* a time sooner than this many
  minutes from now.
- **Accepted buffer** — an applicant cannot *pick* a time sooner than this many
  minutes from now.

Both are "too soon" floors. Together they decide the earliest interview anyone
can be booked into.

## Why 60 / 60

Show rate by how far ahead the interview was booked (n=1,116, 11280 / 11580 /
23965 / 24065, Sept 2026):

| Booked ahead | Showed |
|---|---|
| 3–6 hours | **59%** |
| under 3 hours | 45% |
| a day or more | 36% |

Same day showed **57%** against **42%** next day.

The lesson is that **same-day is the thing to protect**. Even the worst
same-day band (under 3 hours, 45%) beats pushing someone to tomorrow
(36–42%). A floor high enough to push people to the next day costs more than
it saves.

At 180 / 300 that is exactly what happened on 25065 (Aptel, 2026-11-12):
applicants texted at noon, said they could do today, and the AI could only
offer the next morning at 8am — 300 minutes put the earliest pickable slot
after 5pm.

60 still stops the AI booking someone into a slot minutes away (the reason for
a floor at all — 2 minutes was seen in the wild, and nobody can attend that),
gives an applicant an hour to get ready or log in to Zoom, and leaves most of
the working day open for same-day.

**Not yet measured:** whether under-1-hour bookings show worse than 1–3 hours.
The data above only splits at 3 hours. That is the next cut to run once a
couple of weeks have passed on 60 / 60.

## Ghosting threshold → 60

Display only. It raises a flag on the SMS automation page when an applicant has
not replied in x minutes; nothing reaches the applicant. Leave at 60, or drop to
30 for an office where someone actually works that queue — it is the closest
thing the platform has to catching a stalled thread.

---

## What changed (2026-11-13)

The old standard was **180 offered / 300 accepted**. It read the accepted
buffer as *how long an offered slot is held for the applicant* and set it to
300 so slow repliers would not find their time gone. Aptel confirmed that
reading was wrong: the accepted buffer is a second "too soon" floor. At 300 it
blocked every same-day slot inside 5 hours, which is the opposite of what the
show-rate data asks for.

Withdrawn with it: the "at 5 minutes, 36% of repliers find the slot already
gone" finding. The reply-time numbers were real (950 offers: 63.5% answer
inside 5 minutes, 92.4% inside 300), but they were matched to a meaning of the
setting that it does not have, so they say nothing about where to set it.

Observed before the change: 11280 on 60/5/60, a second office on 15/5/60,
Carlos on 2/300/60, 25065 moved by Aptel from 180/300 to 45/30.

## What is still missing

The buffer cannot express "offer 3–6 hours out where the calendar has them".
That is on the eStream list as a preference window rather than a floor.
