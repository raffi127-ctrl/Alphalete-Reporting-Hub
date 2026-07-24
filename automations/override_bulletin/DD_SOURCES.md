# DD Bulletin — source + rules map

Item 4 of the VA replacement. Reverse-engineered from the VA's Loom walkthrough
(2026-07-23) plus the live sheet. **Read this before touching `dd_build.py`.**

Cadence: VA builds it **Wednesday**, posts **Thursday morning by 10am**. Numbers
were still moving Thursday morning, so she moved to building it very early
Thursday instead. Goes to Slack **#alphalete-sales + #alphalete-lvl1-chat**
(Megan also lists #rafs-office-recruiting) AND by email to **Alphalete Org
Owners** + a 4-person **Bulletins** distro. A separate "Up and Coming RCs and
NCs" email follows — email only, no Slack (NOT built).

## Data tab

`Org DDs Ongoing Report` (workbook `1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E`,
gid 423082205). Cols: ICD | Active ICD | Campaign | ORG | Total DD 2026 | weekly
WE cols. Blocks ALREADY in the tab — read them, don't recompute:

| Rows | Block |
|---|---|
| 132 | `Total - Raf` → the headline **ORG. TOTAL DD** ($1,010,586.70 @ 7.19.26) |
| 133 | `Total - Carlos` |
| 135–153 | **ORG/CAMPAIGNS AVG DD** (per-org + per-campaign averages) |
| 155–173 | **Active Owners** counts (per-org + per-campaign) |
| 184–196 | Months Company Revenue — NOT used in the email |

## WHO IS INCLUDED (the VA's rule, verbatim)

> "If someone is in Raf's captainship and is **not an owner**, he will not be
> included." Cody Cannon IS in Raf's captainship but IS an owner → included.

Excluded by this rule in the Loom: Alex Turzynski, Stephen Sharon, Marcial
Rodriguez, Natalia, John Richard Young, Tony, Trang, Tre Mitchell.
New owners: Maud posts a "new owners coming up" message — that list is the
authority for whether a new name counts. When in doubt, ask Maud/Megan.

## ADOPTIONS — excluded from the org total

**Carrington Moody** and **Milan Godbolt** sit under Colten's captainship but are
**not part of the organization** ("adoptions"). Their numbers are used later but
the org total formula is *everyone EXCEPT Carrington and Milan*. The VA keeps a
duplicate tab named `adoptions` holding them. Their figures are typed MANUALLY,
not formulas.

## CREDICO — a real second source

Direct deposits from Credico must be ADDED to each owner's weekly number.
- `arc.credico.com/#/dashboard/sales-management` → **Sales Management → Reports**
  (Carlos's login).
- **The date runs ONE WEEK FORWARD.** For week ending 3.22 she pulls **Saturday
  the 28th**, not the 21st. Always pick the FOLLOWING Saturday.
- Credico reports by **company**, not person → map company → owner. Known:
  `Able Acquisitions → Abel Draper`, `Phoenix Acquisitions → Jhavid Thompson`.
  These owners are often absent from the main list and must be ADDED.

### The working file (Tableau crosstab, campaign-pivoted)

The VA's file is the downloaded DD crosstab: `cl.ICD Owner Name` then ONE COLUMN
PER CAMPAIGN — RES-ATT, NDS Wireless, B2B-ATT-SBS, BOX-Energy, Just Energy,
RES-DTV, ATT Wireless, ATT Internet, PER CARTS, Clear Aligner, LeafGuard,
Sterling — and she appends two columns by hand:
**`credico`** (the Credico pull) and **`total`** (= sum of every campaign column
+ credico). So an owner's weekly DD = their campaign row summed ACROSS campaigns,
plus Credico.

### Row hygiene the VA does by hand — BUILT, in `dd_rows.py`
Both DD inputs arrive dirty the same way, so the rules live once in
`override_bulletin/dd_rows.py` and the Tableau crosstab and Credico share them.
`python -m automations.override_bulletin.dd_rows` runs the worked examples below.

- A person can appear on **two or three lines** → merge into one (sum). Seen in
  her file: `Selena Powers` + `Selena Powers LEDGER`; and Amjad Malhas across
  THREE rows — a named row, a **blank-name continuation row** beneath it, and
  `Amjad Malhas Ledger`. So merge on: same owner, a `… LEDGER/Ledger` suffix, and
  blank-name rows that belong to the owner above. **Source order is load-bearing**
  — a continuation row is defined by what sits above it.
- A **+150 / −150 pair cancels out** → delete both lines (it's a cancellation).
  Pairing is greedy on absolute value, so +150, +150, −150 leaves one +150.
- Name matching between sources: `Carlos` needs **TX** appended; `Roshan` needs
  his second name. (This is exactly what the shared ICD Aliases table is for.)
- Format trap: pasted numbers missing the `$` format are silently skipped by the
  SUM. She copies the format down BEFORE pasting. The parser reads either form,
  so this cannot happen to us.
- Anything unplaceable — a blank-name row with nothing above it, a company with
  no owner mapping — is **REPORTED, never dropped**. An unmapped company is
  somebody's money going missing.

### Pull status — `automations/credico/report.py`
Session (`credico/session.py`), the one-week-forward date rule, parsing, merging
and company→owner mapping are **done and tested**. The page extraction is
**deliberately not written**: nobody has seen the Reports screen, and invented
selectors on a hash-router SPA return `[]` on any layout change, which reads as a
quiet $0 week. `pull()` raises rather than returning an empty dict.

Next step, ON LUCY 1 (where the saved session lives):
```
lucy rerun credico_check                              # session still good?
python -m automations.credico.report --discover       # dumps the screen
```
Discovery writes to the **`_credico_discover` tab** of the override workbook (and
`output/credico/discover.tsv`), so it is readable from any machine — same pattern
as `override_bulletin/discover.py`. Then write `_extract()` against real markup.

## THE PODIUM — ALPHALETE ORGANIZATIONAL LEADERS

Ranked high→low by each leader's org DD total.

**DO NOT try to derive the podium from the `Org Tree` tab.** Two sessions have
now burned hours on it. Each leader's figure is a **specific ICD list** that
exists only in the VA's emailed bulletin — it is neither the flat `ORG` column
nor any downline roll-up, and no tree walk reproduces it.

The lists are transcribed onto **`Lucy Org Tree` (gid 1263646043)** in two
label-found blocks, and `dd_data.load()` just adds them up:

| Block | Columns |
|---|---|
| `PODIUM LEADERS` | Leader, Location, **Minus orgs**, Expected ICDs, Expected week DD, Note |
| `PODIUM ORG LISTS` | Leader, ICD (name as on the DD tab), Manual week DD, Manual total 2026, Note |

Rules the reader applies:
- A leader's figure = the sum of their ICD rows, looked up on the DD tab by name
  (through ICD Aliases). **Manual week DD** is only for people with NO DD row.
- If **Minus orgs** is filled in, the figure is the **ORG. TOTAL DD headline
  minus the ROW-BACKED part of those orgs' lists** — see the correction below.
  That is Raf's row, the "Total outside of Carlos & Colten" line.
- Every leader row carries the bulletin's **expected** count and total; a
  mismatch over $0.50 is reported, never quietly published.

Verified against the 7.19.26 send — six reproduce **exactly**, and Raf's is
**deliberately corrected** (see "Raf's line" below):

| Leader | ICDs | Week DD |
|---|---|---|
| Colten Wright | 14 (incl. adoptions) | $431,124.00 |
| Carlos Hidalgo | 18 | $329,005.70 |
| Rafael Hidalgo | headline − Carlos − Colten | **$292,419.00** (VA sent $250,457.00 — corrected, below) |
| Eveliz Wright | 3 | $69,463.00 |
| Khalil Mansour | 3 | $63,204.00 |
| Salik Mallick | 2 | $48,267.00 |
| Hammad Haque | 2 | $48,267.00 |

Gotchas the numbers pin down:
- **Cody Cannon counts in FULL to Carlos**, not split — that is what makes
  $329,005.70 land to the penny.
- **Raf's line: the VA's send was WRONG and we correct it.** Her sheet subtracts
  Colten's FULL list total, but $41,962.00 of that (Justin $13,088, Marcos
  $1,475, adoptions $27,399) belongs to people with no DD row, who were never in
  the $1,010,586.70 headline. You cannot subtract money the base never contained.
  Her $250,457.00 understates Raf by exactly that $41,962.00.

  The correct figure is **$292,419.00**, and two independent routes agree:
  1. headline − Carlos's row-backed total ($329,005.70) − Colten's row-backed
     total ($389,162.00) = $292,419.00
  2. adding up the 12 active ICDs on neither list (Raf, Kash Rai, Aya, Cyrus,
     Rashad, Isaiah, Salik Waqar, Ronald, Haytham, Hammad Ul Haque, Jacob Dover,
     Tevin Sterling) = $292,419.00

  `dd_data` computes route 1 and asserts route 2 matches; a disagreement means a
  list is wrong and is reported rather than published. **Megan approved the
  correction 2026-07-23** — if a future send still shows $250,457, ours is right.
- **Salik's list excludes Salik's own $9,342 DD** (he is `Salik Waqar` on the DD
  tab). Deliberate. Hammad shows the SAME 2 ICDs — correct, not a duplicate.
- **Justin Fermin ($13,088) and Marcos Barbosa ($1,475) have no DD row at all** —
  not a spelling problem, they are simply absent from the tab. They live in the
  list as Manual week DD and are re-surfaced under "Tracked Separately".
- Eveliz is Colten's wife — location **Miami, Florida** (not Michigan).
- Leaders seen: Colten, Carlos, Raf, Khalil, Zach, Eveliz, Salik, Hammad,
  Benjamin Burden (the count varies by week; 7.19.26 showed 7). Zach Hogue is
  Active NO with $0 this week, which is why he is off this week's podium.

Podium totals OVERLAP by design (a larger org contains smaller ones), so they sum
to MORE than the org total.

### Still open on the podium (needs the emailed bulletin to close)
1. Carlos's list computes right with 19 names but the bulletin says **18** — one
   of the two $0 people (David Martinez, Benjamin Burden) is not on it. No effect
   on the money, only the count.
2. The **adoptions are one line worth $27,399 combined**; the per-person split is
   unconfirmed (derived, not read).
3. **No 2026 totals** for Justin, Marcos or the adoptions, so Colten's "in 2026"
   card figure is understated. Flagged on every run.

## THE LIVE SHEET IS THE SOURCE OF TRUTH — not a sample email

Megan 2026-07-23: **the emailed bulletin sample was OLD.** Hours were spent
"reconciling" the podium against it and finding phantom gaps for Colten, Carlos
and Raf. There are no gaps — the live `Org DDs Ongoing Report` tab carries the
current numbers and the roll-up computed from it is correct.

Never treat a screenshot/sample email as the answer key. If a computed figure
disagrees with a sent bulletin, the SHEET wins. (A stale "confirmed podium"
block was seeded into `Lucy Org Tree` from that old email and has been removed —
it would have published stale numbers every week.)

## Superseded: the tree roll-up (kept for the lesson only)

The old `Org Tree` walk got 4 of 7 (Eveliz, Khalil, Salik, Hammad) and could
never close Colten, Carlos or Raf. Every "gap" was an artefact of the tree not
being the source: Carlos's −$13,154.50 was Cody counted at x0.5 instead of in
full, and Colten's shortfall was the bulletin-only people who have no DD row.
The list-driven reader above replaces it entirely. **Don't rebuild it.**

**Jacob Dover is SPECIAL** (Megan 2026-07-23). Tree puts him under Hammad via
Tevin Sterling, but the sent bulletin excludes him — excluding him is what makes
Salik AND Hammad land exactly. Treat him like the adoptions: **excluded from the
org roll-up but STILL pulled and reported** (Active YES, ATT-RES-Fiber, ORG col
Salik, 2026 $108,004; 7.19 $21,863, 7.12 $15,191, 7.5 $10,508). His numbers must
never silently disappear.

Every failure so far has been a NAME MISMATCH, not a structural one — including
`Salik Malick`/`Mallick`, `Max Aden`/`Maxamad`/`Maxamed`, `MJ Malhas`/`Amjad`.
All are now rows in the shared ICD Aliases tab. `Lucy Org Tree` (gid 1263646043)
holds the tree tied to the DD sheet's names, with a match-status column.

## Presentation

The OneDrive `Org. Bulletin.xlsx` and BeeFree are **formatting only** (Megan:
"just used to make it look pretty") — both are replaced by rendering the branded
layout ourselves. The VA's Slack image is a crop of just the tables, enlarged in
Paint, because a screenshot of the whole email is unreadable — our render should
make that crop unnecessary.

Footer: **"Learn More. Dream More. Do More."** + the ALPHALETE ORGANIZATIONAL
LEADERS blurb ("...maintain three successful promotions outside your own
office...").
