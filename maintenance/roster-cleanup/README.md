# Country Stats + Recruiting roster cleanup (2026-06-19)

One-off maintenance: rebuilt the rep rosters on the **Country Stats** and
**Recruiting** tabs of the *ATT Program - Focus Report* workbook
(`1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE`) — dropped deleted-tab `#REF!`
rows, added live rep tabs, and re-anchored every metric formula with an
`IFERROR(LET(... ISNUMBER ...))` guard so each cell returns a number or blank
(never an error/text).

## Re-runnable apply scripts
Run from repo root with the venv, e.g.
`PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe maintenance/roster-cleanup/<script>.py`

- `country_stats_apply.py` — first Country Stats rebuild (50-row roster, label-anchored template).
- `country_stats_fix2.py` — wrap every Country Stats metric cell in the LET+ISNUMBER guard.
- `country_stats_raf_extend.py` — Raf Hidalgo: widen his bespoke ranges to `$ZZ$` + guard.
- `recruiting_apply.py` — Recruiting rebuild (per-row funnel template + guard; Raf bespoke widened).

## Backups (revert path)
`*_backup_*.json` are `A1:R53` / `A1:P60` snapshots in **FORMULA** mode taken
right before each write. To revert, write the JSON grid back to the same range
with `value_input_option="USER_ENTERED"`.

## Note — Sheets write protection
The **Recruiting** tab has a hard protected range on rows 4–53. Writes 400
("protected cell") unless the bot's Google Sheets account is a range editor.
That account is **alphaletereporting@gmail.com** (NOT raffi127@gmail.com — that's
the Tableau login). If a protection reappears, grant that account editor on the
range (or remove the protection) and re-run.
