# Digi Docs + Onboarding Quizzes — the click-path

Source: Megan's Loom, "All in One Local Office - Raf - Google Sheets",
recorded 2026-08-24 (94s, no usable audio — the transcript is background
noise). Everything below is read off the video frames, not remembered.

This is the build spec for the THIRD new-start onboarding automation, the
sibling of `blueink_docs` (Blue Ink packet) and `headshots` (Headshot Photo).
It ticks two columns on the `D2D OBCL <m.d>` tab: **Digi Docs** and
**Onboarding Quizzes**.

## Who it runs for

The week's newly-created **`D2D OBCL <m.d>`** tab, reading EVERY chart on it —
Monday's has two. Same source, same reader as Blue Ink and the Headshot Bot
(`blueink_docs.roster` / `shared.obcl_charts`), and the same eligibility
block-list (Final Status / BG Status / Friday Confirmation), so all three steps
always agree on who this week's cohort is.

Workbook: https://docs.google.com/spreadsheets/d/1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4/edit?gid=1430069873#gid=1430069873

## Step 1 — add the rep to OwnerVille

**Onboard → View Progress → `+ Add Sales Rep`** (button above the table, left).
The modal has:

- an employee dropdown (`-Select-`),
- a team dropdown (`-Select a Team-`, with a "Click here to set up teams" link),
- **☑ Activate Now** — checked by default,
- `Close` / **`Add`**.

Then **search their name** in the table's search box (top right). If they don't
come up, the campaign's **Filter by Activation Date** radio is on
*Show Last 3 Weeks* — flip it to **Show All** and search again. This is the
same fallback `headshots/ov_upload.py` already implements, including the
"full names filter to zero, so probe on the last name" trick.

The campaign dropdown sits top-left (e.g. **RES-AT&T**); a rep lives under ONE
campaign, so the existing code tries each until the name matches.

## Step 2 — open the rep and reach the docs portal

Click **Edit** under the rep's name. That opens the **"<Name> - Set Status"**
modal — the SAME modal `headshots/ov_upload.py` already opens for the photo
upload, so the navigation to this point is code we have.

The modal is one collapsible row per onboarding step, each with its own state
chip. For a brand-new rep (Megan's screenshot, 2026-08-25):

| Row | State |
|---|---|
| LOGIN CREATED | `COMPLETED` |
| ONBOARDING DOCUMENTS | `REQUIRED ACTION` |
| BACKGROUND CHECK | `REQUIRED ACTION` |
| DRUG TEST | `REQUIRED ACTION` |
| FTC DIRECTV COMPLIANCE TRAINING | `PENDING` |
| AT&T PROTECTIVE ADVANTAGE COURSE | `PENDING` |
| AT&T BROADBAND FACTS | `PENDING` |
| AT&T PROTECTING CPNI | `PENDING` |
| AT&T COMPLIANCE – 2023 | `PENDING` |

Expand **ONBOARDING DOCUMENTS** (the chevron on the right). It reads
*"Digital doc not yet generated."* above a gray button,
**`🔗 Access Digital Doc Portal`** — that button is the way into the Generate
Document flow below.

**This modal is probably the better read-back for both ticks.** It names each
step in words with an explicit state chip (`COMPLETED` / `REQUIRED ACTION` /
`PENDING`), per rep, instead of colour-coded pills in a twenty-column
DataTable — and `_photo_pill` already exists as a warning about how easily
those pills mislead (both states render the same inner_text, which once made
every rep look like they needed a photo).

## Where the truth lives

Both columns read back from that same **Onboard → View Progress** table (p=201,
needs the session's `rqst` token appended). Confirmed columns, left to right:

`Name · Contact · Login Created · Onboarding Documents · Background Check ·
Drug Test · FTC DIRECTV Compliance Training · AT&T Protective Advantage Course ·
AT&T Broadband Facts · AT&T Protecting CPNI · AT&T Compliance – 2023 ·
2024 Consent Decree Manual CPNI/SPI · Upload Documents · AT&T UID Request ·
Service · Supplement · Owner Submit · Badge · SARA Plus · Progress`

Cell states: green ✓ with a timestamp = done, red ✗ = not done, yellow
**Pending** = in flight. The SARA Plus cell lists "Qualification Missing" as red
chips naming exactly which items are outstanding, and Progress shows a %.

Mapping to the OBCL columns:

- **Digi Docs** ← `Onboarding Documents`.
- **Onboarding Quizzes** ← the six training/compliance columns:
  `FTC DIRECTV Compliance Training`, `AT&T Protective Advantage Course`,
  `AT&T Broadband Facts`, `AT&T Protecting CPNI`, `AT&T Compliance – 2023`,
  `2024 Consent Decree Manual CPNI/SPI`.
  **Confirm with Megan whether all six must be green to tick it, or just the
  FTC course** — the page banner only says reps need the FTC course plus a
  passing background check before they can be activated in Sara Plus.

Two more columns are already sitting there for LATER steps, unautomated today:
`AT&T UID Request` (states: Requested / ✗) and `Owner Submit` (Approved / ✗) —
the OBCL tab has a "UID Request" and an "Owner Submit" column to match.

## Sending the docs (what "Digi Docs" means)

Reached either from the left nav (**Digital Docs → Generate Document**) or from
the rep's own **Access Digital Doc Portal** button in step 2. The form is
*Generate Document for Employee*:

1. **Employee** — dropdown, pick the new start.
2. **Bundle Type** — radio. The video picks
   **Base [Door to Door / Business to Business]**. Other options on screen:
   Base (Default), Base (Retail), Base (Wireless — MOD…), Commission Grid,
   Financing, Administrative.
3. **Select Bundle*** — dropdown → **"Door to Door- General 1"**.
4. **Select Associated Commission Bundle(s)*** — checkboxes:
   - ☑ **AT&T Door to Door with Drug Free Workplace Policy**
   - ☐ Energy D2D- Commission Grid
   ("Select all Commission bundles that apply.")
5. **Get Documents for Selected Bundle** → **Generate Bundle**.

Result banner: **"Successfully Added Document(s) for <Name>"**, listing the
bundle it created:

1. Mutual Agreement Affecting Three Important Rights
2. Policy Against Discrimination Harassment and Retaliation- General
3. Drug Free Workplace Policy- General
4. Drug Testing Consent Form
5. Compensation Schedule D2D
6. GPS Tracking Policy D2D
7. AT&T Door to Door Com… (truncated on screen)
8. AT&T Compliance Manu… (truncated on screen)
9. Cybersecurity Policy

The page then shows the email OwnerVille sends the rep with the docs — so
generating the bundle IS the send. There is no separate mail step.

A rep who is not on View Progress yet is added first with **Add Sales Rep**
(button top-left of the progress table; a modal with an employee dropdown).

## Open questions before this can be built

1. **Bundle selection per rep.** The video shows one rep getting Door to
   Door- General 1 + the AT&T commission bundle. Is that the same for every
   D2D new start, or does it vary by campaign (Energy reps presumably take
   the Energy D2D grid)? Guessing here mails the wrong contract.
2. **What "Onboarding Quizzes" ticks on** — all six training/compliance
   columns green, or just the FTC course? See above.
3. Whether generating a bundle twice for the same rep re-sends or errors
   (blueink's rule is "already has one → skip"; this needs the same guard).

## What it inherits from the two built siblings

- Roster + eligibility: `blueink_docs.roster` reads every CHART on the newest
  dated OBCL tab (Monday's has two) and applies the Final Status / BG Status /
  Friday Confirmation block-list. Same cohort, same skips. (Megan 2026-08-25:
  "headshot and Blueink both follow this and are built to read multiple charts
  on this tab — we need to follow the same idea".)
- OwnerVille session + rep lookup: `headshots/ov_upload.py` — the
  campaign-dropdown walk, the DataTables search, the "search by last name,
  full names filter to zero" trick, and the pill reader.
- Tick + tint + Slack summary: `blueink_docs` tints the name light green on
  send and posts who still needs doing by hand to
  #11280-alphalete-marketing-inc-rafael-hidalgo.
