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
| **Credico override** | same NETSUITE SECURITY LEDGER (Megan's custom view **Credico**), **NS_Explanation "credico"** | last week of the month; runs behind, so often pending. Added into the section-1 regular component. |

Custom-view URLs (may not resolve under Raf's login — filter fresh if not):
- Special: `.../NETSUITESECURITYLEDGERSFDC/0212de10-2d7f-4281-b0d5-d048361251a9/CarlosColtenSpecial`
- Credico: `.../NETSUITESECURITYLEDGERSFDC/3e5cabd4-1c72-493f-9440-83bdc49d057e/Credico`

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

## Post-fill (already built / mapped)

Sort ALL ORG by Total 2026 desc, render the bulletin (`build.py`), post to
`#alphalete-sales` + `#rafs-office-recruiting`, email inline to the "Alphalete
Org Owners" + "Bulletins" groups from alphaletereporting@ (subject
"Alphalete Organization Override Bulletin WE m.d"). PNL-for-the-office posts
right after (separate — `automations/pnl_office`).
