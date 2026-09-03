# DD Bulletin — source + rules map

Item 4 of the VA replacement. Reverse-engineered from the VA's Loom walkthrough
(2026-07-23) plus the live sheet. **Read this before touching `dd_build.py`.**

Cadence: VA builds it **Wednesday**, posts **Thursday morning by 10am**. Numbers
were still moving Thursday morning, so she moved to building it very early
Thursday instead. Goes to Slack **#alphalete-sales + #alphalete-lvl1-chat**
(Megan also lists the recruiting rooms — #rafs-office-recruiting (retired) and, from
2026-08-20, #rafs-office-recruiting-11280) AND by email
to **Alphalete Org
Owners** + a 4-person **Bulletins** distro.

A separate **"Alphalete Up and Coming RCs and NCs"** email follows — email only,
no Slack (**NOT built**). Inspected 2026-07-24: WE 7.19 went out 7/23 16:20, ~48
minutes after the bulletin, to 61 addresses (the bulletin distro less a couple).
The body is **a single inline PNG** — `Up and Coming RCs and NCs WE 7.19.png`,
973×1139, no HTML table and no text at all. So there is nothing to parse out of
the sent mail: building it means finding the source it was screenshotted from,
the same way the bulletin's own tables had to be reconstructed.

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

## ADOPTIONS — the rule, from Raf (email **2026-03-10**, shared with us 07-24)

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
| "When adding up total units for 'My org' don't count adoptions that aren't mine, **only count them for the person receiving the double over ride**." | They are OUT of the ORG. TOTAL DD headline, and IN the podium list of whoever receives the override. |
| "Future depth promotions shouldn't…" | *(unfinished — see below; depth stays unwired)* |

**STOP LOOKING FOR THE REST OF THAT LINE.** Found in the original 2026-03-10
thread (`Re: Alphalete Org Sales Board 3/9`, raffi127@ → Colten/Maud/Eve): Raf's
own sent email ends the bullet mid-word — *"Future depth promotions shouldn't but
pl"* — and goes straight on to "Hopefully this makes sense". Nothing was lost in
the paste; he never finished the sentence, so no mailbox holds it.

The substance is in the paragraph above it, in his words, and is enough to wire
depth if it ever matters: *"when the adoption promotes someone, this individual
will still not make a regional or national override off of the DEPTH promotions.
But the adoption will count towards the qualifications for regional or national
consultant."* Confirm with Raf before wiring — but ask about the RULE, not about
what the email said.

Same email, worth knowing before it surprises someone: **Colten is the org's
first adoption case, and Raf says he expects one of his own — "technically i'll
have Andrew Sanborn here soon."** When Andrew Sanborn appears, he is likely an
adoption under Raf, not an organic ICD.

### SETTLED 2026-08-06 — where the adoption money lands, and where it does not

Eve: *"es muy importante que cada semana, las siguientes personas repliquen su $
de la tabla de Colten que es donde yo introduzco el número a mano: Milan
Godbolt, Karrington Moody, Justin Fermin, Marcos Barbosa… todo esto afecta los
totales de cada Org y el total de la Org en general."*

**"La tabla de Colten" is the `ICD (Special Cases)` block on the DD tab** (rows
136-139 as of 8.2.26). All four rows are Colten's org — Justin sits under Jairo,
who sits under Colten — the ORG column says so, and Eve types each week's figure
into column F **by hand**. Nothing on the tab adds it up: `Total - Raf` is
`=SUM(F2:F131)` and the block starts at 136, so the money rendered on the page
but was in no total anywhere.

**The rule, in one line: an adoption is IN its leader's org figure and OUT of the
ORG. TOTAL DD.** That is Raf's own rule read straight — the adopting upline gets
the double override, and SCI does not count adoptions as organization headcount
or sales. Eve chose this explicitly on 2026-08-06 after seeing all three
candidate arithmetics side by side.

What that means, and what changed in `dd_data.load()`:

| Line | Where the adoption money goes |
|---|---|
| **ORG. TOTAL DD** | OUT. Stays the tab's `Total - Raf` (`=SUM(F2:F131)`), which cannot reach rows 136+. |
| **Colten / Jairo TOTAL** | IN. `row_wk` / `row_keys` now include the special rows (this is the change — the old code excluded them). |
| **Colten / Jairo ORGANIC** | OUT, via the `Adoption?` flags. Unchanged. |
| **Rafael "outside Carlos & Colten"** | OUT — subtracted with Colten's full total, so raising the adoptions LOWERS Rafael by the same amount. |
| **All ICDs / Tracked Separately** | The four stay in Tracked Separately, labelled "adoption, not in the total". |

For 8.2.26: headline **$1,062,591.00**; Colten $491,363.00 (organic
$428,553.00); Jairo $217,519.00 (organic $201,858.00); Carlos $336,432.50;
Rafael $1,062,591.00 − $336,432.50 − $491,363.00 = **$234,795.50**.

**The 2026-07-23 "correction" to Raf's line is REVERTED.** That session read the
gap as arithmetic error — *"you cannot subtract money the base never contained"*
— and raised Raf by $41,962.00 to $292,419.00 on 7.19.26. Arithmetically true,
editorially wrong: Rafael's line means *what is left once Carlos's and Colten's
orgs are accounted for*, and an adoption under Colten is accounted for. **The
tell was that it made Rafael's figure immune to the adoption amounts** — Eve
expected him to move when they changed, and he did not. The VA's $250,457.00 for
7.19.26 was right all along.

The `direct` cross-check that used to enforce the old reading is kept, not
dropped: the two routes must now differ by **exactly** `special_week`, the
adoption money on the subtracted lists (computed from the podium side). Any
other difference still means a list is wrong and still blocks.

Two things deliberately NOT touched, both reported on every run:
- **AVG DD / Active Owners** are read off the tab and never recomputed. They
  exclude the four, which is now consistent with the headline.
- **The special block is hand-typed and nothing checks its freshness.** On
  8.2.26 all four cells were byte-identical to 7.26.26 ($21,050 / $13,614 /
  $19,239 / $4,706), which is what a copied column looks like. Worth a
  `week_is_filled`-style gate later.

### OUT 2026-08-27 — Milan Godbolt is off the bulletins for good

Eve, 2026-08-27: *"para los bulletins, hay que no incluir a Milan Godbolt de
ahora en adelante."* He had already come off Colten's captainship on 08-21
(`shared/captainship_pins.NOT_ON_TEAM`); the bulletins were left alone on purpose
until this week. **The removal is entirely on the Sheet — no code decides it**,
which is why it is written down here.

| Where | Was | Now |
|---|---|---|
| `Lucy Org Tree` **row 122**, PODIUM ORG LISTS | `Colten Wright \| Milan Godbolt \| $7,193 \| (no 2026 total) \| Adoption? YES` | RETIRED — B:D and F blanked, leader kept in A, reason in E. Same convention as row 87 |
| `Lucy Org Tree` **D64**, PODIUM LEADERS | Colten `Expected ICDs` = 14 | 13, or the count check prints "13 listed, bulletin says 14" every week |
| `Lucy Org Tree` **row 41**, the Org Tree mirror | `NO DD ROW` / `Adoption? YES` | RETIRED note in E, adoption flag cleared |
| `Org Tree` **C28** (gid 2106936862) | `Milan Godbolt`, a Gen-3 node under Colten | blank — see below |

What it moved on WE 8.23.26, checked before and after:

- **Colten Wright $392,776.15 → $385,583.15** (−$7,193). His 2026 total is
  unchanged and **stops saying "partial"** — Milan was the one member with no
  2026 figure, which had been understating nothing but flagging every week.
- **Tracked Separately drops from 4 rows to 3** (Karrington Moody, Justin Fermin,
  Marcos Barbosa stay — and all three still do: Marcos came out from under
  Colten's org later the same day, but his DD row and that line stayed put, see
  *OUT 2026-08-27 — Marcos Barbosa* below).
- **ORG. TOTAL DD and Rafael's line do not move.** Rafael is
  `headline − row_week(Carlos) − row_week(Colten)` and `row_week` counts only
  members backed by a real DD row; Milan was a MANUAL amount, so he was never in
  it. The `direct` cross-check and `adopt_gap` are untouched for the same reason.
- The companion **"Up and Coming RCs and NCs"**: clearing `Org Tree` C28 takes
  **Colten's First Gen from 9 to 8** and his Total Org down by one. Nobody else's
  card changes. `dd_search.py` `TARGETS` still names Milan — that is the one-shot
  diagnostic, not a live report, and it stays as the record of the July question.

### OUT 2026-08-27 — Marcos Barbosa comes out from under Colten's org

Eve, 2026-08-27, hours after the Milan Godbolt removal above: *"hay que sacar a
Marcos Barbosa de debajo de colten's org… y de la org sales board - capitania de
colten y sus reportes, tambien de la distro."* Same shape as Milan, with **one
difference that matters**: Marcos has a REAL DD row, so money moved.

| Where | Was | Now |
|---|---|---|
| `Lucy Org Tree` **row 86**, PODIUM ORG LISTS | `Colten Wright \| Marcos Barbosa \| $1,475 manual \| Adoption? YES` | RETIRED — B:D and F blanked, leader kept in A, reason in E. Same convention as rows 87 and 122 |
| `Lucy Org Tree` **D64**, PODIUM LEADERS | Colten `Expected ICDs` = 13 | 12 |
| `Lucy Org Tree` **row 43**, the Org Tree mirror | `NO DD ROW` | RETIRED note in E |
| `Org Tree` **C29** (gid 2106936862) | `Marcos Barbosa`, a Gen-3 node under Colten | cleared, then the blank row deleted |
| `Org DDs Ongoing Report` **row 138** | his `ICD (Special Cases)` row, ORG = Colten | **UNTOUCHED — deliberately** |

**Why the DD row stays.** That block is his weekly history and the bulletin only
ever renders it under *Tracked Separately*, which prints `# / ICD / weeks /
Total 2026` — the `why` string carrying "Colten" never reaches the page
(`dd_build._tracked`). What put him *inside Colten's org* was the podium list row,
not the DD row, so retiring row 86 is the whole removal. Tracked Separately still
shows 3 names; the $1,475 in C86 was already DEAD money (a real row beats a manual
one in `by_key` since 2026-08-06).

What it moved on WE 8.23.26, measured before and after with `dd_data.load()`:

- **Colten Wright $385,583.15 → $385,147.15** (−$436, his 8.23.26 special-case
  figure). His podium list goes 13 → 12 and his `adoptions` list loses him.
- **Rafael Hidalgo $247,851.50 → $248,287.50** (+$436), and this is CORRECT, not
  a leak. Rafael's line is `headline − row_week(Carlos) − row_week(Colten)`, and
  a special row counts inside `row_week` on purpose (Eve, 2026-08-06). Take
  Marcos off Colten's list and there is $436 less to subtract. The `direct`
  cross-check still balances, because `adopt_gap` falls by the same $436 —
  `direct == week + adopt_gap` holds on both sides of the edit.
- **ORG. TOTAL DD does not move** ($958,129.03): the headline never contained the
  special rows.
- The companion **"Up and Coming RCs and NCs"**: clearing his `Org Tree` node
  takes **Colten from 8 / 17 to 7 / 16** (First Gen / Total Org). **Rafael stays
  9 / 48** — the tab paints Marcos with the Adoptions red, and the root already
  dropped him. Carlos unchanged at 10 / 22.

**The rest of the removal, outside this file.** Three board rows (leaderboard
`COLTEN'S CAPTAIN TEAM`, the `ATT NDS - All Units` daily block, the `COLTEN
CAPTAINSHIP` delta box) via `org_sales_board/roster_remove.py`; **four rows on
`Churn - Colten Wright (NDS)`**, one per period block
(`output/remove_marcos_colten_churn.py` + snapshot) — that is where he differs
from Milan, whose churn tab never had him; the pin in
`shared/captainship_pins.NOT_ON_TEAM["Colten"]` so the NDS captain filter cannot
walk him back in; and the distro, out of both
`captainship_drafts/config.RECIPIENTS["colten"]` and the live
`Colten's Captainship` Contacts group. His card was on **no other live group**,
so that was the last report he received.

**This week's bulletin had already gone out** (`review_gate --check`: "already
sent this week"), so the figures above land on the NEXT send. The
`output/preview-up-and-coming-RCs-NCs-WE-8.23.png` preview built at 12:56 that
day is stale — `rcs_ncs_build --png` was re-run after the edit.

**Still under Colten elsewhere, on purpose** (not asked for): the §2 screenshot of
Tableau in the NDS draft, until SmartCircle drops him from the filter; and
`recruiting_report/dd_roster.json` + `all-offices.json` (ICD 22284, Capital Vision
Enterprise), which are not bulletin inputs.


### SETTLED 2026-08-27 — how Total Org is counted on the RCs/NCs board

Eve marked the Org Tree up by hand and then checked the rendered card against it
three times; this is where it landed. Three rules, and the third is the one that
had been wrong for months.

**1. The leader counts themselves.** "How many people are in Colten's org"
includes Colten. The tree only holds who is BELOW someone, so the code adds one.

**2. Adoptions count — for their own org, not for the root.** Raf, 2026-03-10:
*"When adding up total units for 'My org' don't count adoptions that aren't mine,
only count them for the person receiving the double override."* The adoptions sit
under Colten, so they are Colten's and Jairo's, and they are **not** Rafael's —
he is the one they are not "mine" for. Only the root of the tree drops them.

**3. Counting them at all is the other half of Raf's same email.** It has two
halves that point opposite ways, and which applies depends on what is being
counted:

| Raf's words | Where it applies |
|---|---|
| SCI "does not count adoption headcount or sales" when asked how many reps are in an org | the DD bulletin's MONEY — the ORG. TOTAL DD, `Adoption?`, the organic lines. **Untouched** |
| "the adoption **will** count towards the qualifications for regional or national consultant" | the **RCs/NCs board** — every ring on it is a metric measured against an RC/NC threshold |

`rcs_ncs_data` had been applying the money half here, subtracting adoptions from
every org including their own. That understated Colten on every companion that
has gone out. Worse, the exclusion ran off a hardcoded `ADOPTIONS` set that had
drifted — it never named **Justin Fermin**, though the tab paints him with the
legend's Adoptions red and dd_data has flagged him `Adoption? YES` since July.
There is no hardcoded list any more: `adoptions_on_tab` reads the red fill back
off the tab, because the tab is what people edit.

**Depth did not change and does not count the leader** — it answers "how many
owners in depth", not "how big is the org", so it stays `descendants − first
gen`. First Gen never excluded adoptions, so all three metrics now agree.

**The only thing that still takes anyone out of a count is a WEIGHT**, for one
case: Cody Cannon sits on the tree twice as `(1/2)`, counting 1 on Carlos's side
and 0 on Colten's, so the org-wide total holds him once. Eve's markup confirms
it — her Carlos box includes `Cody Cannon (1/2)`, her Colten circle stops just
above his second node.

WE 8.23.26, the figures this has to reproduce (they are the regression test):

| | First Gen | Total Org | how the total is built |
|---|---|---|---|
| Rafael | 9 | **48** | 50 under him − 3 adoptions + himself |
| Colten | 8 | **17** | 16 under him, adoptions in, + himself |
| Carlos | 10 | **22** | 21 under him + himself |

### The `Lucy Org Tree` mirror block, and a header that parsed as people

The top block of `Lucy Org Tree` (rows 5-57, "Tree Name / Reports To / Gen / DD
Sheet Name / Match status") is a hand-kept mirror of the `Org Tree` tab. **Nothing
in the code reads it** — it is there so a person can see, in one place, who is on
the tree and whether they have a DD row. It drifts silently for exactly that
reason. Brought back in step 2026-08-27:

- **Raul Sosa Puerta and Carl Foss** were on the tree under Jairo and missing
  here entirely; added at the end of the block, both `NO DD ROW`.
- **Salik Malick** still said `NO DD ROW`. His row exists and is called **Salik
  Waqar** — the ICD Aliases tab already resolved it, so only this block was
  stale. Col D now carries the DD spelling.
- The summary line under the block is recounted and dated.

**And a real trap found on the way.** The Org Tree's first row is
`Generation | 1 | 2 | 3 | 4`. `_parse_tree` skipped "Generation" (it is in
`_LEGEND`) but not the column numbers, so `1`, `2`, `3` and `4` parsed as four
people and built a `1 -> 2 -> 3 -> 4` chain of their own. **No published figure
was ever wrong** — that chain's root has no parent, so it never sat inside
anyone's org, and 48 / 17 / 22 are identical before and after. But it was one
re-ordered row away from adopting a real Gen-1 name onto a header cell. A bare
number is now never a person.

### The `Adoption?` column and the ORGANIC figure (Raf, 2026-07-24 14:36)
On the bulletin thread, Eve asked whether Jairo could be added. Raf:

> "Yeah we can add him. **Justin is an adoption, not organic.** Lets the same
> thing like Colten where we have organic DD row."

So `PODIUM ORG LISTS` has an **`Adoption?`** column. A `YES` row still counts
toward that leader's **TOTAL** but is excluded from their **ORGANIC** figure,
which renders under the big number on the card:

| Leader | Total | Organic | Adoption(s) |
|---|---|---|---|
| Colten Wright | $431,124.00 | **$390,637.00** | Justin Fermin, Karrington + Milan |
| Jairo Ruiz | $176,559.00 | **$163,471.00** | Justin Fermin |

**Justin Fermin counts to BOTH Jairo and Colten.** He sits under Jairo in the
tree, so Jairo receives the double override — and Colten's org contains Jairo's.
Podium figures overlap by design, so both is correct, not a double-count bug.
Colten's $431,124 still reconciles to the VA's published figure exactly: the flag
changes what we can SHOW, not what we count.

**Jairo Ruiz is on the podium** as of 2026-07-24. His `Expected week DD` is
deliberately BLANK — there is no published figure to check him against yet, and
inventing one would fake the check that protects every other leader.

**His list is confirmed by Jairo himself**, which is a better source than our
reconstruction. Asking for the column (2026-07-24 11:56, on the bulletin thread):
*"Hey guys can we add my name on a column. with: Myself / Drew Tepper / Frank
Matos / Justin Fermin."* That is exactly the four rows on `PODIUM ORG LISTS`, in
that order. So while his money is unchecked, his membership is not.

## CREDICO — a real second source

Direct deposits from Credico must be ADDED to each owner's weekly number.

### WIRED IN 2026-07-24 — `dd_data._fold_credico`
`load()` takes `credico="auto"` and pulls the week's Credico figures before the
podium is summed, so a topped-up week reaches the leader lists that add it up.

**The tab decides, per owner, whether to add or to verify.** While the VA still
fills `Org DDs Ongoing Report` she has ALREADY folded Credico in — Abel's 7.19.26
cell is $6,578.00 against a $6,058.00 Credico office. Adding on top of that would
double-count her work, so:

| Tab cell vs Credico | What happens |
|---|---|
| cell **>=** Credico | Already folded in. The split is printed on page 2 ("$6,578.00 already includes Credico $6,058.00 (Tableau part $520.00)"). Nothing changes. |
| cell **<** Credico | The cell is the Tableau part only → **ADD**. **BLOCKING**, because the headline is read off the tab and does not contain what we just added. |
| **no row at all** | A Credico-only owner. Rendered under **Tracked Separately**, never folded into a total that lacks them. **BLOCKING**. |

Both real offices verify clean against 7.19.26, reproducing the $520.00 / $90.00
Tableau parts this doc already recorded.

`credico.report.pull()` returns **office totals keyed by owner NAME**, not the
per-agent split — the per-agent version scattered an office's money across
individual agents, which the VA tab disproved. It returns `(owners, notes,
offices)`; the caller keys the names through ICD Aliases with its own key
function, so a key built in the Credico module can never drift from the one the
DD tab is indexed by. `--week` on every Credico command now defaults to the
newest week on the DD tab instead of a hard-coded `7.19.26`.
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
- **Raf's line — THIS BULLET IS WRONG. REVERTED 2026-08-06** (see *SETTLED
  2026-08-06* above). The VA's $250,457.00 was right; our $292,419.00 was the
  error. Kept verbatim below because the reasoning is seductive and the next
  session will re-derive it unless it can see where it goes wrong: subtracting
  only what the headline contains is arithmetically sound and editorially wrong,
  and it makes Rafael immune to the adoption amounts. **Do not re-apply it.**

  Her sheet subtracts
  Colten's FULL list total, but $41,962.00 of that (Justin $13,088, Marcos
  $1,475, adoptions $27,399) belongs to people with no DD row, who were never in
  the $1,010,586.70 headline. You cannot subtract money the base never contained.
  Her $250,457.00 understates Raf by exactly that $41,962.00.

  *(2026-08-06: the headline NOW contains them, so the four are subtracted along
  with everyone else. The principle is unchanged — subtract exactly what the
  headline contains — and Raf's figure lands in the same place either way. See
  REVERSED 2026-08-06 above. The 7.19.26 worked example below still describes
  the old base and is kept as the derivation.)*

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
- **Justin Fermin and Marcos Barbosa (and Karrington + Milan) — SUPERSEDED.**
  This bullet used to read "no DD row at all… re-surfaced under Tracked
  Separately". All four now have rows in the `ICD (Special Cases)` block on the
  DD tab and, since 2026-08-06, count inside their leader's org figure (but not
  the headline) — see *SETTLED 2026-08-06* above. Their `Manual week DD` cells
  on `Lucy Org Tree` (C85/C86/C121/C122) are
  now DEAD: a real row always wins in `by_key`, so those cells still hold the
  7.19.26 figures and nothing reads them. Do not "fix" them and expect the page
  to move — edit the DD tab's special block instead.
- Eveliz is Colten's wife — location **Miami, Florida** (not Michigan).
- Leaders seen: Colten, Carlos, Raf, Khalil, Zach, Eveliz, Salik, Hammad,
  Benjamin Burden (the count varies by week; 7.19.26 showed 7). Zach Hogue is
  Active NO with $0 this week, which is why he is off this week's podium.

Podium totals OVERLAP by design (a larger org contains smaller ones), so they sum
to MORE than the org total.

### THE VA'S WORKING FILE — SEEN 2026-07-24. The lists are no longer blind.
Megan shared a screenshot of the file this doc kept saying we did not have: one
small table per leader, every ICD with that week's wire, ranked, with a Total (and
an Organic total for Colten). **Our reconstruction was right.** Reconciled name
for name: Colten (14), Khalil (3), Eveliz (3), Salik (2), Hammad (2) are
**identical**, and every total matches to the cent.

What it settled outright:
- **The per-person adoption split**: Karrington Moody **$20,206** + Milan Godbolt
  **$7,193** = the $27,399 we carried as one combined line. Now two real rows.
- **Marcos Barbosa is non-organic too.** Her `Colten's Organic Total` of
  $389,162.00 only lands if Marcos comes out alongside Justin and the two
  adoptions — $41,962.00 in all. He is flagged `Adoption? YES` and Colten's
  organic now matches her file exactly (it was $390,637.00, $1,475 high).
- **Raf's org is all 38 ICDs earning that week**, totalling the headline. That is
  why his breakdown is derived rather than transcribed.

### CORRECTION — Carlos's 19 names against the bulletin's 18
**An earlier session (2026-07-24, this doc) concluded "it is Benjamin Burden" by
elimination against four weeks of published figures. That conclusion was reached
from a false premise and is wrong.** The reasoning assumed each leader's list is
FIXED and that dropping a member must break some week. It isn't fixed: **the VA
rebuilds every org list weekly from whoever has revenue coming in** (Megan,
2026-07-24: "anyone in khalil's org that has rev coming in is active and that's
the count"). Her Carlos table for 7.19.26 omits **both** David Martinez and
Benjamin Burden, because both earned $0 that week.

Her own label reads `ICDs-18` above **17** rows — the row numbering skips 8. So
the count we were chasing was miscounted at the source, and the money was never
in question.

Practical consequence, now implemented: the org breakdown lists only ICDs that
EARNED this week, which is what makes our tables name-for-name identical to hers.
The $0 owners stay on the podium list itself so nothing is lost from the source
of truth — they simply do not appear in a week they earned nothing.

**Also learned: only the CURRENT week reconciles to the published figure.** The
three prior weeks sit $1,402–$2,497 BELOW what was sent, in the same direction
every time — DD keeps settling downward after the bulletin goes out (the override
backtrack sees the same drift on the VA's own columns). So a sent bulletin is a
snapshot, not an answer key for a week that has moved since; `expected_week` is
only ever checked against the newest week, which is correct.

### Still open on the podium — needs the VA's WORKING FILE, not the email
Neither affects a published weekly figure; both are flagged every run.
1. The **adoptions are one line worth $27,399 combined**; the per-person split is
   derived, not read. Not rendered per person.
2. **No 2026 totals** for Justin, Marcos or the adoptions. This one DOES show:
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

## THE REVIEW GATE — `review_gate.py` (built 2026-08-06). EVELYN ONLY.

Nothing mails itself any more. `deploy/dd_bulletin_thu.sh` now runs
`--post` → `--check --send` → `--remind` on every Thursday pass, so the week's
PDF goes to Drive and its link to `#revision-emails`, and the send waits for a
checkmark.

**Only Evelyn's checkmark releases it** (Eve 2026-08-06: *"que la unica
aprobadora para este bulletin sea Evelyn, que si reacciona Jolie no dispare
nada"*). It was the first of the four gates in that channel to drop the
Evelyn+Jolie pair; the other three followed on 2026-08-13 when Jolie left the
company, so every gate now holds this one id and a tick from anyone else falls
through.

Three differences from the daily gates, all deliberate:
- **Weekly key.** The post is titled `Organization Bulletin — WE 8.2.26`, so
  `--post` is IDEMPOTENT: the agent makes seven passes and must not post seven
  times. Corrections go out with `--refresh` (same link, no second message);
  `--repost` replaces the message and refuses over an approval.
- **It HOLDS rather than posts** while the tab's newest week is not the Sunday
  that just ended. Exit 0 — Eve has until 10am Central to fill the column, and
  posting early would put the wrong week in front of the approver.
- **Blocking problems do not stop the post**, they ride in it. `send.py` refuses
  the send regardless, so the checkmark cannot release a figure we know is
  wrong — but the bulletin's absence is visible instead of silent.

The reviewed PDF and the mailed email are built TWICE (`send.py --dd` rebuilds
from the live Sheet), so the thread confirmation names the week AND the headline
that actually went out. See [[project_captainship-reviewed-pdf-vs-sent-eml]].

## SENDING IT — `send.py --dd` (built 2026-07-24, NEVER auto-sends)

The DD bulletin publishes through the SAME module as the override bulletin, not
a rival sender. `--dd` switches artwork, rooms and state file:

    python -m automations.override_bulletin.send --dd              # DRY RUN
    python -m automations.override_bulletin.send --dd --preview    # Megan only
    python -m automations.override_bulletin.send --dd --send       # the real distro

- **Slack**: `#alphalete-sales` (C068PH3RFSM), `#alphalete-lvl1-chat`
  (C09JG28CD27), `#rafs-office-recruiting` (C06881A7WLV, retired),
  `#rafs-office-recruiting-11280` (C0AUAS88FGW, added
  2026-08-20) — every id resolved
  against the workspace 2026-07-24, not copied from this doc. Both pages go up as
  ONE message per channel (`file_uploads`); two posts in a row read as two
  bulletins.
- **Email**: `Alphalete Org Owners` + `Bulletins` (63 addresses), subject
  **`Alphalete Organization Bulletin WE 7.19`**, both pages as inline `cid:`
  images. PNG over `data:` URIs because Gmail strips those.
- **Idempotency**: its own `dd_bulletin_last_sent.txt`, so publishing one
  bulletin never marks the other as done.

**What stops a send.** `dd_data.load()` now returns `blocking` alongside
`problems` — the subset meaning a number ON THE PAGE is wrong rather than merely
incomplete:

| Blocks a send | Prints and still publishes |
|---|---|
| a leader off their published figure by >$0.50 | a missing 2026 total (card says "partial") |
| Raf's two routes disagreeing | Carlos's 19-vs-18 ICD count (money is right, count is rendered nowhere) |
| a podium list with no ICDs, or an ICD with no amount | |
| Credico not folded in, added, or owner-less | |

`--send` refuses while any of those stand; a dry run and `--preview` still build
and show the pages, because looking at a broken one is how it gets fixed.
`--force` publishes anyway and says so. `--dd --no-credico` reads the tab as it
stands, for diagnosis only.

## The Hub card

`dd-bulletin`, sitting directly before the Override Bulletin card (Thursday
before Friday). Four buttons: **Build Both Pages**, **Preview the Send (no
send)**, **Check the Numbers Only**, **Get This Week's Credico**. Rerun ids
`dd_bulletin` / `dd_bulletin_send` in `day_orchestrator/schedule_config.json`,
both `on_scheduler: false` and both on **Lucy 1** — that is where the Credico
workbooks land. Run `lucy rerun credico_fetch` before the build, or Credico
reports as not folded in and the send is refused.

## ACTIVE OWNERS — the rule, and three VA-formula bugs fixed (2026-07-24)

The Active-Owners block on `Org DDs Ongoing Report` is the VA's own COUNTIFS
block (we read it, never recompute in the bulletin). Rigorous review with Megan
found its weekly formulas counted `"<>"&""` (any NON-BLANK cell), which counts a
`$0.00` entry — so a terminated/inactive owner who sold nothing still counted.

**The rule Megan settled on: an active owner = `Active ICD = YES` AND revenue > 0
that week.** Every weekly formula is now
`=COUNTIFS($D$2:$D$131,"<org>",$B$2:$B$131,"YES",<week>$2:<week>$131,">0")`
(campaign rows key `$C` instead of `$D`; the Total row drops the org/campaign
criterion). This excludes inactive owners in EVERY week and still reflects who
actually sold, so real week-to-week movement is preserved (Carlos 10/11/11/9, JE
Retail 4/5/5/3). Note `">0"` alone was WRONG — it counted an inactive owner in
the weeks they DID earn before going inactive (Kevin Driggs showed 4 in prior
weeks); the `Active=YES` AND `>0` pair is what excludes them entirely.

Three PRE-EXISTING typos in the VA's formulas, fixed on the live tab:
- **Khalil's Org 2026 (E)** keyed `"David"` (no such org) → returned 0. → `"Khalil"`.
- **Colten's Org 2026 (E)** used range `$D3:$D132` (off by one) → 6 instead of 7.
- **Benjamin's Org (all cols)** keyed `"Salik"` — so Salik was double-counted and
  Ben's org (Roshan, Abel, Jahvid) counted nowhere. → `"Ben"`.

VERIFIED after the fixes: the org rows SUM to the Total row in every displayed
week ([38,38,39,37]), Khalil reads 3/3/3/3 (Kevin Driggs, Active=NO, excluded),
and no row trips the impossible-total red flag. If the VA ever re-copies these
formulas the bugs can return — re-check against this note.

## Presentation

The OneDrive `Org. Bulletin.xlsx` and BeeFree are **formatting only** (Megan:
"just used to make it look pretty") — both are replaced by rendering the branded
layout ourselves. The VA's Slack image is a crop of just the tables, enlarged in
Paint, because a screenshot of the whole email is unreadable — our render should
make that crop unnecessary.

Footer: **"Learn More. Dream More. Do More."** The org-leader blurb was REMOVED
(Megan 2026-07-24).

### Layout, as Megan reviewed it live 2026-07-24
Reviewed page by page in a browser preview; the render changed a lot. Current shape:
- **Page 1**: headline → top-5 photo cards (org leaders, gold `#1..#5` top-left) →
  the per-leader **org breakdowns** directly under them (masonry, biggest org
  first), then the `* adoption` key bottom-right. Cards carry name / location /
  week only — the 2026 total and organic lines were dropped (organic shows on the
  org card instead). Org card header shows `14 ICDs (10 ORG)` when adoptions are
  present.
- **Page 2**: **All ICDs** (every ICD we can pull, top 5 highlighted gold) →
  **Tracked Separately** (same fixed columns so they line up, ranked by the week)
  → **Credico** (only the pending warning; the populated table was dropped as
  redundant with the ICD list) → the merged **Avg DD + Active Owners** rollup
  (one row per org/campaign so the two line up; owners show the last 3 weeks and a
  count that ROSE from the prior week is green for that week only).
- **Adoptions**: a red `*`, never the word (Raf: "just a red *").
- Adoption membership is a manual `Adoption?` flag on `Lucy Org Tree` — Karrington,
  Milan, Justin are Raf's explicit calls; **Marcos is a reconciliation inference**
  (his flag makes Colten's organic land on $389,162), unconfirmed by Raf.
- **Salik fix (Raf confirmed a mistake, 2026-07-24)**: Salik was missing from his
  own org because his ICD row `Salik Waqar` sits under Raf on the tab. Added to his
  own list → $57,609 (3 ICDs incl. his own $9,342); still overlaps into Raf's org.

### Open question tooling — `dd_search.py` (Lucy 1)
Do the four bulletin-only names have weekly history in Tableau, or only the single
manual figure? `lucy rerun dd_name_search` downloads the ORG DD Detail crosstab,
searches it for Justin / Marcos / Karrington / Milan, and dumps the result to the
`_dd_search` tab (read-only). If found, they can be wired as excluded-but-tracked
rows and get full history like Jacob Dover; if not, the `—` is the honest thing.

### OUT 2026-09-03 — Marcos Barbosa and Milan Godbolt are off the page entirely

Eve, 2026-09-03: *"hay que sacar a marcos barbosa y milan godbolt del
bulletin."* The two removals above (both 2026-08-27) only took them off
`Lucy Org Tree` — out of Colten's podium list and out of the `Org Tree` node
grid. Their hand-typed rows in the DD tab's **`ICD (Special Cases)`** block were
left alone on purpose, and those rows are what kept printing them under
**Tracked Separately** every week since ($0.00 for both on 8.30.26).

**This one IS in code**, unlike the two before it: `dd_data.RETIRED_SPECIAL`
names them and `load()` skips those rows while parsing the block. The rows stay
on the tab — that block is Eve's own weekly typing and the only place their DD
history lives, and blanking column A there would *truncate the block at that
row* (`load` ends it at the first blank name), silently dropping Karrington and
Justin too. To bring someone back, take the name out of the tuple; nothing on
the Sheet changes either way.

It is their whole presence on the page: neither is in a podium list any more,
neither is an `Active ICD` YES row, and the headline / AVG DD / Active Owners
never contained them. Measured on WE 8.30.26, before and after:

- **Tracked Separately: 4 rows → 2** (Karrington Moody, Justin Fermin).
- **ORG. TOTAL DD unchanged** at $1,107,071.55, and every podium figure
  unchanged — both rows were $0.00 this week, and the special block sits outside
  the headline anyway. In a week where Marcos has a figure it would move Colten
  down and Rafael up by that amount, the same arithmetic as the 08-27 note.
- The "special rows carry $X MORE" note now reads **2 rows / $22,550.00**.
- `dd_search.py` `TARGETS` still names all four — that is the one-shot July
  diagnostic, not a live report.

### The review link carries THREE pages (2026-09-03)

Eve, same day: *"quiero que empieces a incluir el preview de Up and coming NCs
and RCs en el link del bulletin."* `review_gate.build_preview` now appends
`rcs_ncs_build.build()` to the two bulletin pages, so the PDF behind the
#revision-emails link is bulletin p1 → bulletin p2 → the companion infographic,
and Evelyn approves everything that goes out from one link.

- **Nothing about the SEND changed.** The companion is still a separate email
  fired by `send_companion` after the DD send, to the same distro rule; the
  bulletin email still carries its own two pages. This only widened what gets
  reviewed.
- The companion page is **best-effort**: it reads a second tab (`Org Tree`), and
  a failure there prints, lands in `problems`, and leaves a 2-page PDF. It never
  reaches `blocking`/`hard_block` — the page carries no money.
- `build_pdf` now takes each sheet's width from `document.body.scrollWidth`
  instead of a fixed 1180px: the companion body is 1000px and printing it at
  1180 left a white strip down the side (the dark background is painted on
  `<body>`, not on `<html>`). The bulletin pages measure 1180 and are unchanged.
- It reuses the `dd_data.load()` result already in hand — no second read of the
  DD tab, which is what the 60-reads-a-minute ceiling cares about.
