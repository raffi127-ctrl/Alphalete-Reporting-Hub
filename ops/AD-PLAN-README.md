# Ad Plan — How It Works (Alphalete Recruiting Dashboard)

Workbook: **Alphalete Recruiting Dashboard** — `111Bmxx1JvT1UFXaLin7gPH53149WBZhMe0r7CHirHbA`
This doc covers the **Ad Plan** tab, the hidden ad-tracker tabs behind it, what feeds them, and — most importantly — **what breaks when you change things**, so the next change doesn't repeat an old mistake.

Deeper docs: `~/recruiting-report/automations/funnel_board/RUNBOOK.md` (full workbook archaeology), `README.md` and `BUILD_NOTES.md` in the same folder.

*Maintained automatically: a scheduled task updates this file daily at 7pm with new changes, new issues, and new tabs (see "Changelog" at the bottom).*

---

## 1. What the Ad Plan tab is

One visible tab that mirrors whichever person's **hidden Indeed ad tracker tab** you pick from a dropdown. (Formerly named **"Manager View"** — renamed 2026-08-22; old docs saying "Manager View" mean this tab.)

Cell-by-cell:

| Where | What |
|---|---|
| `B1` | "VIEWING:" dropdown. Data validation = ONE_OF_RANGE pointing at `'Ad Plan'!$AC$1:$AC$60`. |
| `AC1` | The dropdown's source list: `=SORT(FILTER($AD$1:$AD$60,$AE$1:$AE$60<>""))` — everyone with a connected tracker, alphabetical, one combined list. |
| `AD1:AE60` | The lookup map: **AD = person's full name, AE = the name of their hidden tracker tab**. A name with a blank AE is "not connected" and stays out of the dropdown. |
| `A2` | The mirror itself. **Since 2026-09-07 (once the Ad Plan Mirror script is installed):** the view area `A2:Z1000` is a script-pasted snapshot — values AND formatting — of the selected person's actual tracker page, repainted on every B1 change (installable onEdit) and hourly (time trigger). Script: `ad_plan_mirror.gs` (kept at `~/recruiting-report/automations/funnel_board/appsscript/`). Before that it was a formula: `=LET(t,IFNA(VLOOKUP($B$1,$AD$1:$AE$60,2,FALSE),""),IF(t="","No ad tracker connected for "&$B$1,INDIRECT("'"&t&"'!A1:Z1000")))` — which could never show colors (INDIRECT/IMPORTRANGE strip formatting). The script parses each person's source URL out of their hidden tab's IMPORTRANGE, so AD/AE stays the only map. `F1` shows what's loaded + refresh time. |
| `AA` / `AB` | The **old** Org / Captainship name lists. **Unused since 2026-09-05** but deliberately left in place so the group picker can be restored with a one-cell change (see §4). |

## 2. The hidden source tabs

- Each person has a hidden tab named either their short name (`Carlos`, `Roshan`, `Raf`…) or full name (`Drew Tepper`, `Sabrina Alicea`, `Calvin Ribera`…). **AE column is the source of truth for which name each person uses.**
- Most are live `=IMPORTRANGE(...)` mirrors of that person's own tracker spreadsheet, pulling `"*Indeed Tracking!A2:Z"`. Google refreshes these on its own — nothing on our side has to run.
- Standard columns: Office ID, Report Date, Status, Posted By (proxy), Indeed Account, Ad Title, Location, Date Posted, Total Spend, Total Applies, 2nd Interviews Booked, Total Hired.
- **Columns B (Report Date) and S (Daily Budget) are load-bearing** — the Recruiting Dashboard's AD BUDGET boxes read them (see §3). Report Date must stay a real date, Daily Budget a real number.
- Not connected as of 2026-09-17: **Jeff Starr, Vincent Smith** (in AD, blank AE — not in dropdown).
- Redundant tab: hidden **'Sabrina'** duplicates **'Sabrina Alicea'** (same IMPORTRANGE source). 'Sabrina Alicea' is the wired one; 'Sabrina' is safe to delete.

## 3. Who reads / writes what (don't step on these)

| Actor | Relationship to Ad Plan |
|---|---|
| `funnel_board` (Lucy 2, 4am + hourly) | Rebuilds Recruiting Dashboard / Focus Report / Manager Matrix. **Deliberately does NOT write the Ad Plan tab** (build.py explicitly writes the per-manager sheets instead). Manual edits to Ad Plan's formulas persist; manual edits to the tabs the builder owns get wiped on the next run. |
| AD BUDGET boxes (on the dashboard boards) | Pure formulas that `INDIRECT` each manager's hidden tracker tab **by the name shown in the board's column A**, reading cols B and S at the latest Report Date. They do NOT go through Ad Plan's AD/AE map. |
| `tracker_mirror` (ferry) | **STOOD DOWN on purpose.** Re-enabling it overwrites the live IMPORTRANGE tabs with frozen values. Do not turn back on. |
| `captainship_boards`, `ad_sales_board`, `indeed_source_report` | Write other tabs in this workbook, not Ad Plan. |

## 4. Change history — what we changed and what we had to adjust

- **2026-08-22 — tab renames.** Manager Board → Recruiting Dashboard, Manager Trend → Focus Report, **Manager View → Ad Plan**. Automations referencing old names had to be updated; RUNBOOK carries the mapping.
- **2026-08-27 — tracker_mirror stood down.** The ferry that copied tracker data was killed because it replaced live IMPORTRANGE feeds with frozen snapshots. *The adjustment that keeps the report functioning:* trackers stay as direct IMPORTRANGE mirrors and nothing copies over them.
- **2026-08-27 — captainship_boards outage.** Adding Sabrina Alicea to OWNERS without sharing her board with `raffi127@gmail.com` failed the **entire** captainship run for a day. Adding a person to a config and granting the access are two separate steps — do both in the same sitting.
- **2026-09-05 — 9 new trackers wired in** (Kinsey Guenther, Calvin Ribera, Monika Swanson, Alex Badawi, Nic Lujan, George Hipolito, Joshua Murphy, Joey Ramirez, Sabrina Alicea): AE filled / AD+AE rows added, source tabs hidden.
- **2026-09-05 — single alphabetical dropdown.** The Org/Captainship GROUP picker (D1/E1) was removed. *The adjustment that keeps the report functioning:* B1's validation points at `AC1:AC40`, so `AC1` had to be replaced in the same edit with the combined `SORT(FILTER(AD,AE<>""))` — removing the picker without swapping AC1's formula would have left the dropdown broken (its old formula read the now-meaningless E1). AA/AB kept intact for easy revert: restoring is just putting the old IF/FILTER formula back in AC1 and re-adding the E1 dropdown.

## 5. WHEN YOU MAKE A CHANGE — what typically breaks

**Adding a person** (3 steps; missing any one breaks something):
1. Their tracker tab must exist in this workbook (usually an IMPORTRANGE of their sheet — the **first** IMPORTRANGE to a new spreadsheet needs a human to click "Allow access" in the cell).
2. Add name → tab to `AD`/`AE` **within rows 1–40**. The dropdown updates itself.
3. If they're also a captain being added to `captainship_boards` OWNERS: **share their sales board with `raffi127@gmail.com` as Editor in the same sitting**, or every captainship run fails (8/27 incident).

**Renaming or deleting a tab:** `INDIRECT` references break **silently** (shows an error or "No ad tracker connected", no warning). A tracker tab rename must be mirrored in Ad Plan's `AE` column **and** checked against the dashboard AD BUDGET boxes, which look tabs up by the board's column-A names.

**Hidden ≠ unused.** Almost every hidden tab here is load-bearing (trackers, 0Config, WE, Daily Log, Campaign Log, Indeed Ad Data…). Never delete a hidden tab without checking what reads it. Known exception: hidden 'Sabrina' (duplicate).

**The row-60 ceiling.** `A2`'s VLOOKUP, `AC1`'s FILTER, B1's validation, AND the mirror script's map read all stop at row 60 (bumped from 40 on 2026-09-17; currently 42 rows used). Person #61 needs all FOUR bumped together — the script constant lives in `ad_plan_mirror.gs`.

**The spill area.** Typing anything into the region A2 spills into (roughly `A2:Z1000`) kills the whole view with a #REF "would overwrite data" error. Keep helper data in AA+ only.

**Tabs the builder owns.** Manual formatting/edits on Recruiting Dashboard, Focus Report, or Manager Matrix are wiped by the next `funnel_board` run. Change those in `build.py`, not by hand. Ad Plan is the exception — it's hand-maintained.

**Never round-trip through xlsx.** Uploading an .xlsx copy of a live sheet destroys formulas and dropdowns. Edit live via the Sheets API (spreadsheets-scope token in `~/.config/recruiting-report/`).

**Colors only work for shared trackers.** The Ad Plan Mirror script opens each person's real spreadsheet — that requires their tracker sheet to be shared with the account that installed the script (carloshidalgo349@gmail.com). IMPORTRANGE's "allow access" does NOT count. Unshared → the script falls back to a values-only copy and says so in F1. Same class of trap as the 8/27 captainship sharing outage: wiring a person in and sharing their sheet are two separate steps.

**A2 is no longer a formula.** Once the mirror script is installed, don't re-add the INDIRECT formula in A2 or it will fight the script's pastes. To revert to the formula mirror: delete the script's triggers, clear A2:Z1000, put the LET/VLOOKUP/INDIRECT formula (recorded above) back in A2.

**Filters on Ad Plan hide every other person's data.** (10/6 incident.) A Data filter created while viewing one person (e.g. filtering Report Date to recent dates) sticks to the TAB, not the person — switch names and the new person's rows get hidden, so the picker looks dead ("3 of 3,897 rows displayed" in the bottom-right corner is the tell). Fix: Data → Remove filter. Filter VIEWS (Data → Filter views) are per-user and safe; plain filters are not — don't leave one on this tab.

**Tracker column contract.** If someone restructures their personal tracker (moves Report Date off column B or Daily Budget off column S, or stops using real dates/numbers), their AD BUDGET box quietly reads wrong. Check cols B and S when a manager's budget numbers look off.

---

## Changelog (auto-updated daily at 7pm)

- **2026-09-06** — README created. State: 30 people in dropdown, 3 unconnected (Jeff Starr, Vincent Smith, Dhyey Patel), GROUP picker removed, 'Sabrina' duplicate pending deletion.
- **2026-09-07** — Carlos reported colors wrong on Rafael's view. Root cause: INDIRECT/IMPORTRANGE strip all formatting; the visible colors were stale hand-paint from another person's layout, plus 17 dead conditional-format rules covering only rows 1000+ (old Manager View leftovers). Fix: `ad_plan_mirror.gs` bound Apps Script — copies values+formatting straight from each person's real tracker page on B1 change + hourly. Pending: one-time `install()` run by Carlos (Apps Script API is disabled on the GCP project, so it couldn't be deployed headlessly); per-person sharing check afterwards.
- **2026-09-17** — 10 more people wired in: Colten Wright, Jairo Ruiz, Frank Matos, Joseph Delgado, Justin Fermin, Jose Velasquez, George Delgado, Valeria Tristan, Eveliz Wright, plus Dhyey Patel (his tab now exists). Map crossed the old row-40 ceiling, so all four ranges (A2 formula, AC1 filter, B1 validation, mirror-script map) were bumped to 60 in one edit. Dropdown now 40 names; only Jeff Starr and Vincent Smith remain unconnected. Carlos's request used phonetic spellings (Cohen/Colten, Hayro/Jairo, Abelis/Eveliz, Firmin/Fermin) — the sheet's tab names are canonical. Source tabs hidden.
- **2026-10-05 — MIRROR SCRIPT FINALLY INSTALLED.** Carlos reported Khalil's/Isaiah's ad-title colors not updating; root cause = the 9/07 install never happened (A2 still held the INDIRECT formula, which strips formatting for everyone). Installed now: `ad_plan_mirror.gs` pasted into the bound **Goal Sync** project (own file, no collision with its simple onEdit), `install()` run as CarlosHidalgo349 — onEdit + hourly triggers verified in the Triggers panel. TWO consents granted (Sheets + run-unattended, then external-requests). **Hardening found during install:** `openByUrl` on an unshared tracker aborts the whole execution uncatchably — one unshared sheet killed the run. Fix in the repo copy (now canonical): a Sheets REST probe (`muteHttpExceptions`) checks access first; unshared → values-only fallback + F1 note, never a crash. **REMAINING HUMAN STEP: colors only render for trackers shared with CarlosHidalgo349@gmail.com** (viewer is enough; IMPORTRANGE's allow-access does NOT count). As of install, Khalil's and Rafael's trackers probe NOT shared under Carlos's own token — assume all ~36 IMPORTRANGE'd trackers need sharing. Aya Al-Khafaji / Drew Tepper / Jackie LeRoy / Noah Dubale have no IMPORTRANGE in A2 (frozen tabs) — they can only ever show values until re-wired. A2 is a pasted snapshot now: do NOT re-add the INDIRECT formula (§5 rule stands).
- **2026-10-06** — "Can't pick who I'm viewing": root cause was a leftover basic filter on Report Date (hiding blanks + all pre-10/1 dates), pinned while someone was on Khalil Mansour — every other pick's rows were filtered out, so switching looked broken. Dropdown, map, and mirror script were all healthy. Cleared the filter; added the filter trap to §5. Mirror script confirmed INSTALLED since 10/5 (onEdit + hourly live; openByUrl-abort hardened with a REST probe).
