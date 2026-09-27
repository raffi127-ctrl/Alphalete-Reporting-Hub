# SMS audit — what our texts to applicants actually look like

Raf asked on 2026-09-26 (#l10-alphalete → Megan/Eve/Carlos): *"Can we teach
LUCY to go through all the text messages I have… understand when AI is doing
the booking, how quick are our human recruiters responding, what are common
questions from applicants, what are our regular responses, are their text
messages unanswered, does the AI notice anything off?"* Carlos asked for his
office beside it. Raf has **three** accounts: 11280, 23965, 24065.

## The two sources, and why it takes both

| | reads | gives | misses |
| --- | --- | --- | --- |
| `sms_audit.pull_log` | **SMS List Report, p=336** | every message in and out for a date range, with **Sent By** (AI Messaging vs a named recruiter) and delivery **Status** | never says whether anyone got booked |
| `sms_thread_dump --bookings-only` | Weekly Calendar, p=105 | who booked, by whom, their phone, whether they showed | only sees applicants who booked |

`analyze` joins them **on phone number** (normalised — the calendar writes
`14698762121`, the log writes `+14698762121`; a missed join reads as "never
booked", which is invisible). That join is what turns the audit from
*"of the people who booked…"* into a funnel: **texted → replied → booked →
showed**, plus everyone who was texted and never booked.

## Running it

```
lucy rerun sms_thread_dump --office "11280,23965,24065,11580" --bookings-only --machine "Lucy 2"
lucy rerun sms_log         --office "11280,23965,24065,11580" --machine "Lucy 2"
python -m automations.sms_audit.analyze      --office 11280,23965,24065,11580
python -m automations.sms_audit.weekly_sheet --office 11280,23965,24065,11580
```

Both pulls default to the **last complete recruiting week, Saturday→Friday**
(Megan 2026-09-26) and are READ-ONLY on AppStream. `--week 2` steps back a
week. Quote any comma list going through the queue.

Drop `--bookings-only` to also capture each booking's chat history — but that
opens a dialog per applicant at ~3s each, and Raf's office books ~830 a week,
which is how the first attempt hit a 45-minute timeout having written nothing.
With the p=336 log in hand there is no reason to pay that.

## Where it lands

* `SMS Log <office>` and `SMS Dump <office>` — control sheet, one tab each per
  account. They used to share a single tab, so pulling a second office wiped
  the first and the comparison could never hold both halves.
* `output/sms_log_<office>.json`, `output/sms_thread_dump_<office>.json` on the
  machine that ran it. `--suffix` reads a kept-aside pull, which is how an
  older week is backfilled after a newer one replaced the live file.
* `output/sms-audit-<date>.md` — the write-up.
* **Applicant Correspondence Audit (ACA)** — the standing sheet, one tab per
  account, one column per week. Id recorded in `workbook.json`.

## Things that will bite

**The form has four date fields.** `startDate`/`endDate` are the visible boxes
in `MM-DD-YYYY`; `startDate2`/`endDate2` are hidden, in `MM/DD/YYYY`, written
by the datepicker — and the server reads the hidden pair. Setting only the
visible boxes leaves it on today, and Search returns today's rows while the
boxes on screen show the week you asked for. `_confirm_range` refuses anything
whose grid header does not match what was asked, and `_scrape_grid` warns when
the row count comes in under the page's own total.

**Injected JavaScript must be a raw Python string.** `[^\n]` in a normal
literal reaches the page as a real newline inside a regex character class —
a syntax error that kills the whole evaluate. `\\d` reaches it as an escaped
backslash and silently matches nothing. `test_pull_log` AST-walks the module
and fails on either, because finding them in the browser costs a full queue
round trip.

**A week column can be a partial week.** The window guard checks the data
falls inside the named week; it cannot know what a full week should be for a
given office. Every column states its own coverage ("3 days · 9/2 – 9/4") —
read it before comparing two columns.

**Blank is not zero.** A `--bookings-only` walk has no messages, so questions
and flags are not 0, they are unmeasured. The sheet writes blank.

**The persona is not the sender.** "Elena" fronts every thread in Carlos's
office, AI-booked and recruiter-booked alike, with Tatiana / Val / Valery /
Sandy mixed in. Who sent a message is `Sent By` on the log, or — for a booking
— `Booked By` (`A. Messaging` is the automation), corroborated by which
Directions template fired. Never the name in the body.

## Channels

Each ICD has their own recruiting channel; the map is
`automations/applicant_push/offices.py` (`post_channel`), reused rather than
copied. Raf's three accounts all point at `C0AUAS88FGW`
(#rafs-office-recruiting-11280). **Only Raf, Khalil and Atef have their own**
— Carlos, Jamis, Rashad, Haytham, Cyrus and Cody currently share
`C09L1S3MQ1E`, which is the push module's fallback rather than each ICD's own
channel. Per-ICD routing needs those real channel ids added to that table.

Nothing here posts to Slack.

## What the weekly sheet holds

**Applicant Correspondence Audit (ACA)** — one tab per account, one column
per Sat-Fri week, headed `WE 9/25`. Sections, in order: This week (with the
days the column actually covers) · Who we texted · Why texts never arrive ⊞ ·
1st Rounds · Why they didn't book ⊞ (with Our texts never reached them ⊞
nested) · Cold list · Not the cold list · Texts it takes to book · Did they
show up? · When we text · How fast we reply · People we left hanging · What
applicants ask · Text quality ⊞ · Questions handled badly ⊞ · Problems to fix.

⊞ is a collapsible group, closed by default.

## Things that will bite

**The form has four date fields.** p=336's `startDate`/`endDate` are the
visible boxes in `MM-DD-YYYY`; `startDate2`/`endDate2` are hidden, in
`MM/DD/YYYY`, and the server reads the hidden pair. p=704 has the same trap
(`activityDate` / `activityDate2`). Setting only the visible one leaves the
report on today while the boxes on screen show the week you asked for.

**Injected JavaScript must be a raw Python string.** `[^\n]` in a normal
literal reaches the page as a real newline inside a regex character class —
a syntax error that kills the whole evaluate. `test_pull_log` AST-walks the
module and fails on it.

**A week column can be a partial week**, and a booking can be carried in from
the week before. Both are stated on the tab rather than averaged away: a
thread whose first in-window message IS the booking marker was booked before
the window opened and is excluded from "texts it takes to book".

**Blank is not zero.** A `--bookings-only` walk has no messages, so questions
and flags are unmeasured, not absent.

**Adding a row does not reorder an existing tab** — a missing label is
inserted at its place in the layout, and the pending writes are shifted to
match. Rows are found BY LABEL, so no two rows may share one; a rename goes
in `RENAMED`, pointing at the final name, never at another rename.

**A nested group is depth 2.** The API rejects a depth-1 update on it and
fails the whole batch, losing every group on the sheet. And an `updateCells`
write inside a collapsed group clears the fold, so it is re-applied after
painting.

**The system word list is a 1934 BASE-FORM dictionary.** It has no "paid",
"using", "planning", "callback", "download" or "coordinate". It is a VETO
only — a word it contains is never a typo — and every correction comes from
the office's own vocabulary. Searching it for near neighbours produced
"using → suing" and "paid → pail".

**The dodged-question check is a heuristic.** It treats a question as
answered when the reply names a job title, gives a time to a "when" question,
says a short direct yes (unless the question is a real "A or B?"), or
mentions anything any part of the question was about, hyphens and spacing
ignored. Read that section as a shortlist to eyeball, not a verdict.

**The Activity Report (p=704) is a booking log, not a call log.** Its
Activity column holds only "First Interview Date" and "Second Interview
Date". p=1520 Phone Burner returns nothing even when submitted, and p=1530
"AI Live Calls" is broken server-side. So there is no call-answer-rate by
hour available from AppStream reporting — do not go looking again without
new information.

## Checking that the numbers come from where they claim

Megan, 2026-09-27: *"double check that the mapping of how you're pulling all
these numbers is correct."* Two commands answer that, and they answer
different halves of it.

```
python -m automations.sms_audit.verify              # internal, no network
python -m automations.sms_audit.verify --map        # the row-by-row source map
lucy rerun sms_crosscheck --machine "Lucy 2"        # against AppStream itself
```

**`verify.py` is the internal proof.** It asserts the identities that have to
hold if the mapping is right — booked = AI + recruiter, contacted = booked +
not booked, the drop-off buckets = everyone unbooked, cold + live = contacted,
delivered + undelivered = everything sent — and then re-derives a sample of
the figures straight from the raw scraped rows instead of from the audit's own
structures, so a field read out of the wrong column disagrees with itself
instead of agreeing. It also holds every row on the sheet to a `LINEAGE`
entry naming its page, its column and its rule; **a new row with no entry
fails the run**, which is what stops the map going stale. Exit 1 on any
failure, writes nothing.

**`crosscheck.py` is the outside proof, and it is the only one that matters
for a whole-pipeline error.** Everything above still balances if the calendar
walk quietly missed a day. The Retention Report (p=701) counts first
interviews off AppStream's own table, with no reference to the calendar or
the SMS log, so it is an independent second opinion. It needs Lucy 2's warm
session. Watch the week boundary: **p=701 is locked to Sun-Sat and recruiting
runs Sat-Fri**, so one recruiting week is the Saturday of one p=701 week plus
the Sunday-to-Friday of the next — two pulls, and an off-by-one there reads
as a mismatch blamed on the pull.

**The window guard covers BOTH halves.** `check_window` used to read only the
booking walk's dates, so a right-week bookings file paired with a wrong-week
log passed silently — each half internally fine, the column quietly mixing
two weeks. That is how WE 9/4 once took its reply speeds and questions from
WE 9/25, and it was caught by eye, not by code. `build_report` now stamps the
log's own span onto the report as `log_window`, and both feed `data_window`.
