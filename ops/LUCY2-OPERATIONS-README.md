
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

## 2026-11-19 — Report Library cards do NOT run on Lucy 2 (its card scheduler only watches)

`com.alphalete.card-scheduler` on Lucy 2 has run in OBSERVE mode since at least 2026-09-15: every pass logs
`WOULD run <card> (<time>) [dry-run]` and `Lucy 2 · N assigned here · 0 run (dry-run: none run)` in
`output/logs/card-scheduler-<date>.log` (`CARD_SCHEDULER_LIVE` is not set). So a timed card assigned to Lucy 2
never fires. The seven timed Lucy 2 cards on 11/19, none of which has ever run on its own:

| Card | When | Args |
|---|---|---|
| `daily_plan_text_8am` | 8:00 AM Mon–Sat | `--send` |
| `car_rides` | 8:30 AM Mon–Sat | `--live` (its own launchd agent was removed 9/29) |
| `nds_tnc_check_730am` / `_830pm` / `_930pm` | 7:30 AM / 8:30 PM / 9:30 PM daily | `--post …` |
| `nico_roster_check` | 9:15 PM daily | `--write` |
| `daily_update_fill` | 8:45 PM daily | `--write` |

Last real runs found: daily_plan_text = the 11/11 hand send; nico_roster_check = an 11/04 rerun; nds_tnc_check =
an 11/06 rerun; daily_update_fill = an 11/02 rerun. **Rule until this is settled: an exact-time Lucy 2 job gets
its own launchd agent** (`deploy/com.alphalete.<name>.plist` + a wrapper .sh + an `install_<name>_agent` entry,
installed with `rerun install_<name>_agent`) — e.g. `com.alphalete.week-one-text` (11/19),
`com.alphalete.nds-rep-dms` (11/23, the 9am rep order-log DMs) and `com.alphalete.verizon-texts`. Turning the scheduler live would start all seven at once (including car rides'
live OwnerVille edits) — Carlos's call, not done. Check: `logtail card-scheduler-<date> WOULD 20`.
