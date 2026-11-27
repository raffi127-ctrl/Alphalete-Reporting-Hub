# What to ask ApplicantStream for

Megan's running list of things to ask ApplicantStream to add or change.
Every Claude session adds to it when Megan names a new ask (Megan,
2026-11-15: "just keep a list of what I want to ask for in app stream -
from any session I'm in"). Newest at the bottom. Move an item to **Done**
once ApplicantStream ships it.

Aptel requests live separately (`resources/aptel/`).

## Open

1. **Separate Zoom links for 1st and 2nd rounds** (2026-11-15)
   AI Settings has one Zoom link for the whole office. Many offices use a
   different room for 2nd rounds. Ask for a "1st round Zoom link" and a
   "2nd round Zoom link" field, so the AI and templates send the right one.
   Why it matters: the Applicant Stream Grade Card can't check a 2nd-round
   link against anything, so 11280's 2nd-round emails (room 5708017667)
   only get an orange "is this your 2nd-round room?" question.

2. **2nd round interview type** (2026-11-15)
   AI Settings has one "Interview type" for the office. Ask for a separate
   2nd round interview type (Zoom or in person). The card shows "Not
   available yet in ApplicantStream" until it exists.

3. **A Zoom meeting ID field in AI Settings** (2026-11-17)
   Ask for a spot to type the office's Zoom meeting ID (one for 1st
   rounds, one for 2nd rounds; goes with ask 1). Why it matters: the Grade
   Card grades every template and recruiter text against the office's
   Zoom room, but AI Settings holds no meeting ID, so today the card
   guesses it from whatever link most templates send. Roshan's 19833 card
   graded against 3378381141 with nobody confirming it, and Carlos (11580)
   changed his room a while back, so his old link gets flagged with no
   way to say which room is current. With the ID in AppStream, the card
   reads it from there and grades against the room the office set.

4. **Show rate on Interviews - Timeslot Totals** (2026-11-20)
   Raf's ask. Next to each time slot, add a "Showed" column: how many
   showed out of how many were scheduled, plus the % (e.g. "7/10 · 70%";
   Raf 11/20 approved the mock-up and wants the slash, not "7 of 10").
   Slots that haven't happened yet say "Upcoming". Add a "Showed so far
   today" line at the top of each box (1st rounds, 2nd rounds,
   First Day of Training). Why it matters: Retention Details doesn't
   break out by time slot, so on a day with lots of afternoon 2nd rounds
   Raf can't see his 2nd-round retention while the day is happening.
   Mock-up: `output/appstream-timeslot-retention-mockup.png`.
   Fallback if AppStream won't build it: the Lucy BG Send extension
   (`extension/office-admin/`) already reads each calendar row's show
   status, so it could draw this column on the page itself.

5. **2nd Interviews calendar: new columns, pop-up reasons, cleanup** (2026-11-27)
   Megan's ask. Picking an answer pops up the next dropdown in the same
   cell, the way "Offer Position?" appears under Show Up today.
   - **Column order:** Time, First Name, Last Name, Phone, Email,
     Vetted By, Job Board, Rating, 1st Booked By, Who Conducted the First
     Round, Invite to 2nd Interview?, Answered Invite to 2nd?, Show Up,
     Who Conducted the 2nd Round, Follow Up Status, Follow Up Time,
     icons, Notes, Action, Remove. Every column title centered.
   - **Removed:** Follow Up By, First By Phone, Cell Phone.
   - **Renamed:** Booked By -> **1st Booked By**; Done By -> **Who
     Conducted the 2nd Round**.
   - **Who Conducted the First Round** (new): interviewer dropdown, same
     list as the 2nd round one, filled in from the 1st round's Done By.
   - **Invite to 2nd Interview?** (new): Yes / No. No pops up **Why?**
     (Disqualified / Declined), then **Due to?**.
   - **Answered Invite to 2nd?** (new): Yes / No (LM). Yes pops up
     Booked for 2nd / Declined 2nd. Blank when Invite = No.
   - **Show Up:** keeps Yes / No; Yes pops up "Offer Position?" below.
   - **Follow Up Status options:** Called, BOB - Booked, Left Message,
     Cancelled, Invite to next, Disqualify, Applicant Declined.
     Disqualify and Applicant Declined pop up **Due to?**.
   - **Action:** adds "Disqualify | Decline" links; each pops up
     **Due to?**.
   - **Reason lists:** Disqualify = Camila's ARS reasons (Communication
     Skills, Commute, Pay, Schedule, Hopped Off). Decline = the
     account's Remove Applicant reasons (needs adding to AppStream).
   Mock-up: `output/appstream-2nd-round-columns/` -- `mockup.html`
   (clickable), `how-it-pops-up.gif` (the pop-ups, animated),
   `mockup.png` (proposed page), `today.png` (the page now).

## For Blue Ink (not ApplicantStream)

**The I-9's date-of-birth field keeps the current year.** Measured
2026-11-23 across 116 signed packets on `UNIVERSAL I9 MASTER FORM`:
**12 of them -- about one in ten -- carry a date of birth in the current
year.** Field key `dat010-QaqD0`.

EVERY ONE OF THEM HAS THE CURRENT YEAR, and that is the only thing they
share. The month and day vary and look like real birthdays -- 02-01,
08-08, 05-27, 07-21, 08-24. Only 3 of the 12 match the day that person
signed, and 9 match neither their signing date nor their start date, so
this is not a picker saving "today": the year alone is being lost and
replaced with the current one while the signer's own month and day
survive.

NOT A MAPPING PROBLEM. The field holds real birth years for everybody
else, off the same field on the same form.

**The ask:** the date-of-birth field should not accept a year that makes
the signer younger than about 14, and should not silently default to the
current one.

**Why it matters:** a wrong date of birth goes onto a payroll record. Two
of the twelve are already in Apex, typed in by hand from these packets.

**What we do meanwhile:** the date goes into Apex EXACTLY as the employee
reported it (Megan, 2026-11-23: "we just need to enter in whatever date
the employee reported on their DOB even if we know it's incorrect. They
are filling out the document legally"). `blueink_data._impossible_dob`
flags it so the run says out loud that it cannot be true, and a person can
go and ask them -- it does not hold anybody back. It is not our date to
correct, and keeping somebody out of payroll over a year typed into a date
picker costs them, not us.

**Who they are is deliberately not written here.** This file is in a
PUBLIC repo, and a name beside a date of birth is exactly the pairing that
must never be committed. Re-list them on demand, on a machine with the
Blue Ink key:

    python -m automations.blueink_docs.dob_audit

## Done

(nothing yet)
