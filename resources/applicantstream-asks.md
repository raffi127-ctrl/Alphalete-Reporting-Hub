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

## For Blue Ink (not ApplicantStream)

**The I-9's date-of-birth field keeps the current year.** Measured
2026-11-23 across 116 signed packets on `UNIVERSAL I9 MASTER FORM`:
**11 of them -- about one in ten -- carry a date of birth in the current
year.** Field key `dat010-QaqD0`.

Four of the eleven are the day the person signed; the other seven have a
plausible month and day with the year left at the current one. That is the
signature of a date picker that opens on today: a signer who sets month
and day but not the year saves this year, and one who does not touch it at
all saves the signing date.

NOT A MAPPING PROBLEM. The field holds real birth years for the other 105
people, off the same field on the same form.

**The ask:** the date-of-birth field should not accept a year that makes
the signer younger than about 14, and should not silently default to the
current one.

**Why it matters:** a wrong date of birth goes onto a payroll record. Two
of the eleven are already in Apex, typed in by hand from these packets.

**What we do meanwhile:** `blueink_data._impossible_dob` rejects them, so
the Apex fill holds those people rather than typing a birth date that
cannot be true.

**Who they are is deliberately not written here.** This file is in a
PUBLIC repo, and a name beside a date of birth is exactly the pairing that
must never be committed. Re-list them on demand, on a machine with the
Blue Ink key:

    python -m automations.blueink_docs.dob_audit

## Done

(nothing yet)
