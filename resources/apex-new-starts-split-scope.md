# New Starts → Apex for other offices — scope

**Megan, 2026-11-06**, over three messages:

1. "can the blue ink live on the ECO machine and then the admin be given the
   info needed?"
2. "what if the ICDs relay machine also just logs into apex and blueink — the
   admin is just saying the task should run and who to run it for?"
3. "No other office uses the OBCL so we will need to find another way to pull
   the correct reps" → "Prob anyone marked as showed up on the training
   calendar for that week on app stream"

Three separate questions. Short answers: the roster source is settled and
already readable; the two logins are already-solved patterns; and the whole
thing comes down to **one decision about the Social**.

---

## 1. Where the reps come from (settled)

Today's source does not generalise, and it is worth being precise about why:
the `New Starts/Raf` box on the **org** sales board is Raf's org, and the OBCL
is used for two further things — the start-date fallback and the
"Added to APEX" tick. Another office has none of that.

**Megan's answer is the right one and it maps onto an exact AppStream status.**
`Showed Up - FDOT/BOB` is a real status, named in `ars-processes-2026.md` and
already listed in `sms_audit/analyze.py`. FDOT/BOB is one of the four tabs on
the V2 Applicant Interview Calendar (`p=1511`): *1st Interview / 2nd Interview
/ FDOT/BOB / First Day of Sales*.

So: **the FDOT/BOB calendar, rows marked Showed Up, for that week.**

This is per-office for free — the calendar belongs to an ApplicantStream
account, which is exactly how the background-check extension already scopes
itself.

**Most of the reader already exists.** `automations/office_admin/offered.py`
reads the same calendars for background checks and already:

- recognises both the old and the V2 calendar and fails rather than guessing;
- finds columns by **header text**, never by position;
- knows the tabs have to be clicked and that the table pages 50 at a time;
- already reads the **Show Up** column (that is how it knows a Show Up = No row
  has no offer dropdown at all).

A new `fdot.py` is a sibling of it, not a new capability. The risk is the usual
one: it must **fail loudly** if it cannot find the FDOT/BOB section, never
return an empty list — a wrong section here would create payroll records for
people who did not start.

### What replaces the OBCL

| What the OBCL does today | For an office without one |
|---|---|
| start-date fallback | **the FDOT/BOB date itself** — the training date is the start, and it is on the row we are already reading |
| the "Added to APEX" tick | **the relay's own job history**. The background-check flow already writes a RESULT per job and reads it back (`_admAlready`) to show "already sent". Same mechanism, no new sheet. |

Raf's org keeps its board + OBCL path unchanged. This is an additional source,
not a replacement — [[feedback_no_cross_report_data_reuse]] applies: each
office pulls its own.

---

## 2. The two logins (both already-solved patterns)

**Blue Ink — not a login at all.** It is an API key (`blueink-creds.json`, or
`BLUEINK_PRIVATE_API_KEY`). `blueink-creds` is already whitelisted for
`push_cred_file`, so a machine with a control tab can be given it untouched.

**Apex — already done, for a different report.**
`automations/icd_alerts/apex_signin.py` exists: it opens Apex in Lucy's own
browser so **the owner signs in once, by hand**, and the session is kept in a
dedicated Chrome profile. No password is ever saved or typed by Lucy — the same
rule as `box_signin` / `ov_signin`. It is read-only today because the PNL only
reads; that is a policy choice, not a technical limit.

And `apex.py` already drives Apex to add a new start from a real session —
including `fill_ssn`, which takes a typed Secret.

So the machine half of Megan's idea is mostly assembled already.

---

## 3. The one real decision: does a machine get to hold the Social?

Everything else here is plumbing. This is not.

Apex will not save the record without a Social. Today the number is **never
held by this report at all** — a decision made on 2026-09-05 and defended in
the code:

- `blueink_data.py` sees each Social in the Blue Ink API response, records only
  `has_ssn = True`, and **drops the value**.
- `ssn_prompt.py` asks the person at the keyboard, in a masked box. `str()` of
  the result is **a row of dots**, so a stray print or an exception that happens
  to include it cannot spill the number into a terminal, a log or Slack.
- `apex.py` keeps an explicit `NEVER_TYPE` list: ssn, social security, routing,
  account number.

That is three independent layers, all built on the same premise. "The ICD's
machine just runs it" requires removing the premise.

### Three ways forward

**A. Machine does everything, including the Social.** The ECO machine reads the
Social from the Blue Ink API, holds it in memory, types it into Apex, discards
it. The admin genuinely just says "run it".

This is not automatically unacceptable — a number in RAM for a few seconds on
one machine is a far smaller exposure than a number in a Google Sheet, and the
relay would never see it. But the leak paths that the current design removes by
simply never having the number would all need closing, deliberately:

- the discard in `blueink_data.extract` (the change itself)
- the masked-`str` guarantee has no equivalent on an automated path — anything
  that logs a field value, or an exception that quotes one
- the Hub's own log display, which the operator reads
- screenshots, if any step takes them
- the Chrome profile: form autofill, session storage, and anything Apex itself
  caches in it
- `NEVER_TYPE` exists to stop exactly this and would need a documented hole

Doable. Not a small change, and it is the kind that is easy to get 95% right.

**B. Machine does two of the three pages, the admin types only the Socials.**
The Social lives on the **Tax & Bank** page; creating the employee does not need
it (`PAGE_OF["new"]` has no SSN). So the ECO machine can create the person, fill
and save the **Employment Record** and **User Profile**, and leave only the tax
page.

The admin's whole job becomes: open a panel that has already found everyone,
and type N numbers with each signed W-4 already on screen beside the box. No
Apex navigation, no lookups, no creating anybody, no Blue Ink.

Every guarantee above survives untouched.

**C. The split from the earlier scope** — machine builds the list, admin runs
the whole fill in their own browser. Least new code; the admin still does the
most work.

**My recommendation: B.** It is most of the automation for none of the safety
change, and it is the only one of the three where I would not be asking you to
weigh a trade-off you cannot easily check afterwards. A is a legitimate choice
if you want it — it just needs to be chosen, not drifted into.

---

## Work items (for B)

| # | Where | What | Size |
|---|---|---|---|
| 1 | `automations/office_admin/fdot.py` (new) | FDOT/BOB calendar → Showed Up, for a week, per account. Sibling of `offered.py`; fails loudly on an unrecognised page | medium |
| 2 | `automations/apex_new_starts/roster.py` | a second roster source behind the existing interface, so Raf's board path is untouched | small |
| 3 | `automations/icd_alerts/apex_signin.py` | allow the kept session to be used for writing, not only the PNL read | small, but a **policy change** — say so out loud |
| 4 | `automations/apex_new_starts/eco_run.py` (new) | create + fill + save pages 1 and 2 from the ECO machine, stop before the tax page, record who got how far | medium |
| 5 | `resources/icd-alerts-relay.gs` | an `apex_week` job kind; the result carries who is ready for Socials. One row per person (~1.2 KB measured) rather than a week in one cell | ~150 lines, **needs an Apps Script redeploy** |
| 6 | `extension/apex-new-starts/` | relay half (`background.js`/`config.js` near-verbatim from office-admin), sign-in, and a tax-page-only mode | medium |
| 7 | ECO machine | Blue Ink key via `push_cred_file`; Apex signed in once by the owner | 15 min |
| 8 | tests | the FDOT reader against a real saved calendar; the no-Social pin; the relay round trip; "stops before the tax page" | medium |

---

## Shared Apex account (Megan, 2026-11-06: "the admin and ICD both use the same
account logins — for apex")

**This answers the rights question.** Same account means Lucy can create and
save exactly what the admin can. The biggest unknown in this plan is gone.

**It replaces it with a smaller one: does Apex allow two sessions on one
account?** Nothing in this repo records it. `ProfileInUse` in `apex.py` is only
about the local Chrome profile — a second run on the SAME machine — and says
nothing about the server. This codebase has been bitten by this class twice
already: SaraPlus is one login per account
([[reference_saraplus_session_resume]]) and OwnerVille is one session per
machine ([[reference_ownerville_session_identity]]). AppStream is the exception
where logins are unlimited.

**Option B survives either answer**, which is the main reason to prefer it. The
two halves are *sequential*, not simultaneous: the ECO machine creates the
people and fills pages 1 and 2, finishes, and releases the session; only then
does the admin sign in to type Socials. The relay job completing is already the
handoff signal. So a single-session Apex makes the handoff explicit rather than
breaking the design — we need the answer before scheduling it, not before
choosing it.

**The 2FA chore gets sharper, though.** Apex texts its code to one phone. When
Lucy's kept session dies, the code goes to whoever owns that number — not to
the ICD's machine. SaraPlus's `code_forward` does not transfer: that one works
because SaraPlus *emails* its codes and the office forwards those mails. Under
B this is a few minutes every few weeks, not per run, but it should be a known
chore rather than a surprise at 8am.

**One more thing the same account implies:** if several offices share one Apex
account, their runs collide with each other too, not just with their admin.
That decides whether runs need to be serialised across offices.

---

## Check these before building anything

1. **Does Apex allow two sessions on one account?** Five minutes: sign in on the
   ICD machine, leave it, sign in as the same account elsewhere, then reload the
   roster on the first and see whether it survived. Then reverse it. This decides
   the scheduling, not the design.
2. **A real FDOT/BOB calendar page**, saved, from an office that is not Raf's.
   The reader is only as good as the page it was written against, and
   `offered.py` exists in its current shape because it was written from a real
   screenshot of Omar's calendar rather than from a guess.
3. **Does every office's FDOT/BOB row carry an email?** Blue Ink matching is by
   email where it can be (that is the difference between proof and judgement —
   `matched_on`). Without one, matching falls back to names.

---

## Risks

- **The Apex login cannot be automated.** Apex texts a code. The owner signs in
  by hand, once, and the session is kept — exactly like `box_signin`. If that
  session dies mid-week, somebody has to sign in again.
- **Doc links expire in a few hours**, so the week cannot be built the night
  before. Under B the admin needs them at the moment they type, so a *refresh
  the documents* action should ship with it, not after.
- **A wrong roster creates real payroll records.** This is the sharpest risk in
  the whole plan and it is why #1 above must fail loudly rather than return an
  empty list. Pair it with the duplicate guard that already checks All Employees
  before creating anybody.
- **The relay is a Google Sheet.** Under B it carries names, start dates,
  addresses and dates of birth for a few days. Not Socials. If that is not
  acceptable the answer is to give the admin the key instead, which is the thing
  we are avoiding.
