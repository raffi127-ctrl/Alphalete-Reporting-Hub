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
