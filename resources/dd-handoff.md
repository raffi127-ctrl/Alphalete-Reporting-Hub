# Handoff — Direct Deposit correction (ATT Program - Focus Report)

You're picking up work in the **Alphalete Reporting Hub** repo at
`/Users/megan/1st Claude Folder`. Read `CLAUDE.md` first — its rules override defaults.

## The task (two parts, both Direct Deposit = "DD")
1. **DMari Longmire tab — DD not filling at all.** Find out why and fix it.
2. **Correct the DD amounts for WE 5/24 and WE 5/31 on EVERY tab** of the ATT
   Program - Focus Report (the current amounts for those two weeks are wrong).

## Where DD comes from (cite this; do NOT use the financial uploads)
DD is pulled from **Tableau**, not the financial xlsx uploads.
- Raf report: `automations/recruiting_report/opt_phase.py` — "Program Summary
  (Direct Deposit)" from the **PROGRAM SUMMARY view (CAPTAINVIEW custom view)**,
  scraped via Tableau **Download → Data → "View Data"**. DD per ICD = the sum of
  that view. Queued as metric **"Direct Deposit"** at `opt_phase.py:1695-1698`
  (`_queue(om_rows, "Direct Deposit", round(ps_row["total"], 2))`). View intro
  comment at `opt_phase.py:150-152`.
- Week is pinned via the view's **"Processed Week" filter** — see
  `opt_phase_carlos.py:604` (`Pin the Direct Deposit view to a week…`). Carlos
  variant: row 51 = "Direct Deposit", "Direct Deposit ICD VIEW v2.0"
  (`opt_phase_carlos.py:284,332`).
- Org/other campaigns use the org-wide DD view `ORG_DD_URL` (e.g.
  `automations/alphalete_org_report/opt_box.py:52,248-251`). Memory calls it the
  **"DD BY OWNER (ORG)"** org-wide view.

## Sheet / how to run
- ATT Program - Focus Report (Raf) sheet id:
  `1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE` (`fill.SPREADSHEET_ID`).
- DD lands on each ICD tab's metric row labeled **"Direct Deposit"**, in the
  week column whose header is that week's Sunday date. Find the row by its
  **col-B label** and the week by **date header** (`fill.find_sunday_columns`) —
  NEVER hardcode row/column indices (templates drift).

## Likely causes (verify, don't assume)
- **DMari Longmire blank**: the ICD name almost certainly doesn't match the
  spelling in the PROGRAM SUMMARY / DD view (every ICD IS in Tableau, so a
  non-match = wrong name/view, not missing data). Fix via the shared **ICD
  Aliases** sheet, not a per-report patch:
  `automations.focus_office_att.aliases.save_alias(canonical, alias)`.
- **Wrong amounts for 5/24 & 5/31**: most likely the "Processed Week" filter
  didn't pin correctly (Tableau week-pins are per-view and can leak/auto-restore
  — see the saved-custom-view gotchas). Re-pull the DD view pinned to Processed
  Week = 5/24 and = 5/31, get DD per ICD, compare to what's on the sheet, then
  correct.

## Hard rules (from CLAUDE.md)
- **Preview on ONE tab first: Marcellus Butler.** Fill/verify there, wait for
  Megan's "looks good, roll out" before touching the other ~52 tabs.
- **`--dry-run`** while testing (no Sheet writes) until the output is confirmed.
- **Don't wipe/overwrite good data** — correct only the DD cells for 5/24 & 5/31;
  never blank other weeks or other metrics.
- **Cite the full source** when you report a number: workbook → view → worksheet
  → filter → row/col.
- Cross-platform (macOS + Windows); no hardcoded paths/`%-I`/`.venv/bin/python`.

## Suggested first steps
1. Pull the PROGRAM SUMMARY / DD view, pinned to Processed Week 5/24 then 5/31,
   and print DD-per-ICD (dry-run). Confirm the totals look right with Megan.
2. Read Marcellus Butler's "Direct Deposit" row at the 5/24 and 5/31 columns;
   compare sheet vs Tableau; show Megan the diff before writing.
3. Search the DD view for "DMari Longmire" / close spellings; if found under a
   different spelling, add an alias.

## Parked threads (not part of this task, for awareness)
- **Auto-relogin shipped** (commit 6bb9935) — ownerville/Tableau/AppStream-SSO
  sessions self-heal expired logins. Next: recruiting direct-AppStream self-heal
  + macOS `launchd` scheduler on Megan's always-on Mac.
- **Bug Reports cleanup**: `python -m automations.hub_bug_resolve --match "…"
  --note "fixed in <sha>"` marks rows Resolved (quiet status, no submitter email).
- **Marcial Rodriguez "formatting"**: investigated — FS/LS block row heights are
  uniform 21px (no height anomaly). Open question: what specifically looks wrong
  (possibly the stale "WE 5.17" week label). Ask Megan before acting.
