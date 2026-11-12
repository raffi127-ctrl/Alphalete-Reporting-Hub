# Applicant replies — Lucy answering applicants in AppStream (SHADOW ONLY)

Megan 2026-10-20: *"we want to explore the idea of our claude/Lucy responding
to applicants in app stream"*, then *"let's build it out but not apply it to
any account yet"*.

**Nothing here sends.** No AppStream login, no text, no Slack post.
`config.ENABLED_OFFICES` is empty, and `test_never_sends` fails if a send
path or one of the sending modules (OAT, applicant_push, Slack) is ever
imported into this package. It reads saved SMS logs and writes what Lucy
**would** have said, next to what actually went out.

## The design: alongside eStream's AI, not over it

AppStream already has its own AI ("A. Messaging") replying and booking.
Lucy only takes the moments it hands off or can't do, so an applicant never
gets two answers:

| Reason | What Lucy does | Why it's hers |
|---|---|---|
| `opt_out` | **nothing**, ever | stop / not interested / withdrawing |
| `spanish` | answers in Spanish | AppStream blocks its AI from Spanish |
| `scam` | approved scam answer | also blocked for the AI |
| `call_me` | approved call line, tells the team | #1 thing applicants text |
| `scheduling` | **nothing**, tells the team | booking needs the calendar, which only the AI and recruiters see |
| `dodged` | the real answer | the AI deflected/ignored a question we have an approved answer for |
| `unanswered` | answers | nobody replied within 30 min |

A recruiter's reply inside the wait always wins: Lucy leaves that thread
alone, whatever the reason.

## The three safety layers

1. **Facts** (`facts.py`) — Lucy knows only what's built in code: the
   office's own row on the *Recruiting Audit Offices* tab (address with move
   history, Zoom, round formats, pay) plus the company-wide approved
   answers. Read from the cached copy, never Sheets. A missing fact is a
   gap, and Lucy hands that question to a person. Raf's pay line is used
   for Raf's accounts only; other offices need `pay_low`/`pay_high`.
2. **Prompt** (`draft.py`) — Megan's rulings 1–8 in plain words, no
   booking, honest if asked "is this a bot", no age/gender wording.
3. **Guard** (`guard.py`) — every draft goes through the SAME checks the
   weekly audit scores people on (imported from `sms_audit`, not copied):
   deflection, timed call promise, "base" pay, block capitals, wrong address
   or Zoom, links, protected-class words, placeholders, over 2 segments.
   A failing draft is **HELD**, with the reason.

## Running it

```
# free — counts per reason, no model calls
python -m automations.applicant_replies.shadow --office 11280 --triage-only

# drafts for a sample spread across the reasons (~$0.05 each, Opus 5.5)
.venv/bin/python -m automations.applicant_replies.shadow --office 11280 --limit 30

# Lucy vs what was sent, on the 122 exchanges from the 9/27 review
.venv/bin/python -m automations.applicant_replies.shadow --bench

python -m unittest automations.applicant_replies.test_applicant_replies
```

Input is `output/sms_log_<office>.json` (or `--log` for a kept-aside week).
Get a fresh one with `lucy rerun sms_log --office "<id>" --machine "Lucy 2"`
(read-only on AppStream). Output: `output/applicant_replies/`.

## Before any account goes live

- **A claim on the thread.** At 15 min, 381 of 692 "unanswered" turns at
  11280 got a human reply inside the hour. The wait is now 30, but live
  needs a real lock so a recruiter and Lucy can't both answer.
- **Speed.** Live means reading p=336 every few minutes, which holds one of
  the two AppStream logins all day.
- **The send itself** would reuse OAT Processing's proven compose-and-send
  in the SMS widget, behind `ENABLED_OFFICES` and a per-run cap.
- **Hub card.** Add one when the first account is switched on.
- **Megan's 122 verdicts.** The bench scores with the audit's rules, not her
  own calls, which live only in the 9/27 chat. Saving them as a file would
  make the bench a true test.
