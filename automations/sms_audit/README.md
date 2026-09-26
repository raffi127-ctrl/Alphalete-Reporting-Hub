# SMS audit — what our texts to applicants actually look like

Raf asked on 2026-09-26 (#l10-alphalete, Raf → Megan/Eve/Carlos): *"Can we
teach LUCY to go through all the text messages I have… understand when AI is
doing the booking, how quick are our human recruiters responding, what are
common questions from applicants, what are our regular responses, are their
text messages unanswered, does the AI notice anything off?"* Carlos asked for
his office too, with a comparison of the two.

Two steps.

## 1. Pull the threads (Lucy 2 — it holds the live AppStream session)

```
lucy rerun sms_thread_dump --office 11280,11580 --dates "09-23-2026,09-24-2026,09-25-2026" --machine "Lucy 2"
```

`automations/sms_thread_dump` walks the Weekly Calendar (p=105) for each date,
opens every booking's **Applicant History → SMS Sent → Chat History**, and
parks the raw thread in the control sheet, one tab per office
(`SMS Dump 11280`, `SMS Dump 11580`) plus `output/sms_thread_dump_<office>.json`
on the machine that ran it. Read-only on AppStream. ~3s per applicant, so a
3-day window for one office is 10–20 minutes.

`--days N` takes the N most recent non-Sunday days instead of naming dates.
Offices in one run share the window, which is what makes the comparison fair.

## 2. Read them

```
python -m automations.sms_audit.analyze --office 11280,11580
```

Writes `output/sms-audit-<date>.md`: one section per office answering Raf's six
questions in order, then a side-by-side table. Reads the local JSON if it is
there, else the sheet tab, so it runs on the laptop with no AppStream login.

## What the source can and cannot tell us

**It can.** Who booked (`Booked By` = `A. Messaging` for the automation, a
recruiter's name otherwise — corroborated by which Directions template fired),
every message with its template name and timestamp, the applicant's side, and
the booking's outcome.

**It cannot.** *Who typed a free-typed message.* The Chat History has no sender
column, so "median 1 minute" mixes the conversational AI with a recruiter at a
keyboard. §2 splits by who booked the interview and says so. The real per-message
sender is the **`Sent By` column on the SMS List Report (p=336)** — which also
carries `Source`, `Status` (delivered/error) and **every applicant, not just the
ones who booked**, over an arbitrary date range, with an Export to CSV button.
That page is the better source for a second pass; nothing reads it yet.

**Coverage.** This walk only sees applicants who *booked a first interview*.
Anyone who was texted and never booked — the population most likely to have been
left on read — is invisible here. Read §5's "unanswered" as a floor, not a total.

## The persona trap

The name inside a message is not the sender. "Elena" fronts 185 of 185 threads
in Carlos's office, AI-booked and recruiter-booked alike, and three more names
(Tatiana, Val, Valery) appear alongside her. Nobody should read a name in a
thread and conclude a person typed it.
