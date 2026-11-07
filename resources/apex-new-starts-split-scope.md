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

So: **the training calendar, rows marked Show Up = Yes, for that week.** On
the old calendar (`p=102`) that is the purple `FIRST DAY OF TRAINING` section —
see the page spec below. On V2 it is the `FDOT/BOB` tab.

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


### The page itself (Megan's screenshot, 2026-11-06 — Raf's office)

Read off the real calendar rather than assumed. **This is the OLD calendar
(`p=102`), not V2**, so the reader has to handle both exactly as `offered.py`
does.

**URL** — any date can be opened directly, no clicking through:

    applicantstream.com/index.cfm?p=102&newOfficeId=<account>&cd=MM%2FDD%2FYYYY

`newOfficeId=11280` and `cd=11/02/2026` on the example. That matches
[[reference_appstream_calendar_reads]]: the calendar goes to past days.

**The section is a purple banner row reading `FIRST DAY OF TRAINING`**, and the
same page carries a **`FIRST DAY OF SALES`** section above it (empty on the
example: *"No First Day of Sales found for 11-02-2026"*). Only rows under the
training banner count. This is the same trap `offered.py` already guards for
SECOND INTERVIEWS, and for the same reason — the wrong section here creates
payroll records for people who have not started.

**Show Up is a pair of radio buttons, Yes / No** — not a dropdown and not text.
So the reader takes the *checked* radio in that column. (`offered.py` reads a
`<select id="sOfferPosition">`; this is a different control and cannot be
copied straight across.)

**Columns, as the header spells them:** Time · First Name · Last Name · Phone ·
Cell Phone · Email · Rating · Booked By · First By Phone · Job Board ·
**Show Up** · Done By · Remove · Follow Up Status · Follow Up By · Follow Up
Time. Found by header text, never position.

**Email is present on every row** on this page, which settles the earlier
question: Blue Ink matching can be by email (proof) rather than name
(judgement) — `matched_on`.

**The office guard is on the page**: a header block reading
`Office ID: 11280   Owner: Rafael Hidalgo`. Note this is NOT the account number
in the title bar (`Account No: 23981`, the call centre) — `offered.py` already
reads the Office ID one.

**A week is six reads, one per date.** The calendar is per-day, so Mon–Sat each
get a `cd=` fetch and the results are pooled — Megan, 2026-11-06: *"it would
only be sent to those marked showed up on that week"*.

**Pooling means de-duplicating by email.** Somebody rescheduled inside the week
appears on two days — No on Monday, Yes on Wednesday — and a double entry would
mean a second payroll record for a real person. One row per email, and a `Yes`
on any day of the week wins. The same guard that already checks All Employees
before creating anybody is the second line of defence, not the first.

**Follow Up Status is not a second condition.** The rows also carry one
(Cancelled / Confirmed / Booked Today - Confirmed / Called), and it is tempting
to read `Cancelled` as "did not start". Megan, 2026-11-06: *"it's just if they
are scheduled to start"* — it describes the **appointment**, not the outcome.
Show Up is the outcome.

So the rule is exactly one column: **Show Up = Yes**. Nothing else is consulted,
and a reader that starts filtering on Follow Up Status is wrong.

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

### DECIDED, 2026-11-06: the machine may hold it (option A)

Megan: *"the ICDs relay machine can hold a social"* … *"the way the current
automation works is that user is able to preview the tax doc with the social to
copy and paste it"* … *"so it can just disappear from that if they can just
access it to fill it in that time."*

Her reasoning is sound and worth writing down, because it is the thing that
makes this a smaller change than it first looks: **the operator already
previews the signed tax document and copies the number out of it by hand.** The
number is already on a screen and already in a clipboard. What changes is that
a machine does the copying — and a machine does not screenshot it, leave it in
a clipboard, or read it out loud on a Zoom.

**Built, 2026-11-06.** `blueink_data.py`:

- **Opt-in only.** `extract(..., keep_ssn=True)` / `for_people(..., keep_ssn=True)`.
  No caller gets a Social without asking; every existing call site is unchanged
  and still comes away with nothing but `has_ssn = True`.
- **Wrapped, not a string.** It arrives as the existing `Secret` from
  `ssn_prompt`, whose `str`, `repr`, f-string and dict-repr are all dots. The
  one place the real value is reachable is `.reveal()`.
- **Not in `values`.** Kept out of the field map rather than filtered out of
  each consumer, so `fillable()`, the setup payload, the batch file, the Hub
  log and (later) the relay row are all structurally unable to carry one.
- **`json.dumps` refuses it.** A `Secret` is not serialisable, so anything that
  tries to write a Social into a payload, a file or the relay **fails loudly**
  rather than succeeding quietly. This is the strongest guarantee in the set.
- **Held for the run, never written down.** Memory only, exactly as Megan
  described.

`test_ssn_custody.py` pins all of it — nine tests, including that the default
is still "drop it on the floor".

**Still to do on the machine side:** the Chrome profile (form autofill and
anything Apex caches in it), and a documented hole in `apex.py`'s `NEVER_TYPE`
list for the one call site that is allowed to type it.

## Work items

| # | Where | What | Size |
|---|---|---|---|
| ✅ | `automations/apex_new_starts/blueink_data.py` | the opt-in Social: `keep_ssn`, a `Secret`, out of `values`. **Done 2026-11-06**, `test_ssn_custody.py` | done |
| 1 | `automations/office_admin/fdot.py` (new) | FDOT/BOB calendar → Showed Up, for a week, per account. Sibling of `offered.py`; **fails loudly** on an unrecognised page rather than returning an empty list | medium |
| 2 | `automations/apex_new_starts/roster.py` (new) | a second roster source behind the existing interface, so Raf's board + OBCL path is untouched | small |
| 3 | `automations/icd_alerts/apex_signin.py` | let the kept session be used for writing, not only the PNL's read | small, but a **policy change** — say it out loud |
| 4 | `automations/apex_new_starts/eco_run.py` (new) | the whole fill from the ECO machine: create, all three pages, save. Takes the Social from `for_people(keep_ssn=True)` and `.reveal()`s it at the one call site | medium |
| 5 | `automations/apex_new_starts/apex.py` | one documented hole in `NEVER_TYPE` for that call site. It exists to stop exactly this, so the exception has to be explicit and narrow | small |
| 6 | ECO machine hardening | the Chrome profile: form autofill off, and whatever Apex itself caches in it. This is the leak path the Python guarantees do **not** cover | small, **do not skip** |
| 7 | `resources/icd-alerts-relay.gs` | an `apex_week` job kind; one row per person (~1.2 KB measured) rather than a week in one cell. **No Social ever goes in it** — `json.dumps` now refuses | ~150 lines, **needs an Apps Script redeploy** |
| 8 | `extension/apex-new-starts/` | relay half (`background.js`/`config.js` near-verbatim from office-admin), sign-in, and "run it for these people" — a pick-list and a progress clock, no filling | medium |
| 9 | ECO machine setup | that office's own Blue Ink key; Apex signed in once by the owner | 15 min |
| 10 | tests | the FDOT reader against a real saved calendar; the relay round trip; the no-Social pins extended to the relay row and the ECO run's logs | medium |

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

**Answered, same day:** *"Apex and blue ink are both 1 per office."* So offices
do not collide with each other — only the admin and the ICD machine inside one
office share an account, and option B's sequential handoff is the only ordering
that matters.

It also means **Blue Ink is a per-office key**, not one shared one. That is
better than it sounds: each office's machine only ever holds its own people's
paperwork. And it needs no code change — `config.CREDS_PATH` is a single
repo-root path, and each ECO machine serves exactly one office, so the office's
own key simply lives on the office's own machine.

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
