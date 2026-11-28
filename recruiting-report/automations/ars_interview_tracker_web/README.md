# ARS Interview Tracker — web app (Google Apps Script)

Per-interview tracker for Camila's interviewer team, one office per tab of the
old ARS REPORT Excel. Runs as a Google Apps Script web app bound to a Google
Sheet; the team signs in with a username and password created in the app.

Tabs: Data Entry · Qualified Retention · Answered / Booked · 2nd Rd Showed ·
Offered / BOB · Conversion Numbers · Interviewers Retention · Ad Titles ·
Ads × Stars · Users (Admins).

**Interviewers Retention** (Raf, 2026-11-20) is the daily 6 PM email's four
tables, read-only. A Lucy writes them as JSON into the sheet's
`Retention Report` tab (`automations/interviewers_retention/web_export.py`,
run with `--web-sheet`); `getRetention` in Code.gs reads it. A **Show** menu
switches between *Use our service* (the offices Camila's team interviews for,
same numbers as the email) and *Our org (all offices)* (every office on the
Hub's office lists, offices from AppStream). Nobody edits that tab by hand.

## Files

| File | What it is |
|---|---|
| `Code.gs` | Server side. Paste into the Apps Script project's `Code.gs`. |
| `Index.html` | The page, **built** — paste into the project's HTML file named `Index`. Don't edit it by hand. |
| `src/app.js` | Readable page code. Edit this. |
| `src/shell.html` | Page markup + CSS, with an `@@CODE@@` placeholder for the packed app code. |
| `build.py` | `python build.py v12` rebuilds `Index.html` from `src/` (the label shows under the title while loading, so you can tell which version a URL serves). |

`Index.html` packs the app code as base64 behind a one-line loader on purpose:
Apps Script's HtmlService strips what it takes for comments inside inline
scripts and breaks real code doing it, and the Apps Script editor rewrites some
non-ASCII characters on paste. See the docstring in `build.py`.

No interview data lives in this folder (the repo is public). Data is in the
Google Sheet.

## The Google Sheet

`Code.gs` creates these tabs on first use:

- `Interviews` — one row per interview: id, office, Date 1st Rd, 1st Round
  Interviewer, Full Name, Qualify, Reasons, Answer Call, Booked to 2nd Rd,
  Date 2nd Rd, Showed Up to 2nd Round, Offered Position, BOB, Ad Title,
  Star Rating, updated, updated_by. Dates are stored as `yyyy-mm-dd` text.
- `Offices` — id, name.
- `Interviewers` — the 1st Round Interviewer dropdown list.
- `AdGroups` — key, label (the Excel's Ad Groups table, used to merge ad titles).
- `Retention Report` — written by the Interviewers Retention run, not by this
  app: column A holds one JSON document split over rows.
- `Users` — username, name, role (`admin` / `interviewer`), active, salt, hash,
  lastLogin. Passwords are never stored, only a salted SHA-256 hash.

## Deploy / update

1. Google Sheet → Extensions → Apps Script.
2. Replace `Code.gs` with `Code.gs`, and the `Index` HTML file with `Index.html`. Save.
3. Test on the `/dev` URL (Deploy → Test deployments). The version label shows
   under the title while loading. First run asks to create the first Admin.
4. Deploy → Manage deployments → edit:
   - Execute as: **Me**
   - Who has access: **Anyone** (or "Anyone with Google account" if Anyone isn't offered)
   - Version: **New version** → Deploy. Only then does the `/exec` URL change.

Share the `/exec` link **without** `/u/1/` in it. Someone signed in to several
Google accounts gets "No se puede abrir el archivo" from a `/u/N/` link; an
incognito window or the plain link fixes it.

## Roles and security

- Nobody sees data without signing in; every server function except `login`,
  `needsSetup` and `setupAdmin` takes the session token and checks it.
- Interviewer: all offices and reports, enter and edit interviews.
- Admin: also Users (create, role, reset password, disable, delete), + Office,
  Manage offices (delete), Import Excel, Interviewer list.
- Sessions: CacheService, 6 h of inactivity. Disabling a user or resetting
  their password ends their sessions.
- 5 wrong passwords lock that username for 10 minutes.
- There is always at least one active Admin; an Admin can't demote, disable or
  delete themselves.
- Helper functions end in `_` so `google.script.run` can't call them.

## Retention colour rules

- Qualified Retention (QR): ≥ 60% green, below red.
- Answered / Booked (AR, BR): ≥ 85% green, 80–84% grey, < 80% red.
- 2nd Rd Showed, Offered / BOB, Conversion: the Retention goal selector (default 50%).

## Working on it

Changes are tried first in the Claude artifact prototype, then ported here:
edit `src/app.js` (and `Code.gs` for server changes), run `python build.py vN`,
paste both files into Apps Script, check `/dev`, then deploy a new version.
