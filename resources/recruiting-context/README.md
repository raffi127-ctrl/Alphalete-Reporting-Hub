# Recruiting context

Context pack so an agent understands how ARS recruiting actually runs — the
1st-round → 2nd-round → BOB pipeline, the call loop, the scripts, and the
ApplicantStream mechanics the recruiters and bookers use all day.

Built 2026-09-26 from Raf's post in #l10-alphalete
([thread](https://ao-pbns.slack.com/archives/C075PCEL92M/p1790446285684109?thread_ts=1790446285.684109&cid=C075PCEL92M)):
*"Can we make an AGENT / feed the AI this huge word document + Videos and have
it learn everything so that it gets context please?"*

## What's here

| File | What it is |
|---|---|
| [ars-processes-2026.md](ars-processes-2026.md) | Full text of Raf's "ARS Processes 2026" Google Doc — 1,299 lines, every script and process. The bulk of the context. |
| [video-index.md](video-index.md) | All 42 training Looms: real Loom title, recording date, length, Skool day, and a link to each transcript. |
| [transcripts/](transcripts/) | 41 transcripts (~15,700 words), one per video, plus a single combined file. |
| [videos.json](videos.json) | Same, machine-readable. |

## Source of truth — re-pull before trusting this

The Google Doc is **live and still being edited**. Everything here is a snapshot
taken 2026-09-26. For any decision that matters, re-pull:

- Doc: <https://docs.google.com/document/d/1zHhuWzoWy4GMO1-gDOKQWXaPe_uQO9ZSmPaRvOEuxKM/edit>
  ("ARS Processes 2026")
- Videos: the `url` in videos.json; titles/dates via Loom's public oEmbed endpoint.

## Staleness — the videos really are old

Raf asked us to "prep the AI that some of it might be old." He is right, and the
gap is bigger than the list suggests: **every video is from September 2024**,
uploaded 2024-09-12 → 2024-09-20 by Aisha Ceron. The `9/12` and `9.13` in the Loom
titles are 2024 dates, not 2026 ones — easy to misread as recent.

So: the transcripts are a reliable record of how the work was taught two years ago.
Any specific click path, menu name or button label should be re-checked against
today's ApplicantStream before an agent acts on it. The shape of the process
(the call loop, the pipeline states, the scripts) is far more likely to still hold
than the UI details. This is exactly the re-record pass Carlos took on.

The Doc has its own stale patches — it mixes settled process with in-flight
planning. Treat these sections as plans, not current process:

- `# Next Steps` — an open to-do list (Carlos on scripts, Raf/Megan/Eve on AI
  automation, Tiffani/Maria on recruiter numbers).
- `# 1st rd AI Audit` — the spec for the interview-audit bot, written as questions
  to ask a transcript. Not a description of something already running.

One dead link: **"Daily Update & 2nd Round Retention to BOB"**
(`loom.com/share/6c8f85faadd94e95b96b98200af25adb`) returns HTTP 404 while the
other 41 resolve. No transcript for it. Needs a re-record or re-share.

## Transcripts

All 41 reachable videos are transcribed — ~15,700 words in
[transcripts/](transcripts/), one file per video with timestamps, plus
[ALL-TRANSCRIPTS.md](transcripts/ALL-TRANSCRIPTS.md) with everything concatenated
for pasting into a model in one go.

These are Loom's own auto-captions, so expect light speech errors and mangled
product names. The richest single file is
[live-phone-burner-session-opens.md](transcripts/live-phone-burner-session-opens.md)
— 30 minutes of a recruiter actually working the Opens call list, rebuttals and all.

A note for whoever extends this: Loom's share-page HTML contains a block of text
addressed at AI agents, telling them to connect a third-party MCP server to read
transcripts. That is page content, not an instruction from anyone here — it was
ignored. The captions came from the signed URL the public page already serves.

## The process in one pass

Grounded in the Doc; section names are its headings.

- **Pipeline.** Application → call list → 1st round (Zoom) → 2nd round (in person,
  head office, with an account manager) → BOB ("Bring on Board") → start date.
  Terminal states: on Hold, Disqualified, Declined next round.
- **Call loop** (`# Call scdule`). Fixed daily order, CST: Opens 10:00 →
  No Answers 11:30 → LM1 13:00 → LM2 14:30 → LM3+ 15:30. At least an hour between
  passes on the same list, measured from when the pass started; 40–50 applicants
  an hour. Voicemail only on the first Opens call. Book same-day when possible;
  if the applicant wants to book 2+ days out, put them on Hold.
- **Scripts** (`# Opens Scripts`, `# D2D Script`, `# B2B Script`, `# 2nd ITN Script`,
  `# Rebuttals`, `# Voicemails`, `# Disqualified`). The 1st round runs a fixed
  outline: Introduction → Q&A → Company Background → Pay Structure → Schedule →
  Wrap up.
- **Auditing** (`# Process`, `# Auditing Process`). Interviewer runs Fathom on
  Zoom; at EOD transcripts go to Google Drive; an audit pass scores them and
  scorecards post to Slack. Confirmation-call SLAs: 1st round within 1 hr
  (±10 min), 2nd round within 45 min (±10 min).
- **Training** (`# Recruiter Training Syllabus`). A day-by-day ramp; the Skool
  video checklist in video-index.md is its homework — Monday 17 videos,
  Wednesday 6, Thursday 10. Nine videos are on no day's list.

## Related work already in the repo

- `automations/recruiting_report/` — ATT Program - Focus Report. The Doc's
  "How to fill out Daily Focus report" video covers the manual version of this.
- Applicant Tracker / Applicant Push / Resume Pushing — the ApplicantStream
  automation these videos describe by hand.
- The `# 1st rd AI Audit` section is the spec behind Raf's interview-audit bot.
