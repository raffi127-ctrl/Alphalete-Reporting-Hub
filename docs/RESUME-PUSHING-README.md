# Resume Pushing — How It Works

*Written 10/8/2026. Plain-language guide to Lucy's resume-pushing automation.
The deep technical doc is `~/recruiting-report/PUSHING-OPERATIONS-README.md`
(auto-updated nightly on the mini). This one is the human version.*

---

## What it does

Lucy opens ApplicantStream's **One App at a Time** queue (the "scooper"), and
for each applicant: reads the resume, grabs the phone number, fills it in, and
clicks **Send to AI** so the applicant lands on the call list and gets the
Await text. Same thing a person does, one applicant at a time.

## Who gets pushed

Hard-coded allowlist — Lucy physically cannot push any office not on it:

| Office | ID | Machine |
|---|---|---|
| Carlos | 11580 | Lucy 2 |
| Atef | 23467 | Lucy 2 |
| Khalil | 11901 | Lucy 2 |
| Raf main | 11280 | Lucy 4 |
| Raf 2nd funnel | 23965 | Lucy 4 |
| Raf 3rd (24065) | 24065 | Lucy 4 |

Carlos's laptop can also hand-run any of these (it holds the same Lucy login).
Every machine checks the **Office ID banner before every single click** — a
mismatch stops the run cold.

## When it runs

- **7am–10pm Central, every day**, each mini cycling its offices every ~10 min.
- **Weekend quiet window: OFF Friday 1pm → Sunday 1pm.** Nothing pushes Saturday.
- Each office takes its turn (rotation) so no office hogs the machine; each
  turn caps at ~60 people / 15 minutes. Hand-runs on the laptop can run longer.

## How a resume gets read (in order)

1. **Download the attachment** from the applicant's panel — fastest, never
   blocked. (Khalil's applicants usually have these.)
2. **Open the Indeed viewer** — real click on "View resume," new tab, read the
   number off the page. If Indeed shows "unable to display this resume," Lucy
   clicks the download link immediately instead of waiting.
3. **Read the screen** — if the resume renders as an image, Lucy screenshots it
   and reads the number with AI vision, like a human eyeballing it.

Only **Indeed** applicants are worked: the Job Board filter is set to Indeed on
the queue, and anything else (Glassdoor quick-reads etc.) is skipped on sight.

## The rules (standing orders from Carlos)

- **Nobody is ever removed for "no contact info."** No number = flag and leave
  them in the queue. Removals only happen for real duplicates.
- Texting from pushes: only where explicitly enabled (Carlos's office).
- Passwords come from Carlos/Megan only. Lucy's login (`lucyresume`) is stored
  on each machine's own protected config.

## The one thing that needs a human: the "Verify you are human" box

Indeed periodically challenges each machine's browser with a checkbox. **Lucy
will not click it — ever.** When a machine is walled:

- Pushes for that office drop to zero and the queue grows.
- Lucy posts a screenshot pair to the **Carlos/Megan/Eve group chat** showing
  exactly what she sees.
- **Fix: a human clicks the box on that machine's Chrome window once.** Clears
  it for a long while; Lucy resumes on her own.
- Each office has its own browser profile, so one office can be walled while
  another on the same machine pushes fine.

## How you know what's happening

- **Push report** in the Carlos/Megan/Eve/Lucy Slack chat at **1pm and 8pm**:
  per office, "N pushed · M left," with a red ❌ on any office with 10+ waiting.
- First dead-end of the day per office auto-sends the screenshot pair.
- Applicants flagged "no number" get re-checked automatically (misses are often
  just a half-loaded page; a second read usually finds the number).

## Common sights, decoded

| You see | It means |
|---|---|
| "X pushed · 2 left" | Normal — the 2 are no-number flags or fresh arrivals |
| 0 pushed, queue growing, ❌ | That machine's browser is walled → needs the click |
| "no_button" in a log | Number found and SAVED, but the panel has no Send-to-AI button — needs a manual text |
| Big queue number on screen vs few worked | The on-screen count includes non-Indeed applicants Lucy skips by design |
| "paused" on a report line | That office was turned off on purpose (allowlist/rotation) |

## Turning offices on/off

Tell Lucy (Claude) in a session. Under the hood it's two edits that must move
together: `PUSH_ALLOWED` in `automations/applicant_push/run.py` and
`ROTATION_BY_MACHINE` in `automations/applicant_push/offices.py`, deployed via
git push + a queue `update` on both minis.

## Hand-running on the laptop

Ask Lucy to "push for <office> on this device." The laptop signs in by itself,
runs with a long clock (no 15-min cutoff), and Carlos clicks the verify box if
it appears. You can also start at a specific applicant number ("start from 82")
— Lucy uses the pager dropdown on the page.

**Two offices on the laptop at once (learned 10/8):** starting a second
office's hand-run used to kill the first one's Chrome (the "idle browser"
cleanup didn't know a walk was inside it). Fixed on the laptop 10/8 so a
running push is never reaped; until that fix is deployed to the minis, run
one office at a time there.
