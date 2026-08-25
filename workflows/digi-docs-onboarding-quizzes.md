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

## When it runs — Monday 7:45am

Alongside Blue Ink's 7:30 (Megan 2026-08-25). Different machines, so no
contention: Blue Ink is Lucy 2, this is Lucy 3. Same cohort, same morning.

The neighbour that matters is on Lucy 3: the headshots Monday thread posts at
8:30 and its tick runs every 5 minutes all week. 7:45 leaves the batch about 45
minutes clear. Separate browser profiles stop them blocking each other outright,
but if the batch ever runs past 8:30, move the thread rather than have two jobs
driving the same OwnerVille pages for the same reps at once.

## Which machine — Lucy 3

**Both phases on one machine, necessarily.** They share a single OwnerVille
session: phase 2 flips the activation-date filter to Show All and then works on
the reps phase 1 just added. Split across boxes that is two sessions and no
shared state.

**Lucy 3**, because OwnerVille already lives there — `headshots/ov_upload.py`
drives the same Onboard → View Progress page for the same weekly cohort from
that machine, so the session, the login and the Turnstile workaround are
already solved. It is also the lightest box: 17 scheduler handles against Lucy
1's 59 and Lucy 2's 56.

Two things that follow:

- **Its own browser profile** (`.browser_profile_digi_docs`), never a shared
  one. headshots keeps its own for exactly this reason (profile-lock wedge,
  2026-08-19), and the headshots tick runs **every five minutes all week** on
  Lucy 3 — a batched send is a long run, so sharing a profile would put the two
  in each other's way most of the time.
- **Don't schedule the batch over the Monday 8:30am headshot thread.** Separate
  profiles stop them blocking each other, not from hammering the same site with
  the same reps on the same morning.

### Why the merged card spans three machines

**It is all Raf's logins** (Megan 2026-08-25), and Lucy 3 mirrors Lucy 1's
accounts — rcaptain AppStream, ownerville, Tableau (see
`workflows/lucy3-provisioning.md`). So the usual *wrong box = wrong data* rule
does **not** apply here: that rule is about Raf vs Carlos, and nothing in
new-start onboarding is Carlos's.

What actually pins each step to a machine is which **session is seeded** there:

| Step | Machine | What's seeded there |
|---|---|---|
| BG Check Sync | Lucy 1 | the `raffi127@` gmail app-password |
| Blue Ink | Lucy 2 | a hand-seeded Blue Ink browser session |
| Headshot Photo | Lucy 3 | an OwnerVille session |
| **Digi Docs** | **Lucy 3** | an OwnerVille session |

Those are all re-seedable, so **consolidating all three onto one box is
possible** — it is a session-seeding job, not an identity problem. Nobody has
asked for it, and it is not free, but it is worth knowing the option is open.

One thing to know before anything moves: two machines holding warm sessions on
the **same** OwnerVille account can kick each other's logins, which is itself a
known wedge cause. That is why the OV keep-warm holder runs on exactly one box
(Lucy 1) and Lucy 3 logs in on demand. This report follows headshots and does
the same.

The card still carries no `daily_runs` count regardless — three clocks on three
machines means no fixed N is honest.

## Run it in phases, not one flow per rep

Megan 2026-08-25: **add every new rep first, then send every bundle.** Not a
full add-then-send cycle per person.

That is the right shape for more than tidiness:

- **The two phases live on different pages.** Add Sales Rep is a modal on
  View Progress — you add N reps without ever leaving that page. The bundle
  flow opens a NEW TAB and walks a six-step reveal form. Interleaving them
  means navigating back, re-searching and re-opening the modal for every
  single person, paying the expensive transition N times instead of once.
- **The activation-date filter gets flipped once.** A just-added rep may not
  appear under the default *Show Last 3 Weeks*. Phase 2 sets **Show All** one
  time at the start rather than rediscovering that per rep.
- **A clean failure boundary.** If phase 2 dies halfway — and the known
  failure for both Blue Ink and OwnerVille is exactly this, a session going
  stale mid-run — everyone still EXISTS in OwnerVille and nothing is
  half-added. The roster is left consistent whatever happens next.
- **Only phase 2 sends.** Phase 1 writes nothing to a rep and mails nobody, so
  it is safe to run and re-run freely. That maps to `--add-only` / `--send-only`
  flags, the same way `blueink_docs` splits `--send` from `--sync-completed`,
  and it gives a scoped re-run when one phase needs repeating.

**Which makes the re-send guard load-bearing, not optional.** A batched phase 2
is a long run that WILL sometimes stop in the middle, so re-running it is the
normal path, not the exception — and a re-run must skip whoever already has
their documents. Until the "what does generating twice do" question is answered,
the safe reading is: skip anyone whose **ONBOARDING DOCUMENTS** row is not
`REQUIRED ACTION` / "Digital doc not yet generated." Blue Ink's rule, same
reasoning — a hand-send must never be duplicated.

So the run is three passes:

1. Read this week's OBCL tab (every chart) and apply the eligibility block-list.
2. Add every eligible rep who isn't in OwnerVille yet. Ticks nothing.
3. For each rep still showing `REQUIRED ACTION`, generate the bundle, then tint
   their **Digi Docs** cell. Post the by-hand leftovers to #11280 at the end.

### What gets written back, exactly (Megan 2026-08-25)

- **Tint the `Digi Docs` CELL light green.** That is the whole write.
- **Do NOT tint the name.** Blue Ink tints the first name in column D; this one
  does not. Only its own cell.
- **Do NOT tick the checkbox — ever.** A person hand-marks it once the docs are
  actually done. The tint is the automation saying *"I sent it"*; the tick is a
  human saying *"this is complete"*, and those are different claims. The same
  cell carrying both is Blue Ink's pattern, but there the code ticks the box off
  a Blue Ink "signed" list it can actually verify. Here we have no such source,
  so writing the tick would be the software asserting something nobody checked.

That also gives a cheap second re-send guard: an already-tinted `Digi Docs` cell
is our own record that this rep was sent, readable without an OwnerVille round
trip. Belt and braces with the `REQUIRED ACTION` check, which remains the
authoritative one.

## Step 1 — add the rep to OwnerVille

**Onboard → View Progress → `+ Add Sales Rep`** (button above the table, left).
The modal has:

- an employee dropdown (`-Select-`),
- a team dropdown (`-Select a Team-`, with a "Click here to set up teams" link)
  — **leave it alone. No team gets selected** (Megan 2026-08-25). It looks like
  a required field sitting between two things you do touch, which is exactly
  how it would end up filled in by mistake.
- **☑ Activate Now** — checked by default, leave it,
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
**`🔗 Access Digital Doc Portal`**.

That button **opens a NEW TAB** (Megan 2026-08-25), which is where the campaign
gets chosen and the bundle generated. Implementation note: a click that spawns a
tab has to be caught with `context.expect_page()` — the click alone returns
before the new page exists, and patchright's `evaluate` runs in an isolated
world, so the usual "read it off the current page" shortcut will silently look
at the OLD tab.

**This modal is probably the better read-back for both ticks.** It names each
step in words with an explicit state chip (`COMPLETED` / `REQUIRED ACTION` /
`PENDING`), per rep, instead of colour-coded pills in a twenty-column
DataTable — and `_photo_pill` already exists as a warning about how easily
those pills mislead (both states render the same inner_text, which once made
every rep look like they needed a photo).

## Step 8 — back on Set Status, tick the attestations and save

Return to the rep's **Edit → "<Name> - Set Status"** modal and, in order:

1. Expand **BACKGROUND CHECK** → tick the single box:
   *"Elite or Elite Extra Background Check Required"*.
2. Expand **DRUG TEST** → tick **two** boxes:
   - *"Alphalete Marketing, INC. acknowledges that the campaign requires a
     passing 4 panel drug screen within the first 30 days of participating in
     the campaign. Alphalete Marketing, INC. confirms that it will comply with
     the requirement."*
   - *"Alphalete Marketing, INC. has reviewed the drug screen and confirmed that
     it passes Alphalete Marketing, INC.'s drug screening requirements."*
3. Expand **SERVICE** → select the radio **`RES-ATT`** (the other option is
   `RES-ATT-OOF`). Constant, not a literal — OOF is presumably out-of-footprint
   and another office or campaign will want it.
4. **Save Changes**, bottom right.

### The attestation checkboxes — decided

The second drug-test box is not a status flag; it states that *"Alphalete
Marketing, INC. has reviewed the drug screen and confirmed that it passes."*
Raised with Megan 2026-08-25 because it is the only action in this flow that
asserts something to AT&T rather than writing to our own systems.

**Her answer: tick them — "we know how to do it."** Decided; the automation
does what the hand process does, and this is not to be re-litigated by a later
session.

One thing carried over from raising it, because it costs nothing: the run
records per rep that it ticked these, so the attestation is auditable after the
fact rather than invisible.

### The full Set Status row list

`LOGIN CREATED · ONBOARDING DOCUMENTS · BACKGROUND CHECK · DRUG TEST ·
FTC DIRECTV COMPLIANCE TRAINING · AT&T PROTECTIVE ADVANTAGE COURSE ·
AT&T BROADBAND FACTS · AT&T PROTECTING CPNI · AT&T COMPLIANCE – 2023 ·
2024 CONSENT DECREE MANUAL CPNI/SPI · UPLOAD DOCUMENTS · AT&T UID REQUEST ·
SERVICE · SUPPLEMENT · OWNER SUBMIT · BADGE · SARA PLUS`

The six training rows stay `PENDING` through all of the above — **the rep
completes those themselves.**

**And that is where this report stops (Megan 2026-08-25): no completion sweep.**
Blue Ink polls for signed packets because a signature is a thing we asked for
and are waiting on. These six are the rep's own coursework; watching them would
mean polling for work we neither perform nor can hurry along, to write a tick
whose only reader is a person already looking at the same sheet. `Onboarding
Quizzes` stays a human column, and the "do all six count or just FTC?" question
retires unanswered with the sweep that would have needed it.

So the report is **send-only**: add the reps, generate the bundles, tint the
`Digi Docs` cell, post the leftovers. Everything else on that tab belongs to
somebody.

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

In the new tab from step 2, **choose the campaign they need onboarded for**
(the left nav route, **Digital Docs → Generate Document**, reaches the same
form). Then *Generate Document for Employee*, in this order — the form reveals
itself a step at a time, so the whole thing is NOT on screen at once:

1. **Employee** — the new start.
2. **Bundle Type** — **`Base (Door to Door/Business to Business)`** for
   everyone right now (Megan 2026-08-25). Other options: Base (Default),
   Base (Retail), Base (Wireless — MOD…), Commission Grid, Financing,
   Administrative. Keep it a named constant; a wireless or retail office will
   want a different one.
3. Hit **`Generate Bundle`**. This does NOT generate anything yet — it reveals
   the next dropdown (Megan 2026-08-25).
4. **Select Bundle*** — now visible. Choose **`Door to Door- General 1`**.
   It is a typeahead select (a text input inside the open list), not a plain
   `<select>`, so it needs a click-then-type-then-pick, not `select_option`.
   Under this bundle type the list holds exactly ONE real option besides the
   `-Select a Bundle-` placeholder. **Assert that.** If it ever offers more
   than one, the campaign or the plan changed and the run should refuse and
   say so rather than pick the first row — the whole point of pinning the
   bundle is that nobody gets mailed the wrong contract.
5. **Select Associated Commission Bundle(s)*** — these appear only ONCE the
   bundle is chosen (Megan 2026-08-25). Tick
   ☑ **AT&T Door to Door with Drug Free Workplace Policy**.
   Leave ☐ Energy D2D- Commission Grid unticked. (The note beside them reads
   "Select all Commission Grids that apply. If you are missing a Commission
   Grid, go to 'Download' to download it.")
6. **`Get Documents for Selected Bundle`** — NOT the submit either. It opens
   a long per-document form (Megan 2026-08-25).
7. **Scroll to the bottom of that form and hit the gray `Generate Document`
   button.** THAT is the submit.

### The per-document form (step 6 → 7)

One titled section per document in the bundle, each saying how many fields it
found, e.g.:

- **Drug Free Workplace Policy- General** — *(Found 1 fields)* → `Company Name:` *
- **Drug Testing Consent Form** — *(Found 2 fields)* → `EMPLOYEE NAME:` *,
  `Company Name:` *
- **GPS Tracking Policy** — *(Found 1 fields)* → `Company Name:` *

Above them sit `Commissionable Product 1…25` / `Amount Due for Product 1…25`
pairs, all reading **N/A**.

**ANSWERED (Megan 2026-08-25): nothing is hand typed — they pre-fill.** In
Megan's screenshot `Company Name` and `EMPLOYEE NAME` render as empty inputs
with a red required asterisk, but the success banner afterwards says "click
'View' to see the document with any form field values assigned to each
document", which reads like something assigns them. It matters a lot:

- If they auto-fill, step 7 is just scroll-and-click.
- If they do NOT, the run has to fill a variable number of fields whose count
  and labels come from the bundle, and a batch that skips them either fails
  validation or — far worse — generates contracts with a blank employee name
  on them.

So step 7 is scroll-and-click. **The verify stays anyway**: check every
required field is non-empty before clicking Generate Document, and refuse that
rep rather than submit. Megan's answer was "I don't think anything is hand
typed" — a belief about a form none of us has watched fill itself, and the cost
of it being wrong is a contract mailed with a blank employee name on it. The
guard turns that from a bet into a refusal, and costs one read. This is the same instinct as asserting the bundle
dropdown holds one option: the failure to design out is a legally-meaningful
document going to someone with the wrong or missing details.

Note the form is LONG (25 product pairs plus a section per document), so the
button needs a scroll-into-view, not a blind click at a fixed position.

**The form reveals itself one control at a time.** Employee + bundle type →
`Generate Bundle` reveals the bundle dropdown → choosing the bundle reveals the
commission checkboxes → `Get Documents for Selected Bundle` submits. Nothing
below the current step exists in the DOM yet, so every step has to WAIT for its
control to appear rather than assume a static form. Getting this order wrong is
the single easiest way to build something that clicks a button that isn't there
and reports success.

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

## Guards the build keeps

Every open question is now answered. Three defensive rules stay in anyway, each
cheap and each guarding an expensive mistake:

1. **Assert the bundle dropdown holds exactly one option.** If it ever holds
   more, the campaign or the plan changed: refuse the rep and say so. Taking
   row one of a list that quietly grew is how someone gets the wrong contract.
2. **Verify the required fields are non-empty before submitting.** They
   pre-fill (Megan: "I don't think anything is hand typed"), but that is a
   belief about a form nobody has watched populate itself, and being wrong means
   a contract mailed with a blank employee name. One read turns it into a
   refusal.
3. **Skip anyone not showing `REQUIRED ACTION` on Onboarding Documents.**
   OwnerVille refuses a second generate for the same rep (Megan 2026-08-25), so
   this is not what stops a double-send — the platform is. It is what keeps a
   re-run quiet, and what keeps a refusal meaningful: if we only ever generate
   for reps we think still need it, a "won't allow" means our picture is wrong
   and deserves saying, rather than being the expected noise of every re-run.

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
