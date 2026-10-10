# Booking-call scorecard — DRAFT rubric for Raf

> **Nothing is built from this yet.** The 1st-round scorecard's items were
> signed off by Rafael in a manual pilot before any of it ran (grade.py: *"The
> scorecard is the one Rafael signed off on in the manual pilot (Sep 22-24)"*).
> This is the same thing one step earlier in the pipeline, and it needs the
> same sign-off. **Items below are a proposal, not a standard.**

Megan 2026-10-09, on the 1st Round Scorecards post: *"this is 1st round
interviews but we will want the same type of edit on the booking phone calls
when we get them."*

## What it grades

The call that books the 1st round — [the quick
pitch](first-round-booking-call.md) — read off Ringover Empower transcripts
once [[project_ringover_call_audit]] clears its 403.

## Why it is worth building

| Booked by | Showed up |
|---|---|
| Text | 47% |
| Phone call | 14% |

The 1st-round audit grades the interview. Nothing yet grades the call that
produces the interview, and that call is where the pipeline leaks hardest.

## Proposed items

Same rule as the interview scorecard: strictly YES / NO, partly done counts as
not done, score = % of applicable items passed, minus half an item per script
portion said in the wrong words.

### Red flags — YES is bad

| key | Question |
|---|---|
| `base_pay` | Did they offer base pay / salary for the entry-level role? |
| `off_script_pay` | Did they quote pay different from this office's range? |
| `retail` | Did they say the job is inside a retail store? |
| `nine_to_five` | Did they say the schedule is 9-5, or Monday-Friday only? |
| `wrong_details` | Did they give an address, Zoom link or time that is not this office's? |
| `no_sooner_slot` | Did they book more than a day out without offering anything sooner? |

The last one is new and is the single most defensible item in the list: show
rate runs **74%** when the slot is under an hour away and **33%** when it is
more than two days out, and 54% of bookings are 12+ hours out.
[[project_applicant_sms_audit]]

### Must-dos — YES is good

| key | Question |
|---|---|
| `identity` | Did they confirm they were speaking to the right person? |
| `permission` | Did they ask for the minute before pitching? |
| `named_role` | Did they say which role and which company? |
| `personalised` | Did they reference something specific from the resume? |
| `two_times` | Did they offer two specific times rather than an open question? |
| `email_back` | Did they read the email address back for confirmation? |
| `what_next` | Did they say what happens next — confirmation text, email, when the Zoom link arrives? |
| `warmth` | Was there audible warmth and enthusiasm throughout? |
| `urgency` | Did they give a reason to take the sooner slot? |

`personalised`, `warmth` and `urgency` are the trained techniques made
gradeable — see [the script file](first-round-booking-call.md) for SEE and
FUGI. Note **eye contact is not gradeable on a phone call**, so SEE reduces to
two of its three parts here; a rubric scoring all three would mark every call
down on something physically impossible.

## Two judgement calls for Raf

1. **`warmth` is the only subjective item.** Every other question has a
   checkable answer in the transcript. Either it stays and the model is told
   plainly what counts, or it comes out and the rubric grades only what was
   said. The interview scorecard kept everything binary and checkable, which
   argues for cutting it.
2. **Does a call that does not book still get graded?** A recruiter who runs
   the script perfectly and gets a no is not the same as one who skipped half
   of it. Suggest grading every call over some length and reporting the
   booking rate separately, rather than only grading the wins.

## What gets reused

Most of it. `automations/first_round_scorecards/` already has the grading loop,
the scoring rule, the verbiage penalty, per-office formats, the name merge and
the Slack post shape Megan pointed at. The booking-call version is a new item
list plus a different transcript source — Ringover instead of Fathom.
