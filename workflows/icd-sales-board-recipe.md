# ICD Sales Boards — build recipe

Automate the per-office sales board and roll it out as a **service**, so ICDs
stop hand-filling their boards. Raf's ask (2026-08-17, #l10-alphalete):
production numbers, automated, not ugly.

## The three surfaces

There is one pipeline and three ways to look at it. Build them in this order —
each one is the input to the next.

**1. The Sheet (per office).** The durable artifact. One workbook per ICD, a new
tab every week named by the week-ending Sunday, so week-over-week history is
never lost. This is the same shape our own board has, minus the hand-filling.
The owner reads and downloads it; the automation owns every write.

**2. The site.** Renders the Sheet. One **org link** (every rep, every office —
Megan / Eve / Raf) and one **per-owner link** showing only that office's board
plus a recruiting section. Read-only by design, see below.

**3. The daily Slack post.** Into the office's own channel: a screenshot of the
board plus their link. The screenshot is what gets looked at; the link is what
gets clicked.

## Don't design a board — generalize Raf's

**"Alphalete SALES BOARD 2025"**
(`1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc`) already is the template, and it
already has nearly every section asked for. Verified read-only 2026-08-17; it
runs one tab per week today.

**`Sales Board WE m.d`**

| Rows | What |
|---|---|
| r3 header | `# ⏐ <week> ⏐ Total Apps ⏐ INT ⏐ INT UP ⏐ DTV ⏐ NL ⏐ EN ⏐ Cx` (this week, D–J), then the same measures as **last week's totals** (K–P) |
| r4–71 | rep rows |
| r72 | `TOTALS` |
| **r74–85** | **the team breakdown, already built** — "Total Reps in the Field", "Reps that got on the Board", "Reps that rolled a Zero", **"% of Reps on the Board"**, org-wide *and* per campaign (FIBER, ENERGY) |
| **r87+** | **week-over-week history** back to 2024 — the trend/projection source for the top of the site |

**`Line Up WE m.d` — this is the attendance tab.** Header: `# ⏐ Car Ride Leader
#1 ⏐ Car Ride #2…#5 ⏐ New T? ⏐ Done Y/N ⏐ Convo Done ⏐ Zip Code ⏐ City ⏐ Notes
⏐ Expectation of Days ⏐ Green?`. The car-ride groupings **are** the team
assignment. Row 44+ carries the status columns: `FFP ⏐ New Starts ⏐ Roadtrips ⏐
OFF ⏐ O-NA ⏐ Terminated ⏐ Late to matchs up ⏐ STF`.

So "% of reps selling", the per-team breakdown, zero counts, week-over-week, team
assignment and the retire/attendance markers are **existing rows**, not new
design work. The build is generalizing this to per-office and automating the
sales half.

## What owners may edit — and what they may not

Owners need to retire a rep, mark attendance, and set a rep's team. They must not
touch sales numbers. That line is the whole design:

- **Owners edit** roster, attendance, and team (car ride). This is their own
  operational truth — no Tableau pull can know who showed up today.
- **The automation owns** every sales cell, pulled and rewritten each run.

This keeps the anti-glitch property intact, because glitches come from
hand-editing *pulled numbers* — Carlos flags them multiple times a day off small
manual edits, and Eve notes owners "tend to play with sales boards and change
things here and there manually." Roster metadata has no such failure mode.

Practically: attendance and team are **dropdowns on a small number of columns**,
and the sales region is protected. If an owner thinks a sales number is wrong,
that is a source fix, not a cell fix.

## Parse the rep name — do not match on it

Rep names on both tabs carry inline annotations: `(Wk 2)`, `(Wk 3)`, `(NC)`,
`( BO )`. That is three facts in one cell — name, tenure week, status — and it
**will** break matching against Tableau. Split them into real columns
(Rep / Team / Status / Tenure) on the automated board. The ICD alias sheet solves
spelling, not suffixes.

## What to reuse (most of this is already built)

| Need | Use | Notes |
|---|---|---|
| New tab every week | `leaders_call/recognition_tab.py` | Duplicates a template tab → `M.D.YY` at front. **Additive + idempotent**: skips if it exists, never edits/clears/deletes. Exactly the semantics we need. |
| Board screenshot | `captainship_drafts` `sheet_shot`, as wired in `org_sales_board/screenshot_email.py` | Exact-sheet PNGs, sections located by col-A/col-B label, never row numbers. |
| Post as Lucy into the office channel | `slack_metrics_post` + `office_metrics/offices.py` | The channel, owner name, sheet id and cross-workspace token already live per office in that registry. |
| Freeze a week / roll forward | `org_sales_board/rollover.py` | Freeze this-week → prior, re-date headers, zero the new week. Worksheet-scoped writes. |
| Who sells what, and from which view | `icd_sales_board/` (new) | `profiles.load()` gives campaigns + the metrics that apply; `campaigns.py` gives the Tableau path per campaign. |

## Rules this build inherits

- **Never hand-list an office's metrics.** Derive them from what the ICD sells
  (`icd_sales_board.campaigns.applicable_metrics`). A metric that does not apply
  is **absent from the page**, not blank and not greyed — an all-blank board
  reads as broken (Megan 2026-08-04).
- **Stupid simple to look at** (Megan 2026-08-17). Four vitals above the fold,
  one number per concept, plain words. Same bar as the Hub itself.
- **Uniform across offices.** Every office's board goes through the same render.
  ICDs pay for this as a service; a board that looks different reads as
  second-class.
- **No hardcoded rows or columns.** Find rows by col-B label, weeks by date
  header. Templates change; label lookup survives.
- **Never delete or overwrite a tab someone filled in**, even to rebuild
  cleanly.
- **Sandbox + `--dry-run`** until Megan says otherwise, and preview on ONE
  office before touching the rest.

## Known blockers

**Drive scope.** The OAuth token has **Sheets scope only, not Drive**, so the
automation cannot create a spreadsheet — `client.copy()` returns 403. That
matters here because the design needs one workbook per office. Either Megan
creates the workbooks by hand (as she did for the metrics offices) or we add
the Drive scope and let the onboarding step create them. **Adding the scope is
the better answer at 40+ offices** and should be decided before build, not
during.

**Frontier has no Tableau source.** Abel Draper's numbers come off an emailed
Credico PDF. Any "pull it from Tableau" assumption silently produces an empty
board for him.

**Two campaigns are not on the daily-metrics path at all.** B2B and Box/JE
owners sell products the shared AT&T metric views do not describe. Carlos is the
standing example — trackers yes, metrics thread no, and that is correct. Their
sales board can still be built from the campaign views; their *metrics* section
cannot, and should say so rather than render empty.

## Open decisions

1. **Raf: production only, or attendance too?** Asked in-thread, unanswered.
   Decides whether an owner page is one board or several.
2. **Raf: the funnel goal numbers** from the conference talk. Without them the
   recruiting section can show actuals but not whether anyone is on target.
3. **Eve: does Isaiah get a Disconnects board?** He posts one; Drew, on the same
   wireless-only campaign, does not.
4. **Eve: which removals count** as "apps removed" — disqualified, withdrawn,
   duplicate, aged-out. They mean different things.
5. **`active reps` — roster or producers?** On the trackers "Rep Count" means
   reps who PRODUCED. "% of reps selling" is meaningless until the denominator
   is pinned. Do not let both be called "active".
