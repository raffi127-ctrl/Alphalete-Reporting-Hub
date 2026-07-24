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

## ADOPTIONS — the rule, from Raf (email, shared 2026-07-24)

**Karrington Moody** and **Milan Godbolt** sit under Colten's captainship but are
**not part of the organization** ("adoptions"). The VA keeps a duplicate tab named
`adoptions` holding them; their figures are typed MANUALLY, not formulas.

Raf's own words on what an adoption IS and how to report it — this is the
authority, and our handling below matches it:

> "2 of these deals are not organic deals, they are **'Adoptions'** or what SCI
> calls **'Double over ride promotion'**" — SCI approved an owner to take a 1st
> gen override off an individual who came organically from *another* owner
> (retrains, transfers, an owner mentoring inside someone else's building).

- The adopting upline gets the double override but **no regional or national
  override**, and depth promotions underneath an adoption don't earn those
  either — though the adoption **does** count toward regional/national
  consultant *qualification*.
- **SCI's own reporting excludes adoptions**: asked "how many reps are in this
  person's org" or "how many UNITS is this org selling", SCI does **not** count
  adoption headcount or sales.

Raf's instructions for OUR reporting, and where each lands in the code:

| Raf's rule | How it is implemented |
|---|---|
| "Include the deals in the reporting." | They render on page 2 under **Tracked Separately**, with a per-row reason. |
| "When adding up total units for 'My org' don't count adoptions that aren't mine, **only count them for the person receiving the double over ride**." | They are OUT of the ORG. TOTAL DD headline, and IN **Colten's** podium list — Colten is the person receiving the double override. |
| "Future depth promotions shouldn't…" | *(the pasted copy cuts off mid-sentence — get the rest before wiring depth handling)* |

So the current treatment is correct on Raf's rule, not just on the VA's habit:
excluded from the org total, counted for Colten, and never invisible.

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

### The Reports screen — MAPPED 2026-07-24 (7 probe runs on Lucy 1)
`lucy rerun credico_discover_deep` re-runs the probe; output lands on the
**`_credico_discover` tab** of the override workbook, readable from any machine.

**Fee Reports is a FILE BROWSER, not a grid.** The path is:

    Sales Management → Reports → "Fee Reports" → a week (Saturday) → an office → FILE

- The **Reports list** is three `[ng-click="r.getReport(report)"]` links:
  **Fee Reports**, **Personal**, **CDF Report**. Only Fee Reports has anything —
  the other two say "No files found."
- Opening Fee Reports lists **weekly Saturdays**: 2026-07-25, 07-18, 07-11, …
  This is the one-week-forward cadence, confirmed live: `credico_saturday()`
  returned 2026-07-25 for week 7.19.26 and that date was in the list.
- Opening a week lists the offices inside `div.report-list` as
  `<div class="col-item" ng-click="r.clickNode(displayFile)">` — **no href, no
  download attribute**. So the file is fetched by a JS handler, not a plain link.
- Office names as Credico spells them (these are the mapping keys, and they are
  NOT what this doc used to say):
  | Dropdown | id | Owner |
  |---|---|---|
  | `Abyl Acquisition Group, Inc.` (`Abyl Acquisition Grp` in the file list) | 2041 | Abel Draper |
  | `Phoenix Acquisition Group, Inc.` (`Phoenix Acquisition`) | 2062 | Jahvid Thompson |
- Campaigns: **Frontier B2B** (105), **Frontier Communications** (36). There is
  also an **"All offices"** checkbox, so one fetch may cover both offices.
- Traps found the hard way: the office/campaign `<select>`s are inside a
  `display:none` ancestor until a report is opened (they report visible but have
  no `offsetParent`), so set them by assigning `.value` + dispatching `change`;
  and `goto()` does NOT reset a hash-router SPA already on that URL — use
  `reload()`, or the second and third reports come back "no link found".

### The file, and what is in it (downloaded 2026-07-24, Megan approved)

The office node drills to ONE more level — a single file node:

    2026-07-25~Abyl Acquisition Grp~Commissions.xlsx      (90,012 bytes)

**It is an XLSX**, six sheets: `CommissionSummary`, **`CommissionDetail`**,
`BonusApps`, `StatusChanges`, `DetailAndStatus`, `Installments`.

- `CommissionSummary` (13×5) is a pivot BY CAMPAIGN with **no names** — Frontier
  B2B / Frontier Communications / Grand Total over Full, Payment, ISOFee,
  Attachment Bonus, Kicker Incentive, Other, Deduction, Wire Fee. Abyl's week:
  Grand Total **$6,058** (the $6,068 "Full" line less $10 of deductions).
- **`CommissionDetail` (93×37) is the payload** and it IS per person:
  `OfficeID | OfficeName | CommissionWeek | CampaignID | CampaignName |
  CommissionGroup | CommissionItem | PayType | ActionType | TransAmt | Detail |
  AgentName | BadgeNum | SaleWeek`
  `AgentName` arrives **"Draper, Abel"** (Last, First) and is flipped before
  alias resolution. Deductions are already negative, so summing `TransAmt` is
  the net. Columns are found BY HEADER LABEL, and the header ROW is located by
  looking for AgentName+TransAmt — Credico can add a column or a title row.

### THE DIRECT DOWNLOAD API — better than the DOM walk
The click's network trace exposed a plain REST API on `arcapi.credico.com`:

    GET /api/offices              GET /api/offices/2041      GET /api/campaigns
    GET /api/Downloads/FolderList/PayReports
    GET /api/downloads?filename=C:\inetpub\Pay Reports\<office>\<date>\<date>~<office>~Commissions.xlsx

The filename is fully predictable from office + date, so a future version should
fetch straight from `/api/downloads` and skip the seven-step DOM walk entirely.
The session cookies already authenticate it.

### Status: END TO END, on real data
`lucy rerun credico_fetch` → `lucy rerun credico_parse` produced per-person
amounts (Abel $474, Yerailis Cuevas-Castillo $395, Yehonatan Bennaim $355, …).
`pull()` raises rather than returning an empty dict — a silent `{}` would zero
every Credico owner's week and look like a real result.

### RECONCILED AGAINST THE VA TAB (Megan: "you should be matching the VA tab")
`lucy rerun credico_reconcile` matches each office against `Org DDs Ongoing
Report`, which already reflects however the VA folds Credico in. Week 7.19.26:

| Office | Credico office total | VA tab cell | Gap |
|---|---|---|---|
| Abyl Acquisition Group → **Abel Draper** | $6,058.00 | $6,578.00 | **$520.00** |
| Phoenix Acquisition Group → **Jahvid Thompson** | $11,978.00 | $12,068.00 | **$90.00** |

**Settled: an owner's Credico DD is the WHOLE OFFICE**, not just their own agent
rows. Those rows are tiny — Abel $484, Jahvid $360 — and would leave gaps of
$6,094 / $11,708. The office total leaves $520 / $90, which is the Tableau
portion Credico is ADDED to. Credico is 92–99% of these two owners' weekly DD,
so getting it wrong would gut both numbers.

Practical consequence: the Credico owners really are near-absent from the main
DD source, exactly as DD_SOURCES said — their week is essentially the Credico
file. Both offices now download (the fetch re-navigates per office rather than
unwinding history, which is why only the first one used to come back).

### Open, and worth Megan's eye
1. **The period is worth a sanity check.** The file for Saturday 2026-07-25 is
   headed "Jul 19 - Jul 25 2026" and its rows carry `SaleWeek` values from JUNE
   (816: Jun 14-20). So the one-week-forward rule lands on a commission week
   that PAYS sales from weeks earlier. That is the VA's documented rule and it
   is reproduced faithfully — but it means Credico money added to sheet week
   7.19.26 was earned well before it. Ask Carlos whether that is intended.

## THE PODIUM — ALPHALETE ORGANIZATIONAL LEADERS

Ranked high→low by each leader's org DD total.

**DO NOT try to derive the podium from the `Org Tree` tab.** Two sessions have
now burned hours on it. Each leader's figure is a **specific ICD list** — neither
the flat `ORG` column nor any downline roll-up, and no tree walk reproduces it.

**And do NOT go looking for those lists in the emailed bulletin.** Verified
2026-07-23 against the real send (`Alphalete Organization Bulletin WE`,
alphaletereporting@gmail.com, 7/23 15:32, WE 7.19.26): the email carries **only**
the headline and the 7 leader cards — name, city, one dollar figure each. No ICD
tables, no 2026 totals, no adoptions breakdown. The lists live in the VA's own
working file (the campaign-pivoted Tableau crosstab plus her `adoptions` tab),
which we do not have. Ours were reconstructed and are validated against the
published figures to the penny — that check is the thing to trust.

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

### Still open on the podium — needs the VA's WORKING FILE, not the email
None of these affect a published weekly figure; all three are flagged every run.
1. Carlos's list computes right with 19 names but the count says **18** — one of
   the two $0 people (David Martinez, Benjamin Burden) is not on it. The count is
   not rendered anywhere, and the money is confirmed correct either way.
2. The **adoptions are one line worth $27,399 combined**; the per-person split is
   derived, not read. Also not rendered per person.
3. **No 2026 totals** for Justin, Marcos or the adoptions. This one DOES show:
   Colten's card reads "(partial)" after his 2026 figure rather than printing a
   number we know is short. Note the 2026 line is OUR addition — the VA's
   bulletin shows the week only — so this is a nicety, not a defect.

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
