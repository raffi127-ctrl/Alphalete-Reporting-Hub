# OAT page — DOM findings (Lucy 2 `--debug`, 2026-07-27)

Captured by running `oat_processing.run --debug` remotely on Lucy 2 (office
11580, Carlos) via the mini-control channel, then paging the health check with
`logtail`. End-to-end this **confirmed the whole session path works** on Lucy 2:
holder-warmed AppStream session → applicantstream.com → office switch → OAT page.
No service-account key, no Cloudflare prompt.

## Navigation
- Landing after office switch: `index.cfm?p=104&newOfficeId=11580`
- **One App at a time = `index.cfm?p=604`** (rqst token carried). `open_oat`
  opens the Applicants menu and clicks the link; falls back to direct `p=604` nav.

## Applicant panel fields (read by `name`)
| Field | control | notes |
|-------|---------|-------|
| First name | `input[name=fname]` | |
| Last name | `input[name=lname]` | |
| Phone | `input[name=phone]` | |
| Cell | `input[name=cellPhone]` | blank on the no-phone case (Donald Sowells) |
| Email | `input[name=email]` | Indeed relay address |
| Job Board | `select[name=jBoard]` | Breezy, careerBuilder, Company Website, Facebook, **Indeed**, … |
| (hidden) | `input[name=emailThatWasDupeChecked]` | dupe-check signal — worth probing for state |

## Action controls (confirmed present; click sequences NOT yet armed)
- **Send to AI** — button (bottom of panel).
- **Remove for duplicate** — `input[name=removApp]` checkbox + `select[name=rmvReason]`
  + **Save Applicant** (`submitSaveApplicant`). `rmvReason` options include
  "Different Career Path, Accepted Another Position, AD Receipt, Benefits
  required, Commute Too Far, Declined Via Email/Text, Desk Job Only, …" — the
  **duplicate** entry is past the 12-option capture cap, so select it at runtime
  by matching option text ~ /duplicate/i.
- **Re-text / await** — **Email Applicant** button + `input[name=emailApplicantSubject]`
  + `textarea[name=emailApplicantMessage]` + `input[name=emailApplicantOriginal]`
  (checkbox). Quick-Note picker = `select[name=qNotes]`.
- Rating radios `1..5` (`name=rating`); `Send Email` / `Send SMS` / `AI Eligible`
  checkboxes (from the screenshot).
- Filters on the page: `numDays` (30 Days), `matchedOnly`, `filterByDate`,
  `filterByJboard`.

## STILL UNOBSERVED — needs an applicant in each state (the last-mile blockers)
The applicant that happened to be first in the OAT queue was a plain **no-phone**
case, so these never rendered:
1. **The overwrite/duplicate confirm dialog** that appears when you Send to AI on
   a duplicate ("overwrite old applicant?"). Needed for SEND_AI + OVERRIDE_SEND_AI.
2. **The "Interview Assigned" status line + date** (future vs past interview).
   Needed for REMOVE_FUTURE_INTERVIEW and the past-interview re-text branch.
3. **`sent_to_call_list_today`** signal — how the page shows "already sent today".
4. **How the page advances** to the next applicant after Send/Save (auto-load? a
   Next control? does `p=604` just always show the next unprocessed app?).
5. **The await-template source** for the re-text branch — is it a `qNotes` Quick
   Note, or a saved "await message" the applicant last received?

These are stateful, so they can't be forced by health-checking whatever applicant
is first in queue. Fastest unlocks: Carlos shows a duplicate + an interview-assigned
applicant (screenshot or a short driven session), or a supervised dry-run that
logs the states as they appear across a batch.
