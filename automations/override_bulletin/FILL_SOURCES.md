# Override Bulletin — fill source map

How each Friday's numbers get into the `Org Overrides Ongoing Report` tab.
Reverse-engineered from the VA's Loom (2026-07-22) + Megan's walkthrough, and
**every number below was cross-checked to the dollar against the current sheet.**

## Runs on Lucy 1 (Raf's login)

These are Raf's **ORG** views — he sits above the other captains in the downline,
so only Raf's login sees the whole org. Lucy 1 = Raf. The render (`build.py`)
only reads Google Sheets, but the number PULLS need Raf's Tableau/ownerville
session → Lucy 1 (shares the session with the other Lucy 1 reports; don't scrape
from the laptop, it evicts the holder).

Custom views are per-account, so a saved view made on another login may not
resolve under Raf's — apply the filters fresh each run instead of relying on it.

## Who to fill (sheet-driven, no exclusion list)

The **sheet roster is truth.** Fill each row in the ALL ORG section where
**Active ICD (col B) = YES**, matched by normalized name to the source. NO rows
stay $0; names not on the sheet are ignored. This already encodes the VA's
"in a captainship but not an owner → exclude" rule (those people are NO / absent).
**A YES row that can't be matched in the source is reported on the email summary,
never silently zeroed.**

## The numbers

Each active person's weekly cell (section 1) = `regular + captain/special`. The
captain/special piece comes from section 2 (its `=SUM()` rows feed section 1).

| Piece | Source | Extract |
|---|---|---|
| **Regular override** | Tableau `OverridesICDView/ORGOVERRIDESUMMARY` | select the **highest Period** (dropdown, changes monthly); per owner, **sum all their campaign rows** in the target week's column. Downloaded crosstab groups an owner's rows under their name (blank col A = continuation). Watch number locale ($72.253,17). |
| **Raf Captain Override** | Google Sheet `All in One Local Office - Raf` → tab `Raf PNL 2026`, **row 335 "Captain Override"** | value in the target week's WE block, **Profit/Loss column (WE-header col + 2)**. Verified 7/12 = $18,067, 7/5 = $20,068. |
| **Raf Special Override** | Tableau `ResATTSpecialDealOverride-Raf/RafOverrideBonus` | select highest Period; read the **"Raf Payout Total"** summary row for the target Processed Week. Verified 7/12 = $39,522, 7/5 = $26,950. |
| **Other Captain Overrides** (Carlos, Colten, Khalil, Jairo, Eveliz) | Tableau `DirectDepositICDVIEWVersion2_0/DDDETAILORG` | filter **Downline or Captain = Downline**, **cl.ICD Owner Name = captain**; in **cl.DD Week** take the target week; sum **Total $ to ICD** on **"Captain's Bonus"** rows only (exclude chargebacks/other B2B Bonus). Verified Carlos DD-week 7/11 = $10,875. |
| **Carlos/Colten Special Override** | Tableau `OverridesICDView/NETSUITESECURITYLEDGERSFDC` (Megan's custom view **CarlosColtenSpecial**) | owner = Carlos/Colten, **NS_Explanation contains "Special Override"**; the explanation carries the **period** (P#-2026). Read **Transaction Amount** for the target period. ~every 4 weeks. |
| **Credico override** | same NETSUITE SECURITY LEDGER (Megan's custom view **Credico**), **NS_Explanation "credico"** | rows read **"[Month] [Year] Standard Overrides - Credico"** (month-labeled, NOT a P#-period like Special) + owner; read **Transaction Amount**. Placed on the month's **last week ending**. Runs badly behind (snapshot 2026-07 showed latest = **January 2026**), so recent months are usually pending → red marker. Excluded people appear in the ledger but are filtered out by Active-ICD=YES. Added into the section-1 regular component. |

Custom-view URLs (may not resolve under Raf's login — filter fresh if not):
- Special: `.../NETSUITESECURITYLEDGERSFDC/0212de10-2d7f-4281-b0d5-d048361251a9/CarlosColtenSpecial`
- Credico: `.../NETSUITESECURITYLEDGERSFDC/3e5cabd4-1c72-493f-9440-83bdc49d057e/Credico`

## CONFIRMED on Lucy 1 (2026-07-23) — the pull mechanics

| Source | Sheet name | Period/week selection | Status |
|---|---|---|---|
| Regular override | **`ORG Override Summary`** | URL `?Period=Period 2026-7` (**year-prefixed**; bare `Period 7` returns NO sheets) | parse ✅ |
| Raf special | `Payout- Raf wow` | URL `?Period=Period 7` (**bare**; `Period 2026-7` fails here) | ✅ **7/12=$39,522, 7/5=$26,950** |
| Other captains (DD) | `ORG DD Detail` | **no filter** — default download IS the just-closed week; URL week-filters BREAK the view | parse ✅ (7.18: Carlos $9,545, Eveliz $2,500, Raf $16,740) |
| Special / Credico | `Transaction Details` | no filter; needle carries the period/month | parse ✅ |

Note the two views take **different Period formats** — don't unify them.

### Gotchas that cost real debugging time

1. **`ORG DD Detail` is a HIERARCHICAL crosstab.** Empty dimensions collapse per
   row, so **columns do NOT align to the header** — the amount lands at a
   different index on every row, and `cl.Description` isn't a header column at
   all. Header-index parsing returns EMPTY. `parse_dd_captain` matches by
   **content**: a `Captain('s) Bonus M.D.YY` cell + an owner in the captain set +
   **max money cell** = Total $ to ICD. Don't "fix" it back to column lookup.
2. **ORG summary week headers are zero-padded** (`07/12/2026`) and the real header
   sits under **two banner rows**. `_wk_norm` compares dates, not strings.
3. **Sources are staggered mid-week.** On 2026-07-23, DD was already at 7.18 while
   the ORG summary's latest week was 07/12. They align on the Friday run (all hold
   the just-closed week). A week a source doesn't have is **reported, never
   filled from a neighbouring week** (`_dd_week_for` returns None → unmatched).
4. **Sheet Sunday ↔ DD day-behind**: sheet `7.19` ↔ DD `7.18` (real date math, so
   month edges work).

### Name matching goes through the ICD Aliases sheet

The sheet roster and Tableau spell people differently. BOTH sides resolve through
the shared 'ICD Aliases' tab (`fill.canon` / `fill.rekey`) and match on the
canonical — never patch a name in this report. Confirmed 2026-07-23:
`Muhammad Hammad Ul Haque` (roster) and `HAMMAD HAQUE` (Tableau) both resolve to
`Hammad Haque`; before wiring this he was silently blank on the bulletin.
Two roster spellings were missing and were ADDED to the alias tab:
`Boaktear Chowhury`→`Boaktear Chowdhury` (roster drops the 'd') and
`Muhammad Salik Waqar`→`Salik Mallick`.

Result for week 7/12: **16 of 21 actives matched**. The other 5 (Abel Draper,
Cinthya Reyes, Jacob Dover, Roshan Ahmad, Valeria Tristan) are genuinely absent
from the regular-override source that week → they go on the email summary as
unfilled, never $0.

## Discovered crosstab sheets + columns (Lucy 1 discovery, 2026-07-23)

Confirmed via `discover.py` → `_discover_out` tab. Parsers match columns BY NAME.
- **RAF_OVERRIDE_BONUS** — sheet **`Payout- Raf wow`**: r0 'Processed Week' span,
  r1 = week dates, r5 = 'Raf Payout Total' row. (Default download shows OLD weeks
  — needs the Period set to the highest.)
- **DD_DETAIL_ORG** — sheet **`ORG DD Detail`** (~10.7k rows): cols include
  `cl.ICD Owner Name`, `cl.DD Week`, `cl.Description`, `Total $ to ICD`. Owner
  name repeats on every row (not grouped). r1 is a 'Grand Total to ICD' row.
- **NETSUITE_SECURITY_LEDGER** — sheet **`Transaction Details`** (~6.1k rows):
  `ICD Owner Name and OFFICE NAME` (col0, "Owner (Office)"), `NS_Explanation__c`,
  `Transaction Amount`. r1 is a per-owner 'Total' row (skip).
- **ORG_OVERRIDE_SUMMARY** — list_crosstab_sheets returns **0** even with longer
  settle; the default download fails. OPEN: probably a dashboard whose crosstab
  only exists once a Period is selected — try selecting the highest Period first,
  or download the named worksheet ('Consultant (+/-) Campaign') directly.

Tableau crosstabs are **UTF-16 tab-separated** — use pulls.read_crosstab().
All these need the PERIOD/week driven before export (default = oldest weeks).

## Week / period conventions (gotchas)

- Sheet week label is **Sunday** (7.12.26). DD Detail's `cl.DD Week` runs a day
  behind — **7/11 ↔ sheet 7.12**. Override Summary's Processed Week matches the
  sheet (7/12). Align by matching the **last 4 weeks positionally**, not by the
  literal date string.
- **Backtrack the last 4 weeks every run** — prior weeks shift slightly as
  sources update. Re-read and correct them, with a sum-matches-source check.
- Near month-end a week can appear in **two periods** (period N and N-1) — pull
  both and combine.

## Pending markers (P#-2026)

The special (Carlos/Colten, ~monthly) and Credico (last week of month) overrides
arrive late. The period marker on the sheet = the ledger's `NS_Explanation`
period. **If the period's row is in the ledger → write the amount; if not →
it's pending → leave the red `P#-2026` marker** and check again next week.
Exact target cells + period→week placement to be pinned during the build by
reconciling live pulls against the sheet.

### The week roll has TWO header rows, not one

Section 2 ("CAPTAIN/SPECIAL OVERRIDES ONLY") repeats the week headers over its
own block. To `scaffold.plan` that repeated label looked like a typed value, so
the roll CLEARED it — section 1 got the new week label and section 2's newest
column was left blank. Fixed 2026-07-23: any row repeating the newest label is
RELABELLED, not cleared (found by matching the label, never by row number).

### A bad fill must be CLEARED, not overwritten

`week_is_filled` gates the run, so a column holding a bad fill makes every later
pass hold on "already filled" and the week never gets its real numbers. Use:

    python -m automations.override_bulletin.run --tab "Copy of …" \
        --clear-week 7.19.26 --write

It blanks only the mapped cells (roster rows + captain/special sub-rows), leaving
the `=SUM` structure, the header and every other week untouched. Live tab refused.

## Verifying the numbers (verify.py)

Coverage ("16 of 21 actives matched") proves we found a ROW, not the right
NUMBER. `verify.py` pulls a week the VA already filled and diffs it cell-for-cell
against her column on the LIVE tab — read-only, writes nothing:

    python -m automations.override_bulletin.verify --week 7.12.26   # on Lucy 1

This is the only check that covers the CAPTAIN/SPECIAL rows, where a captain's
weekly figure is a SUM of several DD Captain's-Bonus lines (Eveliz 7.12 = the
VA's `=2576+540`), so a parser that grabs one line instead of the sum looks
perfectly healthy until the dollars are compared.

### Result, Lucy 1 2026-07-23 (week 7.12)

**Every source that exported matched the VA to the cent. No real disagreement.**

| Source | Verdict |
|---|---|
| ORG Override Summary (regular) | ✅ all 21 actives match exactly |
| Raf PNL Captain Override | ✅ $18,067 (and 7.5 = $20,068) |
| Raf Special Override | ⚠️ did not export |
| DD captain overrides | ⚠️ did not export |
| NetSuite ledger | no P7-2026 rows yet (still pending) |

22 cells compared, 16 matched, 6 "mismatched" — and every one of those 6 is off
by **exactly** the figure the dead source was supposed to supply: Raf −39,521.99
(his special), Colten −10,236.00, Carlos −10,874.99, Jairo −6,534.00, Khalil
−4,865.00, Eveliz −3,116.00 (their DD captain bonuses). Each person's regular
component matched to the cent underneath. So the two failures cost coverage, not
correctness.

**Both failures were the same symptom** — `Couldn't find the '<sheet>' sheet in
the Crosstab dialog — saw 0 thumb(s)` on `Payout- Raf wow` and `ORG DD Detail`,
while the ORG summary exported fine on both attempts. Someone was working ON the
mini at the time (see the Chrome-collision note): re-run verify when it's idle to
close out these two sources.

## Post-fill (already built / mapped)

Sort ALL ORG by Total 2026 desc, render the bulletin (`build.py`), then publish
with `send.py`. PNL-for-the-office posts right after (separate —
`automations/pnl_office`).

    python -m automations.override_bulletin.send             # DRY RUN (default)
    python -m automations.override_bulletin.send --preview   # email Megan only
    python -m automations.override_bulletin.send --send      # real distro

* **Slack** — the rendered PNG to `#alphalete-sales` (C068PH3RFSM) and
  `#rafs-office-recruiting` (C06881A7WLV), as Lucy (xoxp USER token via
  `slack_metrics_post._client()`). `OVERRIDE_BULLETIN_CHANNEL_ID` redirects BOTH
  to a scratch channel for a safe live test.
* **Email** — from alphaletereporting@ to the "Alphalete Org Owners" +
  "Bulletins" contact groups (63 addresses on 2026-07-23), subject
  "Alphalete Organization Override Bulletin WE m.d".
* **The email carries the PNG as one inline `cid:` image, not the bulletin
  HTML.** `build_html` embeds the logo and headshots as `data:` URIs — right for
  a local file and for the Slack render, but **Gmail strips `data:` image URIs
  from received mail**, so the HTML body would arrive as broken images.
* A missing contact group ABORTS the send rather than under-sending silently,
  and an unfilled week is refused outright.
* Sends are recorded per week (`~/.config/recruiting-report/override_bulletin_last_sent.txt`)
  so the 25-minute launchd retries can't double-post to the whole org.
