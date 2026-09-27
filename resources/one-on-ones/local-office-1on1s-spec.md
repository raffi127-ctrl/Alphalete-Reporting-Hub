# Local Office 1on1s — report spec

Source: Raf's Loom, 2026-09-27 —
https://www.loom.com/share/a197dcc15c944fa4bf853f49378f76ff
(tagged to Megan, cc Eve)

> "The most tedious task is just getting the data, which is why I'm so
> hit-and-miss about doing it with the reps. What I would like is for it
> just to automate it, and all of it being connected to the sales board."

This is the **local office** 1on1 sheet — Raf's own office. It is NOT
[[project_org_1on1s_report]] (the "Alphalete Org 1on1s - Focus Report"
tab, which is per-ICD and PP-driven). Different sheet, different grain:
here a box is **one rep**.

---

## Shape

**Tabs: one per team.** Alphaletes, Se7en Sins, Ceaseless, Hashiras,
Mindset Engine. Raf: "it would delete these" — the existing per-person
tabs get cleared out and replaced by five team tabs.

**Inside a tab: one box per rep** (Hayden, Thomas, IBK, Zoe, …), stacked.

**Only leaders get a box.** Raf: "it only has to do it for leaders. So if
they're an entry-level, it doesn't have to." Same test
`gap_alerts/leaders.py` already uses — sales-board `Leadership Status`
above Entry Level on the ladder (In Training → Entry Level → Level 1 →
Level 2 → Mastermind), terminated excluded via `terminated_reps.board`.

**Two box templates.** Raf keeps these two and deletes the rest:
1. **Rep template** — the average rep who is a leader but has no team of
   their own yet.
2. **Team-leader template** — a rep "running their own team", i.e. they
   have a team NAME. Same rep fields, plus the team block at the bottom.

**Schedule: Sunday morning, data as of Sunday morning. Then again
Monday morning** — "because sometimes the reps do sales on Sunday."
Same tabs, same boxes, overwritten. Not a second post/sheet.

---

## Field → source map

Everything below is by-label lookup, never a fixed row/column
([[feedback_no_hardcoded_columns]]). Grain is one rep per box.

### Rep fields (both templates)

| Field | Source | Already built? |
|---|---|---|
| Knocking data | Weekly Knock Dispositions per-rep rows — Mon–Fri Total Knocks, Mon–Fri Total Leads Knocked, Mon–Fri Avg Doors/Day, Sat Avg Doors/Day, Mon–Sat Avg Knocks/Hr, Mon–Sat % Talk To's per Knocks | **Yes** — `automations/weekly_knock_dispositions/board.py`. Raf: "comes from the knocking report that gets sent out." |
| Sales | The office sales board, per-rep row | **Yes** — `automations/icd_sales_board/board_read.py` (Raf's "Alphalete SALES BOARD 2025", `Sales Board WE m.d` tabs, rep block ends at `TOTALS`) |
| 2nd Rounds Conducted | Recruiting funnel — AppStream p=783 "Retention - Details (new)" | Partly — see **Gap 1** |
| Job Offered | same | Partly — Gap 1 |
| 2nd Rounds Closed (a NUMBER — Raf corrected this live: "so that should be a number") | same | Partly — Gap 1 |
| % 2nd Round Close | formula off the two above | formula |
| BOB | same | Partly — Gap 1 |
| New Starts Scheduled / New Starts Shown | same | Partly — Gap 1 |
| **These six are MONTHLY, not weekly.** Raf: "This is monthly, so it doesn't have to be weekly… when I was filling it out manually, it would be for the month. What are they at?" | | |
| Trained This Week | Sales board — reps whose `Trainer` cell names this rep, filed to the week | Reader exists (`sales_board_mind_map` walks the Trainer chain); the weekly count is new |
| Retained (= not terminated) | Sales board termination, all three markings | **Yes** — `terminated_reps.board`. Raf: "that would come off of the fact that the rep is not terminated yet on the sales board." |
| Gross Paycheck | `Got Paid` out of the P&Ls | Partly — see **Gap 2** |

Raf on one block: *"This stuff right here would just be us."* — a set of
cells stays manual/leadership-entered. Which ones is in **Question 3**.

### Team block (team-leader template only)

| Field | Source | Notes |
|---|---|---|
| Team Structure — All | Trainer chain off the sales board, first-gen count + whole-team count | `sales_board_mind_map` already prints exactly this as "Name 2/5" (2 first gens, 5 in the whole team). Raf: "it's got team structure all, which is what that means is entry levels." |
| Team Structure — with Leaders | same chain, leaders only | same source, filtered by `Leadership Status` |
| Active Reps | team size, **week ones excluded** | Raf: "I would not count a week one an active rep." Week is on the board (colour + "WK1 New Start" rank) |
| # Leaders | `Leadership Status` above Entry Level, in their downline | `gap_alerts/leaders.py` test |
| New Starts that started | board New Starts / Classroom block | |
| How many are alive | of those, not terminated | `terminated_reps.board` |
| New Start Retention | formula (alive ÷ started) | formula |
| Team totals — "what did they all do" | sum of the rep rows in their downline | Raf: "this would be formulas, I believe" |

Note the upline rule: a rep's team comes from their **Trainer chain**,
not their own `Team` cell — "their trainer is their upline" (Megan,
2026-09-20, in `sales_board_mind_map`). The five team names are the
roots. That module's tree is the thing to reuse for every structural
number here, rather than re-deriving the chain.

---

## Gaps (real work, not unknowns)

**Gap 1 — the funnel numbers are not per-rep today.**
`automations/funnel_board/` pulls all eleven funnel metrics from
AppStream p=783, but per **office/manager** — and `fetch.py` explicitly
skips the per-recruiter breakdown (`tr.adminRow`). The per-person rows
exist in the page; `automations/recruiter_stats/` already reads a
per-admin cut of a sibling report. So the pull is a known change, not a
new capability. **Open:** whether field leaders (Hayden, Thomas, IBK,
Zoe) appear as recruiters/admins in that breakdown at all — see
Question 2.

**Gap 2 — only one P&L is wired.**
`automations/reps_gross_paycheck/pnl.py` reads per-rep `Got Paid` out of
`Raf PNL 2026` (in "All in One Local Office - Raf") and already handles
the traps: sub-rosters below row ~389 (AYA, CY - Rafs DD, CY - Cy's DD,
Zach, Rashad), people on two rows, and the 3-wide
`Brought In | Got Paid | Profit/Loss` week blocks found by header.
Raf wants all three searched: "there's a couple different PLs here, so
it would have to search the three PLs, and then it would just grab got
paid." Repo also knows `B2B PNL`, `Fiber PNL`, `JE PNL`, and
`Copy of Carlos PNL 2026` — but those three are program blocks on the
Focus Report tab, office-level, no per-rep `Got Paid`. So the three
rep-level P&Ls have to be named. See Question 3.

**Gap 3 — the fill itself.** New module, per the house pattern: sandbox
copy of the sheet + `--dry-run` until the output is confirmed; preview
on ONE box first (Raf's own default preview rep) before the other four
tabs get touched.

---

## Blockers

1. **The spreadsheet URL.** The template layout — which rows carry which
   label, in what order, in each of the two box templates — can only be
   read off the sheet. [[feedback_ask_for_the_url]]
2. **Do the field leaders show up in AppStream's per-recruiter
   breakdown on p=783?** If 2nd rounds are logged under the office
   admin who booked them rather than the leader who conducted them,
   Gap 1 needs a different source (or those six cells stay manual).
3. **Which three P&Ls, and are the other two per-rep with a `Got Paid`
   column?** Raf said "search the three PLs" while pointing at the
   screen; only `Raf PNL 2026` is a known per-rep one.
4. **"We can just delete all of these"** — the existing per-person tabs.
   Deleting tabs someone filled in is exactly the thing this repo does
   not do without a confirm, and they get backed up to `output/` first.
   Needs an explicit go from Raf, not just the Loom aside.

## Not blockers (decided)

- Five tabs, named for the five teams; boxes only for leaders.
- Sunday AM fill + Monday AM re-fill, same cells.
- Monthly grain for the six funnel fields, weekly for everything else.
- Week ones are not active reps.
- Structure numbers come from the Trainer chain, via the mind-map tree.
