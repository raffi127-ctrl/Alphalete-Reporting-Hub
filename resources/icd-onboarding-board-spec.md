# ICD Onboarding Board — spec

**Megan, 2026-11-08.** The goal in her words: *"automate onboarding for every
ICD so that things stop getting missed."*

Every ICD has ApplicantStream and OwnerVille. Almost none has an OBCL. So the
board that Alphalete keeps by hand in a spreadsheet becomes something each
office gets automatically, seeded from AppStream, filled by the automations
that already exist, and curated by the ICD from the Lucy extension.

## What the ICD sees

Click the extension. A panel drops down with:

- **the progress board** — the onboarding roadmap for the week, one row per
  new start, a column per step;
- **a week picker** — they choose which week they are looking at;
- **terminate from there** — click somebody off the list;
- **show / hide terminated reps** for that week.

*"They just don't need to go to that sheet. They just want the preview of the
board."*

## Where it lives

A **live Google Sheet per ICD**, one tab per week. The sheet is the record —
it can be opened, shared and fixed by hand like any other — but nobody is
expected to open it. The extension is the way in.

## Who fills each column

Nearly all of this already exists. The board is mostly re-pointing automations
that run today against Alphalete's OBCL.

| Column | Source | State |
|---|---|---|
| Name, Last Name, Email, Phone | AppStream training calendar, Show Up = Yes | **built** (`office_admin/fdot.py`) |
| Start | the training date itself | **built** |
| Contact Added | `second_round_contacts` — it keeps a state file of who it put in the owner's reception contacts | exists, needs reading |
| Digi Docs | OwnerVille *View Progress* | **already automated** (`obcl_ov_sweep`) |
| Onboarding Quizzes (all six) | OwnerVille *View Progress* | **already automated** |
| UID Request | OwnerVille *View Progress* | **already automated** |
| Owner Submit | OwnerVille *View Progress*, blue when everything else is green and BG has passed | **already automated** |
| Blue Ink | `blueink_docs` | exists |
| Headshot Photo | the headshot upload, **on the ICD's own ECO machine** | exists for Alphalete; per-ICD is new |
| BG Status | the Sterling / fadv sync | exists |
| Added to APEX | the Apex run | **built** (`apex_new_starts/eco_run.py`) |
| **Final Status** | **the ICD, by hand, in the extension** | **the new bit** |

**Final Status is the whole point.** AppStream has no idea who was terminated:
a week read straight off the training calendar gave 29 people, 16 of whom had
already been let go — proven on Raf's office for w/c 11-02. Nothing in
ApplicantStream distinguishes them, and First Day of Sales is empty all week,
so there is no automatic signal to find. The ICD marking somebody off IS the
signal, and everything downstream (Apex especially) reads it.

## Where the work happens

**On each ICD's own ECO machine**, including the headshot upload. Not on Lucy 1,
not on Megan's laptop. Each office holds its own AppStream, OwnerVille and Blue
Ink; the extension presses a button and that office's machine does the work —
the pattern the background-check extension already uses.

## Order to build it

1. **The sheet** — create/seed a week's tab per office from the training
   calendar, with these columns. Idempotent: re-seeding a week never disturbs a
   cell somebody has touched.
2. **Relay reach** — the extension reads and writes the board through the same
   relay and sign-in as the background-check one.
3. **The panel** — board, week picker, terminate, show/hide terminated.
4. **Re-point the fillers** — `obcl_ov_sweep` and the rest write to this board
   as well as to Alphalete's OBCL.
5. **Headshot upload per ICD**, on their machine.

## Rules carried over

- **Ticks go ON only, never off** — the OV sweep's rule, and it exists because
  a tick is evidence something happened.
- **Never disturb a hand-typed cell.** The ICD's edits beat anything automatic.
- **A blank is a gap, not a zero** — a step that could not be read is reported,
  not silently left unticked.
- **Terminated rows are hidden, never deleted.** Somebody has to be able to ask
  what happened to a person, and the week's history is the answer.
