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

## Done

(nothing yet)
