
## Sheets identity per machine (11/4/2026)
The gspread OAuth token (`~/.config/recruiting-report/oauth-token.json`, spreadsheets scope only) belongs to a DIFFERENT Google account on each machine: **mini = CarlosHidalgo349@gmail.com, Lucy 2 = alphaletereporting@gmail.com**. Symptom of forgetting this: a module works on the mini, then the same module on Lucy 2 dies with `PermissionError` in `gspread open_by_key`. Fix: share the spreadsheet to **alphaletereporting@gmail.com** (writer). Sharing raffi127@gmail.com (the account named in the captainship_boards docs) does NOT cover Lucy 2's gspread token. First hit: nico_roster_check on 'Nico Verizon Payroll', 11/4.

**2026-11-06 — queue rows SHIFT while a job runs → results on the wrong row → the job runs AGAIN.** The poller
writes Status/Result/Finished back to the row number it captured when it started. When another session INSERTS
rows above (not appends) while the job runs, that write lands on the wrong row and the real row stays "queued",
so the poller picks it up a second time. Seen 11/6: `rerun nds_oof --recap-week 2026-10-31 --send` ran at
10:28 AND 10:33 and #a-players-b2b got the thread twice (second copy deleted with
`rerun aplayers_cleanup --thread <parent ts> --live`). Rules: (1) read a queue row by its ARGS, never by the
number you appended at; (2) anything that SENDS must be idempotent (the recap now checks the room for a
parent with the same text today — do the same for any new sender); (3) "running" on a row whose job clearly
finished = a shifted write, not a hung job; (4) `rerun <report>` carries the card's base_args — nds_metrics
reruns always include `--post`, so "dry" there means a section already in today's thread state is skipped,
not that nothing posts.

**2026-11-06 — push_cred_file keys live in the RUNNING poller.** A key added to `_CRED_FILES` in mini_control.py is unknown to the receiving box until its poller restarts: the first `set_cred_file gmail-app-password-carloshidalgo349` failed 'unknown file-key' four seconds before the `update` landed, and would have failed after it too. Order: push the code → `update` → `restart_poller` (wait for done) → `push_cred_file` from the box that has the file → verify. The push row lands on the target's OWN workbook tab (mini_control prints '(own workbook)'), not the 1eJ3 sheet — look there (`mini_control._own_live_tab`) when a pushed file seems to vanish.

