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

## State model — from Carlos's Loom (watched frame-by-frame 2026-07-27)

**All state is inline text/tables on the OAT page (p=604) — no modal to catch.**

### The duplicate table (the key state source)
When the applicant matches prior records, the page shows a table titled
**"Following Applicants found with the same email address or phone number"** with
columns: Owner · Office · Applicant · Email · Phone · Cell · Job Board ·
**Date Entered** · **Status** · **Duplicate Type** (Email / Phone). Example Status
values seen:
- `Interview Assigned (View Last Activity) (1st Interview - Unmarked Show)` →
  **past interview, no-show**. (A future interview shows the scheduled date instead
  — Carlos: "scheduled for the 27th".)
- `Sent to Call List` with **Date Entered = today** → the "already sent to the call
  list today via another ad" case → remove for duplicate.
So `has_interview` / `interview_date` / `sent_to_call_list_today` all come from
parsing this table's Status + Date Entered per row.

### Red inline messages (the AI-correspondence block)
- `Cannot send to AI as correspondence with this phone number has already occurred.
  The last correspondence was on <MM/DD/YYYY h:mm AM/PM>` → past correspondence;
  parse that date for the 1-week re-text rule.
- `Cannot override this applicant.` → the AI-send override is blocked (→ re-text or
  remove path, not override+send).

### The overwrite buttons (the overridable-duplicate case)
When the dup CAN be overridden, the page shows a pink box "To Save this Applicant,
the applicants shown above will have to be removed as duplicates." + two buttons:
**"Overwrite old Applicants"** and **"Overwrite Old Applicants (Send to AI)"**. The
second = override + send to AI (classify OVERRIDE_SEND_AI).

### Advance mechanism
The OAT queue is **paginated** — a pager top-right of the dup area reads
`<page> of <N> Emails` (e.g. "2 of 24 Emails") with prev/next arrows. Advancing =
clicking the next arrow (or setting the page select). So `advance_to_next` drives
that pager; the run ends at page N.

### Re-text (RETEXT_THEN_REMOVE) is a cross-page flow
Not done on p=604. Carlos: copy the applicant's email → **Advanced Search** → paste
→ open the prior record → **Send SMS** modal (Chat History + a message box that
pre-fills the last await message; **Load Template** to swap to the position they
applied to) → **Send** → back to OAT → remove for duplicate. The await copy lives
in that SMS modal / templates, NOT a local file. (Most intricate branch — wire last.)

## Status — RESOLVED from the Loom (2026-07-27)
The 5 previously-unobserved bits are now understood (see the State model above):
overwrite handling (inline buttons, not a modal), Interview-Assigned status (dup
table Status column), sent-today (dup table Date Entered), advance (pager), and the
await source (Send SMS modal / Load Template). Remaining work is code, not
observation:
- **Read layer** — parse the dup table + red messages + overwrite-button presence +
  pager into the Applicant state flags; validate on Lucy 2 with `--debug` before
  trusting it. Selectors are TEXT-based (find the table whose header has
  "Status"+"Duplicate Type"; search page text for the red-message patterns), since
  we have pixels not DOM — robust to exact ids.
- **Actions** — still gated until a supervised dry-run confirms the read layer
  classifies real applicants correctly, then arm one branch at a time
  (remove-duplicate first, then override+send, then the cross-page re-text last).
