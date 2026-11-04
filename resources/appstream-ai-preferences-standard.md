# AppStream AI Preferences — the standard, and why

**Check these three numbers on every ICD.** They sit under
AI → Settings → AI Preferences, they are per office, and nothing surfaces them —
an office can run for months on whatever it was set up with.

Observed in the wild so far: 11280 on 60/5/60, a second office on 15/5/60,
Carlos moving his to 2/300/60. No two the same, none of them deliberate.

| Setting | Standard | Never |
|---|---|---|
| Timeslot Buffer — times **offered by AI** | **180** | below 60 |
| Timeslot Buffer — times **accepted by candidates** | **300** | 5 |
| Ghosting Threshold | 60, or 30 where someone works the queue | — |

---

## Accepted buffer → 300

How long an offered slot stays the applicant's before it is released.

Measured over **950 offers of two or more times** that got a reply, across
11280 / 11580 / 23965 / 24065 in the week to 25 Sep:

| Replied within | Share |
|---|---|
| 2 min | 53.9% |
| **5 min** | **63.5%** |
| 15 min | 75.5% |
| 1 hour | 86.0% |
| **300 min** | **92.4%** |

At 5 minutes, **36% of the people who answer are already outside the window**.
The slot is gone before they finish typing.

It shows in what happens next:

| | Told the time was gone | Offered a different set of times |
|---|---|---|
| Replied within 5 min | 0.8% | 7.0% |
| **Replied after 5 min** | **3.2%** | **19.6%** |

Three times more likely to go round again — about **79 applicants in one week**
across the four offices. That churn is most of why "Can I reschedule?" was the
biggest question bucket in the audit.

*Caveat: a re-offer can also happen because the applicant asked for a different
time, so not all 79 are expiries. But the gap sits exactly on the 5-minute
boundary.*

## Offered buffer → 180

The earliest slot the AI may offer. It is a **floor, not a target** — it can
stop us offering too soon, but nothing steers toward the window that works.

Show rate by how far ahead the interview was booked (n=1,116):

| Booked ahead | Showed |
|---|---|
| 3–6 hours | **59%** |
| under 3 hours | 45% |
| a day or more | 36% |

Within-6-hours vs beyond: 51% vs 38%, p=1.1e-05.

180 puts the floor at the point where show rate jumps from 45% to 59%, so the
AI can no longer offer into the worst band. Same-day stays available for most of
the working day, which matters — same day showed 57% against 42% next day.

**This one is inference, not a proven win.** The show-rate numbers come from
booking lead time, not from an experiment on the buffer itself. Raising the
floor will cost some same-session bookings in exchange for a better show rate.
Worth setting and then re-measuring, not treating as settled.

**2 minutes is the one to catch.** It lets the AI book someone two minutes from
now — a booking nobody can physically attend.

## Ghosting threshold → 60

Display only. It raises a flag on the SMS automation page when an applicant has
not replied in x minutes; nothing reaches the applicant. Leave at 60, or drop to
30 for an office where someone actually works that queue — it is the closest
thing the platform has to catching a stalled thread.

---

## What is still missing

The buffer cannot express "offer 3–6 hours out where the calendar has them".
That is on the eStream list as a preference window rather than a floor. Until it
exists, 180 is the closest approximation.
