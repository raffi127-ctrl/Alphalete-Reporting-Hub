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

### Row hygiene the VA does by hand
- A person can appear on **two or three lines** → merge into one (sum). Seen in
  her file: `Selena Powers` + `Selena Powers LEDGER`; and Amjad Malhas across
  THREE rows — a named row, a **blank-name continuation row** beneath it, and
  `Amjad Malhas Ledger`. So merge on: same owner, a `… LEDGER/Ledger` suffix, and
  blank-name rows that belong to the owner above.
- A **+150 / −150 pair cancels out** → delete both lines (it's a cancellation).
- Name matching between sources: `Carlos` needs **TX** appended; `Roshan` needs
  his second name. (This is exactly what the shared ICD Aliases table is for.)
- Format trap: pasted numbers missing the `$` format are silently skipped by the
  SUM. She copies the format down BEFORE pasting. An automated fill avoids this
  entirely.

## THE PODIUM — ALPHALETE ORGANIZATIONAL LEADERS

Ranked high→low by each leader's org DD total. NOT the flat `ORG` column — it is
a **downline roll-up via the `Org Tree` tab**, minus adoptions:
- **Raf's figure is "total outside Carlos and Colten"** — his org EXCLUDING those
  two subtrees.
- **Hammad sits inside Salik's org**, and Salik takes no personal DD, so the two
  legitimately show the SAME number. This is correct, not a duplication bug.
- Eveliz is Colten's wife — location **Miami, Florida** (not Michigan).
- Leaders seen: Colten, Carlos, Raf, Khalil, Zach, Eveliz, Salik, Hammad,
  Benjamin Burden (the count varies by week; the email screenshot showed 7).

Podium totals OVERLAP by design (a larger org contains smaller ones), so they sum
to MORE than the org total — 7.19.26: podium $1,239,788 vs org total $1,010,587.

## Presentation

The OneDrive `Org. Bulletin.xlsx` and BeeFree are **formatting only** (Megan:
"just used to make it look pretty") — both are replaced by rendering the branded
layout ourselves. The VA's Slack image is a crop of just the tables, enlarged in
Paint, because a screenshot of the whole email is unreadable — our render should
make that crop unnecessary.

Footer: **"Learn More. Dream More. Do More."** + the ALPHALETE ORGANIZATIONAL
LEADERS blurb ("...maintain three successful promotions outside your own
office...").
