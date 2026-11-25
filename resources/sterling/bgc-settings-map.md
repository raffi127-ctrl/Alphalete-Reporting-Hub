# Sending a background check: every setting it depends on

Written 2026-11-20. The click path itself is `portal-map.md`; this is the
answer to "what has to be set, and who sets it", because a press that looks
fine and sends nothing is the failure this map exists to prevent.

The chain is: **admin presses a button** → the office admin page queues a
`bgc_send` job → the relay hands it to that office's ECO machine →
`sterling_send.send_invites` drives Sterling.

Five places hold settings, and they are five different places on purpose —
but only two of them are ever *asked for*.

---

## 1. Our code — `automations/office_admin/config.py`, the `OFFICES` list

Edited by us, in the repo. Nobody outside can set these.

| Setting | What it decides | Default |
|---|---|---|
| `bgc_mode` | **`dry` or `live`.** This alone decides whether a press really sends. | `dry` |
| `appstream_id` | Which ApplicantStream office the names come from | — |
| `key` | The LucyEco office key the relay routes on | — |
| `ov_program` | The OwnerVille campaign the person is looked up on | `""` |
| `tz`, `alert_at`, `channel` | When and where the "not sent yet" alert goes | Central, 16:30 |

**`bgc_mode` is the one to watch.** A new office defaults to `dry`. The admin
presses the button, the page says "Sent to your office computer", the job runs,
Sterling is driven all the way to the review page — and stops before Send
Invites. Everything reads like success. Nothing was sent. No one is told the
office is in dry mode, because the mode is ours, not theirs.

## 2. The Office Settings tab — State and City

The only Sterling answer the office gives, and the only one on the LucyECO
Onboarding enrolment form today (`eco_onboarding/settings.py`, `STERLING`).

Becomes Sterling's "Location of Job/Position", which must read exactly
`Plano, TX, USA` — city, two-letter state, USA (`location_text`). The saved
state is the full name and is shortened here; a state we cannot shorten raises
rather than guesses.

Checked twice on purpose: the admin page refuses the press without it
(`actions.send_bgc` → "Set your office's city and state first"), and
`send_invites` refuses again on the office machine. Sterling's form will not
submit without it, so neither does this.

## 3. The ECO machine — the Sterling login

Saved once by `sterling_setup`, held at `config.STERLING_CREDS_PATH`, chmod
600. Never in the repo, never on a sheet, never sent anywhere.

No login saved → the job answers *"this computer has no Sterling login saved
— run sterling_setup"* and sends nobody. That is the right answer, but it is
found at send time, not at enrolment.

## 4. The code mail — Sterling texts nothing, it emails

Sterling asks for a code at **every** sign-in (`noreply@us.fadv.co`,
"Authentication Request"). Same road as SaraPlus codes:

- the office's Gmail filter forwards **only** those code mails to the
  reporting inbox;
- the office's address goes on the relay workbook's **Sterling Code Mail** tab;
- at the code screen, Lucy 1 (`code_answer`, service `sterling`) finds it and
  hands it back.

Two settings, both set by hand during setup, neither on any form.

## 5. Sterling's own account — read live, never stored

These are not configured anywhere. Each run opens the dropdown and picks by
rule, and **anything ambiguous is a stop, never a guess**:

| Field | Rule | Code |
|---|---|---|
| Job Position | the one option containing "Elite" — exactly one, else stop | `pick_elite` |
| Screening Package | same rule | `pick_elite` |
| Bill Code | the one real (non-placeholder) option — exactly one, else stop | `pick_bill_code` |
| Bill To, WFD Workflow, Charge Type | prefilled per account | never touched |

Each account lists three Position/Package options: **Drug Screen**, **NBR**,
and the Elite one ("Sterling - Elite" on some accounts, "Sterling Elite /
Extra" on others). Picking by the word "Elite" survives both spellings, which
is why it is a rule rather than a stored string.

---

## What is not asked anywhere

1. **`bgc_mode`.** It is a line in our Python. An office enrolling today is in
   dry mode and nothing says so. This is the one that lets a press look like a
   send.
2. **The Sterling login and the code-mail forwarding.** Two setup steps with no
   entry on the enrolment form; they are discovered missing at send time.
3. **Nothing about the drug screen.** "Drug Screen" is already one of the three
   options on every account, so the send path is the same walk with a different
   pick — but `pick_elite` has no counterpart for it, and the **Drug Screen
   Information** table on the form (Source · Test Type · Registration Method ·
   Reason For Test · COC/Site/Kit · App Notify) has never been seen filled.
   One look at a live account answers whether any of it is required.

## Where a send can stop, in order

| Stops at | Says | Anyone invited? |
|---|---|---|
| admin page | "Set your office's city and state first" | no |
| office machine | "no Sterling login saved" | no |
| sign-in | code never arrived | no |
| Order Settings | "expected exactly one Elite job position, found 0" | no |
| Location | "no location suggestion for Plano, TX, USA" | no |
| Bulk Upload | the count found ≠ the count uploaded | no |
| **Send Invites** | **reported UNCONFIRMED, never retried** | **maybe** |

Everything before Send is safe to re-run. A failure *at* Send is the one case
nobody retries automatically: a second press could invite the same people
twice, and Sterling will not invite the same email twice anyway.

---

## The drug screen — what Raf's Loom actually shows (2026-11-25)

Loom `ba6bf293febd4e4baf4dbb01c9912ecc`, **"How to Check Drug Test Status"**.
Raf's own opening line: *"I'm assuming this video is for Megan. Because I
think we're gonna automate it. But we're gonna automate how to CHECK that the
drug tests have been done."*

**It does not show sending one.** It is three minutes of looking a rep up in
First Advantage and reading their status. So nothing in it verifies the send
mapping, and the send route below is still unwatched.

What it DOES establish:

1. **Drug Screen is a POSITION value.** *"you see the drug screen panel as the
   position"* (0:51). `sterling_send.pick_drug_screen` picks Position and
   Screening Package by the word "drug", which matches "Drug Screen Panel".
   The Position half is confirmed; the Package half is still inferred.
2. **The portal is the same sign-in.** The address bar reads
   `auth.sterlingcheck.app`; the dashboard it lands on is First Advantage
   branded ("Account Dashboard", "ScreeningDirect"). Same road the background
   check already takes.
3. **The status word is "clear", not "pass"** (0:51-1:04). *"It won't say
   pass."*
4. **"Complete" means the invite completed, not that they passed** (2:18,
   2:58). Raf: *"it says the same thing as the background check... it doesn't
   say pass or fail."*

### THE ONE THAT BREAKS SOMETHING WE ALREADY RUN

> *"that's the only email we get when I do their back or their drug tests, so
> it doesn't actually say drug tests on it."* — Raf, 1:36

**A drug screen result arrives as the SAME email as a background check
result.** `bg_check_sync/parse.classify` matches on subject phrases —
"E-Invite for X is Complete", "Background Check for X is complete" — and has
no way to tell the two apart, because the subject does not say.

So the moment drug sends go live for an office, that office's drug-screen
result emails will be recorded as BACKGROUND CHECK statuses. For somebody who
has both, whichever lands second overwrites the first. A rep could read as
background-check-complete on the strength of a drug screen.

This is why `drug_mode` ships "dry" everywhere and why arming it is not a
one-word change: `bg_check_sync` has to be able to tell the two apart first.
The only signal available is correlation — we know who we sent a drug invite
to and when, from the `send_drug` rows on 'Admin Requests' — because the email
itself carries nothing.

Raf has not solved this on his side either: *"So I think the only way is you
check"* (3:07).

### The send route, answered (2026-11-25)

Asked directly, the office's answer: **"it's the exact same as sending the BG,
you just check drug test instead."**

So the walk does not change at all — Client Hub, Invite Candidate, Position,
Screening Package, Location, bulk upload, Send Invites — and the only
difference is which option is picked. That is exactly what
`sterling_send.picker_for("drug")` does: the same `fill_order`, with
`pick_drug_screen` in place of `pick_elite` on BOTH dropdowns, because the
background check picks Elite on both.

NOT A SECOND ROUTE, THEREFORE, AND DELIBERATELY SO. A copy of the sign-in, the
code mail and the upload would be a second thing to keep working, and the half
that breaks is always the one nobody is watching.

### Still unseen

Only one thing, and it is smaller than it was: whether the **Drug Screen
Information** table (Source · Test Type · Registration Method · Reason For
Test · COC/Site/Kit · App Notify) has to be filled when the package IS a drug
screen. It has only ever been seen reading "No Records Found", on a
background-check order. "Exactly the same" implies it is left alone there too,
but nobody has watched a drug order go through, so the first live one is where
that is confirmed -- and if it does ask for something, the run stops at that
step and says which field, rather than guessing at a Reason For Test.
