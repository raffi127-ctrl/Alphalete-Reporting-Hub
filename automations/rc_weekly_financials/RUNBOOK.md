# R&C Weekly Financials — Friday runbook

Tabs: **Carlos' Finances** (Monthly PNL - Carlos' Accounts `1HYnm…`) and **Hidalgo's finances** (Monthly PNL - Raf's Accounts `1M2Vy…`).
New column = the coming Sunday (Friday 10/23 → `WE 10.25`). From `~/recruiting-report` with the Hub venv python.
Run the Friday ARS PNL check first — Raf's ARS rows read that week's ARS PNL.

```
python -m automations.rc_weekly_financials.run pull                # all sources -> output/rc_weekly_financials/values_<we>.json  (outside the sandbox: Tableau)
python -m automations.rc_weekly_financials.run fill --who carlos --dry-run
python -m automations.rc_weekly_financials.run fill --who carlos
python -m automations.rc_weekly_financials.run fill --who raf --set "Indeed=-14471.90" --prior "Indeed=-14454.06"
python -m automations.rc_weekly_financials.run shot --who raf      # PNG: labels + 4 newest weeks
```
Test run: `dup --who X` makes `<tab> (TEST WE M.D)`, then add `--tab "<that name>"` to fill/shot.
Re-running fill for a week that already has its column refreshes it in place (no second column).

## Where each number comes from

| Carlos row | Source |
|---|---|
| Maud | 0 from now on |
| Local Office Profits (week prior) | Vantura Master Sales Board → P&L 2026 → "Total Gross Profit (no captain)", WE one week back |
| Captainship (week prior) | same tab → "Captainship Bonus", WE one week back |
| Overrides | 0 for the new week; Tableau ORG Override Summary (Carlos) fills last week + refreshes the week before |
| Total CC Debt | −(Business CC 44K + Business CC 2 + Personal CC + Amex + BOFA + Capital) from Carlos's Tiller |
| Money in the Bank | Alphalete Marketing + Personal + Personal Savings (Tiller) |
| Money in Security | Tableau SFDC Total Balance |
| Personal Pay, NPA - Owner's Draw, Nico's / Sebastian's / Cinthya's Bonus | Apex, via the Thursday `carlos_payroll_pull` → Carlos Business & Personal P&L (`1ngQt…`) tab **Apex Net Pay Detail**, pay period ending one week before the WE: Personal Pay = −(owner gross × 1.12), NPA = −(owner net-pay additions), bonus = −(Nicolas Murrugarra / Sebastian Avellaneda / Cinthya Reyes net-pay addition). No Apex login (Apex forces a 2FA setup screen). Maud's Bonus kept. |
| Indeed Charges, Outside Deals, ARS (−850), Rent, Food, Travel, Investment into local office | Carlos's month tab (e.g. "September 2026"), the week one back: Indeed/Food/Travel from the summary block, Outside Deal + CARLOS ONLY Weekly from the bottom table; Investment = −(Carlos-only − travel − indeed − 850 − rent); Rent = Carlos-only "Online ACH Payment" ≥ $5k that week (flagged to confirm). If that week isn't finished in the month tab, last week's placeholders stay + a NOTE |

| Raf row | Source |
|---|---|
| Support Staff Bonus (Maud, Twaddle) | **manual** — Slack Dylan↔Raf "captainship" bonus, WE two weeks back |
| Indeed | Double Entry (financial_report web_source) — new WE S = DE week ending Sat S−8, last week's column = S−15. Needs `doubleentry_username/password` in the gitignored `ownerville-creds.json` + the OTP inbox on this Mac; otherwise **manual** from the Tue email (`--set` / `--prior`) |
| Recruiting Bonuses (Aisha) | **manual** (Apex) |
| Zach's Pay (overrides / true up) | **manual** (Slack Raf↔Zach) |
| ARS (PNL Shows) | All in One - ARS → ARS PNL → Gross Profit, SAME week |
| Captainship | Tableau ORG DD Detail → Captain Bonus (Raf), DD week = Saturday before the WE (Maud confirmed 2026-10-22) |
| Local Office Gross Profits | All in One Raf → RAF PNL 2026 (NEW) → "Raf's Net Profit from Local Office", week back |
| NC over rides | 0 new week; Tableau ORG Override Summary (Raf) fills last week + refreshes the week before |
| ATT Program over ride | 0 new week; Tableau Raf Override Bonus ("Raf Payout Total") fills last week + the week before |
| Bas Overrides | 0 (one lands every 4 weeks — check) |
| Money Given for Interviewers | −ARS PNL "Raf covers", same week |
| Total CC Debt | −(5 Chase CCs + BOFA - LTD + AMEX - Local Office CC) from Raf's Tiller |
| Money in the Bank | Chase total minus ARS = Local Office + LTD + Personal + Personal Savings + STR Carrollton |
| Money in Security | Tableau SFDC Total Balance |
| Kia / Lambo | Raf sheet → Running TOTALS 2026 → loan tables, last "Money Owed left" |

## Slack
- Raf's PNG → **Maud first** to double-check; Maud sends to Raf + Megan.
- Carlos's PNG → Carlos + Raf.
Confirm before sending.
