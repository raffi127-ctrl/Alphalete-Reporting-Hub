# R&C Weekly Bank Account Totals — Monday runbook

Sheets (tab **Weekly Totals 24-26**):
- Carlos: Monthly PNL - Carlos' Accounts — `1HYnmAVCZn6LaWgXEPZItCB9E2bMdXFBxBwbXorkScm8`
- Raf: Monthly PNL - Raf's Accounts — `1M2Vy2qo3N1AND1tVuKugtT_FizYw_6lBD3t2tcRLFYg`

From `~/recruiting-report`: `python -m automations.rc_bank_totals.run <cmd>` with the Hub venv's python. JSON + PNG outputs go to `output/rc_bank_totals/` (git-ignored).

## 1. Add the new week column (both sheets)
`run add --who carlos` and `--who raf` (header = yesterday's Sunday; `--dry-run` first).

## 2. Collect numbers → `carlos_<date>.json` / `raf_<date>.json` (keys = row labels)

**Carlos:** `run tiller --who carlos` writes every bank/card row from his Tiller sheet (no bank logins).
 Rows it flags MISSING or stale → check in that bank.
**Both:** `run tableau` adds Business Security (Hub's Tableau session) to both JSONs .
**Raf payout:** `run payout` sums the "Payout toward CC" table (Q45 down, same tab) for last Mon–Sun → `Payout toward CC` (0 if nothing paid).
**Raf:** no Tiller yet, so his bank rows still come from the bank sites (the table below).

| Row (Carlos) | Source |
|---|---|
| Business Security | Tableau → Overrides ICD View → NetSuite Security Ledger SFDC → SFDC Total Balance |
| Alphalete Marketing | Chase — "Affiliate Marketing" |
| Personal / Personal Savings | Chase |
| Business CC (44K) | Chase CC …7643 |
| Business CC 2 (6K) | Chase CC …0021 |
| Personal CC (17.3K) | Chase Freedom Unlimited …3455 |
| Amex | Amex total |
| BOFA (20K) | Bank of America |
| Capital | Capital One |
| Raf Debt / Idea Loan | carried over automatically |

| Row (Raf) | Source |
|---|---|
| Business Security | Tableau Security Ledger (Raf's balance) |
| Payout toward CC | Payout toward CC table (Q:S) — payments dated last Mon–Sun, else 0 |
| Local Office | Chase "Local Office" …1096 |
| LTD / Personal / Personal Savings | Chase |
| STR Carrollton | Chase |
| ARS | Chase |
| 5289 / 1909 / 5719 / 0586 / 6468 CC rows | Chase credit cards by last 4 |
| AMEX - Local Office CC | Amex total |
| BOFA - LTD (20K) | Bank of America |

## 3. Fill + check
`run fill --who carlos --values carlos_<date>.json` (prints each cell, flags anything left blank).

## 4. Screenshot + Slack
`run shot --who carlos` → PNG of the header + last 4 weeks.
- Carlos's PNG → Carlos + Maud
- Raf's PNG → Raf + Megan + Maud
