# Local Office Sales Call Outs — README

> **2026-10-19: Fiber → NDS.** The crew's reports now come from CARLOS'S Ownerville (office 11580), campaign **RES AT&T OOF** (invD2DClientId=1), labelled **NDS**, built by `automations/nds_oof/` on Lucy 2 (agent `com.alphalete.nds-oof`, every 15 min). Labels: **NDS Knocks Board** (hourly), **NDS 15 min gaps** (every 15 min), **NDS —** call-outs (hourly, crossed with his SaraPlus credit checks). Same chats (NEW A Players, ATT B2B Leaders) and `NDS …` threads in #alphalete-gp-sales. The Fiber rows below (FIB-1/2/3, SAL-7/8) are OFF; Raf's login is no longer read for Carlos's crew. Roster `total_knocks.guests` stays so Raf's boards still exclude them. Hand runs: `rerun nds_oof --force --board` (dry), `--send` to post; `rerun install_nds_oof_agent`.

Carlos's live reporting for his office: knocks boards, 15-minute gap lists,
territory stats, and sales alerts for the **Box** team, the **Fiber** crew
(his reps knocking and selling under Raf's code), and the **B2B AT&T** team.
Built 2026-09-29 → 2026-10-08. Code lives in `~/recruiting-report/automations`.

Rules Carlos set:
- Knocks boards and gap lists are **separate reports** (separate messages).
- Every post starts with the campaign name (Box…, Fiber…, AT&T…).
- Confirm destinations with Carlos before deploying anything that sends.
- Saturdays: no disposition posts after 5:30pm (sales alerts are exempt).

---

## 1. Where things go

**Carlos's five places** ("me"):
- Texts: **Box B2B**, **NEW A Players**, **ATT B2B Leaders**
- Slack: **#alphalete-gp-sales** (C07J46MQNUX), **#a-players-b2b** (C0AJQA8P716)

### Texts

| Label | Report | Chat | How often | Start | End |
|---|---|---|---|---|---|
| BOX-1 | Box Knocks Board (picture) | Box B2B | Once a day | 6pm | 6pm (Sat 4pm) |
| BOX-3 | Box 15 min Gaps (typed) | Box B2B | Every 30 min | 12pm | 6pm (Sat 4pm) |
| SAL-1 | Box Live Sales (standings, 🔥 on who sold) | Box B2B | Every Box sale | 12pm | Midnight, 7 days |
| FIB-1 | Fiber Knocks Board (picture) | NEW A Players, ATT B2B Leaders | Every hour | 2pm (Sat 10:30) | 9pm (Sat 5:30) |
| FIB-3 | Fiber 15 min gaps (typed) | NEW A Players, ATT B2B Leaders | Every 15 min | 2pm (Sat 10:30) | 9pm (Sat 5:30) |
| SAL-2 | AT&T Live Sales (Carlos's SaraPlus) | NEW A Players, ATT B2B Leaders | Every AT&T sale | 12pm | Midnight, 7 days |
| SAL-7 | Fiber Live Sales (Raf's SaraPlus, crew only) | NEW A Players, ATT B2B Leaders | Every crew sale | 12pm | Midnight, Mon–Sat |
| SAL-8 | Fiber credit checks (Raf's SaraPlus, crew only) | NEW A Players, ATT B2B Leaders | Every new check | 12pm | Midnight, Mon–Sat |

### Slack: #alphalete-gp-sales

Six threads are opened and pinned every morning at 7:30 (Mon–Sat), right
after the B2B Metrics and Box Metrics threads. Everything below posts
**inside its thread**, except the call-outs and sale shout-outs.

| Label | Report | Thread / where | How often | Hours |
|---|---|---|---|---|
| BOX-1 | "Box Knocks Board — [time]" | `Box Knocks Board — <Month Dth YYYY>` (opens with yesterday's final board) + the `Knocks and Dispositions` thread in #a-players-b2b | Every 2 hrs | 12–6pm (Sat 12–4) |
| BOX-2 | Box Today's Activity (Ownerville knock-count panel) | `Box Today's Activity M/D/YY` | Once | 6pm (Sat 4pm) |
| BOX-3 | "Box 15 min gaps — [time]" (typed) | `Box 15 Min Gaps M/D/YY` | Every 30 min | 12–6pm (Sat 12–4) |
| BOX-4 | Box Territory Stats, one picture per territory | `Box Territory Stats M/D/YY` (opens with yesterday's pictures) | Once | 6pm (Sat 4pm) |
| BOX-5 | Weekly Knocks (Box + AT&T boards) | Own post + #a-players-b2b thread | Sundays | morning |
| FIB-1 | "Fiber Knocks Board — [time]" | `Fiber Knocks Board — <Month Dth YYYY>` (opens with yesterday's final board) | Every hour | 2–9pm (Sat 10:30–5:30) |
| FIB-3 | "Fiber 15 min gaps — [time]" (typed) | `Fiber 15 Min Gaps — <Month Dth YYYY>` | Every 15 min | 2–9pm (Sat 10:30–5:30) |
| FIB-2 | "Fiber — …" call-outs (no dispo + no credit check) | Own post | About every hour | field hours, cutoff 8:30pm (Sat 5pm) |
| SAL-3/4 | "Box — …" / "AT&T — …" sale shout-outs | Own post | Every sale | 12pm–midnight |
| SAL-5 | "AT&T — 🔍 … just ran a credit check" | Own post | Every new check | 10am–9:30pm (Sat 5pm) |
| SAL-6 | "Customers who didn't receive wrap up text" | Own post (+ #a-players-b2b) | Daily | ~4am |

**Stopped:** ATT-1 (B2B AT&T daily knocks board), ATT-2 (AT&T hourly), ATT-3 (AT&T territories).

**BOX — ALL OFF since 2026-10-28** (plus the B2B Box tracker text, 10-29) (Carlos: "all of these box automations you're good to turn off"): BOX-1 (knocks board + 6pm text), BOX-2 (Today's Activity), BOX-3 (15 min gaps Slack + Box B2B text), BOX-4 (territory stats + the 7:30 morning fill), BOX-5 (Sunday weekly per-rep board, Box AND AT&T halves), SAL-1/SAL-3 (Box live sales). How: Lucy 2 LaunchAgents `com.alphalete.b2b-dispositions-{gaps,hourly,morning}` unloaded via `rerun remove_b2b_dispositions_<gaps|hourly|morning>_agent`; `weekly_knock_dispositions_carlos_b2b` on_scheduler=false; Box gaps text route `[]`; the office mini's Box key `carlos` stays in `icd_alerts/config.PAUSED_KEYS`. The **Box Order Log** (the morning `Box Metrics — <date>` thread: Tier Bonus, Daily Tracker, Activation Rates, Accepted by supplier, Revenue by Status, Pending orders, Overall log; also the Vantura 'Lucy Box Order Log' tab) is OFF too since 10-28 (Carlos: "the whole thing can go") — `rerun remove_box_order_log_agent` unloaded `com.alphalete.box-order-log` on Lucy 2; `rerun install_box_order_log_agent` restores it. Other owners' Box Order Log email runs are untouched. To bring Box back: `rerun install_b2b_dispositions_<gaps|hourly|morning>_agent`, flip the weekly entry, restore the text route, remove `carlos` from PAUSED_KEYS (office mini needs a My Service Cloud sign-in).

---

## 2. Which machine makes what

| Machine | Makes | Code |
|---|---|---|
| **Lucy 1** (Raf's mini) | FIB-1, FIB-2, FIB-3, SAL-7, SAL-8 (from Raf's Ownerville + SaraPlus); BOX-1, SAL-1..5 (from Carlos's mini relay). Sends ALL texts except BOX-3. | `gap_alerts/`, `icd_alerts/knocks_post.py`, `icd_alerts/gap_callouts.py`, `icd_alerts/post.py`, `alphalete_sales_board/guest_feed.py` |
| **Lucy 2** (the MacBook, logged into Carlos's Ownerville 11580) | BOX-2, BOX-3, BOX-4, BOX-5, the 7:30 threads + pins, the BOX-3 text | `b2b_dispositions/` (run.py, morning.py), `nds_oof/`, `weekly_knock_dispositions`. Texts: the job writes a manifest + a ticket in `~/.config/recruiting-report/text_outbox/`; the Mini Control poller (main lane) sends it. |
| **Carlos's office Mac mini** | Sends nothing. Relays SaraPlus / My Service Cloud / Ownerville numbers to Lucy 1 every ~2 min. When it's off, BOX-1 and SAL-1..5 stop. | Lucy Reports agent (icd_alerts installer) |

Lucy 2 LaunchAgents: `com.alphalete.b2b-dispositions-morning` (7:30),
`-gaps` (every :00/:30, 12:00–5:30, Sat to 3:30), `-hourly` (6pm / Sat 4pm,
`--which all`). All have Sunday entries at Saturday's times that the code
ignores unless the date is in `shared/day_override.py`.

---

## 3. The crew list (Fiber)

One list drives FIB-1, FIB-3, SAL-7, SAL-8, and keeps these reps OFF Raf's
sales board: `automations/total_knocks/guests.py` → `GUEST_REPS["Rafael
Hidalgo"]["Carlos Hidalgo"]`. Spell names the way Ownerville does; matching
tolerates middle names and status suffixes.

As of 2026-10-03 (16): Jorge Gramajo, Rodolfo Bazan, Christian Perez, Jose
Pimentel Lugo, Nicholas Smedra, Aaron De La Torre, Diego Del Pozo Borres,
Yariel Caban, Eduardo Alvarez, Fernando Salazar, Gavin Natividad, Andrew De
La Torre, Danniel Alvarenga, Luis Servellon, Jacob Ortega, Sebastian
Avellaneda.

To add/drop: edit the list, bump the count in `total_knocks/test_guests.py`,
push to main, queue `update` on Lucy 1.

---

## 4. How to change things

| Want to change… | Edit | Then |
|---|---|---|
| Fiber hours, cadence, chats, thread names | `gap_alerts/config.py` → `RAF["guests"]["Carlos Hidalgo"]` (`cadence_min`, `board_every_min`, `start`/`sat_start`, `stop`/`sat_stop`, `title`, `gaps_thread_title`, `board_thread_title`) | push, `update` on Lucy 1 |
| Fiber call-out cadence | `icd_alerts/gap_callouts.py` → `CALLOUT_EVERY_OVERRIDES` | Lucy 1 |
| Box board Slack/text times, header, thread | `icd_alerts/knocks_post.py` → `SET_TIMES`, `BOARD_TITLE`, `THREAD_TITLES`, `BOARDS_OFF`, `NO_GAP_LIST_IN_TEXTS` | Lucy 1 |
| "Box —" / "AT&T —" prefix on sale lines | `icd_alerts/post.py` → `LINE_PREFIX` | Lucy 1 |
| Box gaps / Today's Activity / Territory times | the three plists in `deploy/com.alphalete.b2b-dispositions-*.plist` + `b2b_dispositions/config.py` (`HOURLY_SLOTS`, `SATURDAY_HOURLY_SLOTS` label the captions) | push, `update`, `rerun install_b2b_dispositions_<gaps|hourly|morning>_agent` on Lucy 2 |
| Which campaigns the Lucy 2 posts cover | `b2b_dispositions/config.py` → `HOURLY_CAMPAIGNS`, `DISPOSITION_CAMPAIGNS` (Box only now; add `CAMPAIGN_ATT` to bring AT&T back) | Lucy 2 |
| Box gaps text on/off | `b2b_dispositions/config.py` → `TEXT_ROUTES[(CAMPAIGN_BOX, POST_GAPS)]` | Lucy 2 |
| Thread names | `b2b_dispositions/config.py` → `THREAD_HOURLY`, `THREAD_GAPS`, `THREAD_DISPOSITIONS`; `b2b_dispositions/morning.py` → `NAMED_THREADS`, `ORDER`; `knocks_post.THREAD_TITLES`; the gap_alerts dest titles. Keep them in step: the morning job opens what the posters later look up. | both |
| Fiber sales feed chats | `alphalete_sales_board/guest_feed.py` → `GROUPS` | Lucy 1 |
| NDS knocks board hours | `nds_oof/config.py` → `WEEKDAY_START` (1:30 since 11-03), `SATURDAY_START` (11:45 since 11-07; was 10:15), `SATURDAY_STOP` (6:00), `SAT_EXTRA_BOARD_SLOTS` (11:45/12:00/12:15/12:30), `START_OVERRIDES` for one date | push; Lucy 2 picks it up on the next 15-min tick |
| A rep who knocks on RAF's Ownerville but belongs on the NDS board | `nds_oof/config.py` → `BORROWED_ROWS` (`{"rafael": [names]}`; spell as Ownerville does) | push. Board picture only — not gaps, call-outs, texts or the weekly. Raf's board untouched. |
| "No dispositions from" text: times, roster range, on/off | `nds_oof/config.py` → `NO_DISPO_SLOTS` (Mon–Fri 2:30/2:45/3:00/3:15), `NO_DISPO_SAT_SLOTS` (Sat 12:15/12:30/12:45/1:00/1:15), `NO_DISPO_WEEKDAYS`, `NO_DISPO_RANGE` (Stations `C6:F15`), `NO_DISPO_SEND`; chain = `b2b_dispositions/config.TEXT_ROUTES[("RES AT&T OOF","nds_no_dispo")]` (ATT B2B Leaders only) | push, `update` on Lucy 2 |
| NDS board "Knocks Last 30 Min" test (NEW A Players only) | `nds_oof/config.py` → `BOARD_30_TEST` (off = one board everywhere), `BOARD_30_COL`; routes `b2b_dispositions/config.TEXT_ROUTES` `nds_board` (ATT B2B Leaders while the test runs — put NEW A Players back when it ends) + `nds_board_30` (NEW A Players) | push, `update` on Lucy 2 |
| GPS alerts (3 failed-GPS knocks in a row → ATT B2B Leaders text) | `nds_oof/config.py` → `GPS_ALERTS` (on/off), `GPS_FAIL_STREAK` (3); route `TEXT_ROUTES[("RES AT&T OOF","nds_gps")]` | push, `update` on Lucy 2. Hand run: `rerun nds_oof --gps-now` (dry) / `--gps-now --send`; week count: `rerun nds_oof --gps-week` |
| NDS T&C check: who gets tagged, wording, channel | `nds_tnc_check/config.py` → `MENTIONS` (Slack IDs), `message()`, `CHANNEL` | push, `update` on Lucy 2 |
| NDS T&C check: times | Report Library cards `nds_tnc_check_830pm` / `_930pm` / `_730am` (`schedule.time`; args carry `--post` once live, `--yesterday` on the morning one) | sheet edit only; card_scheduler reads it every pass |
| One date on another day's rules | `shared/day_override.py` → `TREAT_AS_SATURDAY` (+ the date line in `deploy/gap_alerts_5min.sh`) | both |

Deploy flow: commit → `git push origin HEAD:main` → queue `update` on the
machine (Google-Sheet queue, tabs "Mini Control" = Lucy 1, "Mini Control -
Lucy 2") → verify by `logtail`. See `~/alphalete-readmes/LUCY2-OPERATIONS-README.md`.

---

## 5. Hand commands (queue `rerun …`)

| Command | Machine | Does |
|---|---|---|
| `rerun nds_tnc_check [--date YYYY-MM-DD\|--yesterday] [--post]` | Lucy 2 | NDS T&C check for one day; dry-run unless `--post`. `--probe --limit 2` dumps the grid headers + card text to the control sheet's `TNC Probe` tab. |
| `b2b_dispositions --morning --send` | Lucy 2 | Open today's threads, post yesterday's boards, pin |
| `b2b_dispositions --backfill-yesterday "Fiber Knocks Board" --send` | Lucy 2 | Put yesterday's final board into today's thread of that name |
| `b2b_dispositions --delete-loose "<prefix>" --send` | Lucy 2 | Delete TODAY's loose Lucy posts starting with prefix (never thread parents) |
| `b2b_dispositions --which gaps --text --headless` | Lucy 2 | Dry run of the Box gaps (resolves the chat, posts nothing) |
| `sales_board_standings` | Lucy 1 | Raf's board + crew standings now (read-only, no lock) |
| `sales_board_standings --week 2026-09-28 2026-10-04` | Lucy 1 | Crew sales per day / per rep for a range (state keeps 10 days) |
| `gap_alerts --force --only rafael` | Lucy 1 | Preview a Fiber pass (sends nothing) |
| `vantura_payroll --refresh-only` | Lucy 2 | Rebuild the payroll Commission tab after hand-written Adjustments |

---

- `rerun nds_oof --recap-week 2026-10-31` (+ `--send`) — ONE new thread in #a-players-b2b (config.RECAP_CHANNEL) with that week's Mon–Sat board and each day's end-of-day board (output/nds_oof/<date>/total_knocks_<date>.png is overwritten by every tick, so the file on disk is the last board of the day; a missing day is pulled back from that day's NDS Metrics thread). Dry by default. Added 11/6 (Carlos: "send me the weekly knocks board for last week and each individual end of day knocks for last week … post them all on there").

## 6. Known issues / gotchas

- **"No dispositions from" (11-06)**: rides the nds_oof tick; a rep counts as dispositioned only with a row AND >0 knocks on our Ownerville pull + Raf's relay (borrowed). 2:30/3:00 land ~:35/:05 (board slots wait for Raf's share); 2:45/3:15 on the tick. Log: `no-dispo 14:30: N on the car-ride grid, M without dispositions: …` then `text: no-dispo queued`. Blank Stations range = `no names … nothing to check`. One text per slot per day (`no_dispo_slot` in nds_oof_state.json). Text only, no Slack (Carlos). Format = the gaps text's: `No dispositions from — 12:15 PM` then one name per line (Carlos 11-07); nobody missing → `Everyone on the lineup has dispositioned! — 3:15 PM`. A roster nickname vs Ownerville's legal name (Nick Smedra / Nicholas Paul Smedra) is matched by UNIQUE surname; two rows with the surname = still listed as missing (log `no-dispo: X taken as Y`). A slot is its own reason to pull (11-06 3:15: board + gaps weren't due after the late 3:00 tick, and the check was skipped — fixed same day; first real send is Monday 11-09 2:30).
- **NDS T&C check (11-05)**: reads the NDS dealer's SaraPlus (alphaletegp) Sales Order History for the day and opens every row's View Customer card (own Chrome profile `.saraplus_nds_tnc_profile`, so it can overlap nds_metrics' 7:30 pull). Log (`logtail nds-tnc-check-<date> tnc 20`): `N order(s): a confirmed, b NOT confirmed, c card(s) unreadable` — unreadable cards are logged, never called out. A first login on a new profile hits the passcode wall; it self-clears through the alphaletegp inbox/forward like nds_metrics. If SaraPlus renames a label, `CARD_LABELS` in `nds_tnc_check/config.py` is where it lives; the grid columns are matched by header (`COL_ORDER_ID`/`COL_REP`/`COL_CUSTOMER`) and the headers are logged every run. The View Customer RadWindow keeps the PREVIOUS customer's iframe after Close, so a card is only trusted when it names the order id (or the customer's surname) and differs from the last one read; the frame is blanked after reading. Symptom of this going wrong: every order logging the same email/time. A PENDING sale's card has NO `Confirmation Date` row at all (`Confirmation Status: Pending Confirmation`, then `T&C Sent Via`, then the Order Summary button) — the card is recognised by `T&C Sent` / `Confirmation Status`, never by the date row; a missing row IS the not-confirmed case.
- **Unpinning needs `pins:read`** on the Lucy Reporting Slack app (pinning works). Until Megan adds the scope, yesterday's pins stay.
- **Lucy 1 is slow some days**: each Fiber pass can take ~10 min, so "every 15 min" lands every 20–30. The sales sweep holds a lock most of each 5-minute cycle; use `sales_board_standings`, not `alphalete_sales_board …`, for reads.
- **BOX-1 needs the office mini**. "last relayed … too old" in Lucy 1's poster log = the mini is asleep/off/logged out.
- **Hourly Fiber board stops at 8:08pm**: the hourly anchor lands at :05 and the window ends 9:00. Set `stop` to `21:10` if a 9pm board is wanted.
- **Thread title formats differ on purpose**: Lucy 2's are `Prefix M/D/YY`; the two Lucy 1 posts into are `Prefix — Month Dth YYYY`. Each job looks up its own format.
- **The b2b_dispositions reply dedupe** matches the caption at the START of a reply (a `"2 PM" in "12 PM"` bug used to skip 2pm posts).
- **Never post blank**: gap lists and the gaps text skip a slot when nobody is over 15 minutes.
- **No sales post at all (SaraPlus code wall, 11-02)**: SaraPlus logs the office Mac mini out every few days and wants an emailed code; until it's typed, NO standings text and NO sale lines (Lucy DMs the Carlos/Megan/Evelyn group DM). Check on Lucy 1: `logtail icd-alerts-poster-<date> CODE 10` → `CODE carlos-b2batt asked for a code; … -> none` means Lucy 1 couldn't answer; `-> ready` means it did. Codes go to alphaletegp's inbox (forwarded to alphaletereporting). Fixed 11-02: `lucy rerun icd_code_mail_register --register carlos-b2batt <address>` on Lucy 1 (`--list` to see who's registered) so the Mac clears the wall itself. If it still sits there, someone at the office Mac runs the command from https://raffi127-ctrl.github.io/Alphalete-Reporting-Hub/sara-signin.html (nothing pops up by itself) → ALL SET → sales flow within 2 min. Stopgap numbers: Lucy 2 `rerun vantura_nds_sara --probe` reads SaraPlus directly.
- **Borrowed reps missing AGAIN (11-04/05)**: Raf's board moved to his own office Mac on 11-03 (Lucy 1's gap_alerts for him is off), so nothing wrote his `Lucy Knocks` row any more. Since 11-06 `nds_oof` also reads the office Macs' `ICD Knocks` relay tab (`nds_oof/config.BORROWED_ICD_OFFICES` maps `rafael` → his ICD office key `raf`); newer tab wins. Log line now ends `(shared <time>, ICD Knocks office <key>)` or `(…, Lucy Knocks)`; `no 'Lucy Knocks' row and no 'ICD Knocks' relay for rafael today` = his Mac isn't relaying (check the Office Channels row / his machine). `rerun nds_oof --share-dump` prints both tabs as Lucy 2 sees them.
- **Borrowed reps missing from the NDS board (11-03)**: Cinthya Reyes + Nathaly Benitez come off the relay workbook's `Lucy Knocks` tab (Raf's rows, shared by gap_alerts on Lucy 1 every 30 min). Lucy 2 log (`logtail nds-oof-<date> borrowed 10`): `borrowed: <name> off rafael` = on the board; `not on rafael's rows today` = name spelled differently on Raf's grid or they haven't knocked; `no 'Lucy Knocks' row for rafael today` = Raf's pull hasn't run yet (it starts ~1:30) or Lucy 1 is down. Raf's rows are re-shared only when HIS board draws (~:04/:34), so a board tick WAITS up to 9 min (`BORROWED_FRESH_WAIT_MIN`) for a share newer than the slot start — the NDS board posts ~:05/:35, not :00/:30. `borrowed: waiting for rafael's share` / `fresh share arrived` / `drawing with what is there` are the log lines.
- **A SaraPlus glitch sticks**: the sales feed only ever moves UP (so it never re-announces a sale). If Sara briefly shows a rep too high and then corrects, Lucy keeps the high number all day and the poster log says `BACKSLID … 8 -> 4` every pass. Fix from anywhere: queue on Lucy 1 (`Mini Control` tab) `icd_correct_sales carlos-b2batt "Andrew De La Torre" NL=4` (metric names: NL, Int, Int Up, DTV; Box uses Sales). The next standings text then carries the corrected number.
- **Texts stop but Slack keeps posting** = the queue sheet is the problem, not Messages. Since 10-26 texts use the local outbox, so this only happens if the poller itself is down (`restart_poller`). Pre-10-26 symptom: `text_dispositions` rows sitting `queued`.
- **2026-10-04** ran as a Saturday (one-off). The date in `shared/day_override.py` and `deploy/gap_alerts_5min.sh` can be removed; it's harmless to leave.
- **Payroll adjustments** (Vantura board, `Adjustments` tab): `Week | Rep | Type | Amount | Label`, Type ∈ {Bonus, NPA, REMOVEALL, REMOVELINE}; use the Commission-tab spelling of names; "bring up to $X" = Bonus of X − current commission; then `vantura_payroll --refresh-only`.

---

## 7. Change log

- 11-07 (Sat) **GPS alerts** for Carlos's crew: every board tick (:00/:30 in the NDS window) nds_oof reads his Ownerville Today's Activity knock table (same table Raf's rep_knock_breakdown reads) and texts ATT B2B Leaders once per rep streak of 3+ failed-GPS knocks in a row (Raf's wording: `GPS alert: <rep> has N knocks in a row that failed GPS (t1 to t2) — too far from door (0.45 mi … from the door).`). Dedupe in nds_oof_state `gps_texted` (per day). `--gps-week` printed the week: 5,371 knocks, 214 failed (4.0%), Rodolfo 98. Cinthya/Nathaly are on Raf's Ownerville → his job.
- 11-07 (Sat) TEST: NDS knocks board with a `Knocks Last 30 Min` column (knocks since the previous board; totals saved in nds_oof_state `last_board_knocks` only when a board really sent; new day resets) texted to NEW A Players only; plain board to Slack + ATT B2B Leaders. Renderer gained `extra_columns={name: {rep: value}}` (inserted after Total Knocks, before Avg Knocks / Hr). First board of the day shows the day's totals in that column.
- 11-07 (Sat) NDS Saturday schedule: knocks board 11:45, 12:00, 12:15, 12:30 then every 30 min to 6:00pm; 15-min gaps from 11:45; weekly Mon–Sat board after the 6:00 board (was 5:30); "No dispositions from" also runs Saturdays at 12:15/12:30/12:45/1:00/1:15 (`NO_DISPO_SAT_SLOTS`). `nds_oof/config.py` SATURDAY_START/STOP, SAT_EXTRA_BOARD_SLOTS, NO_DISPO_WEEKDAYS.
- 11-06 **"No dispositions from"** text (ATT B2B Leaders only) at 2:30/2:45/3:00/3:15 weekdays from `nds_oof`, roster = Vantura master Stations `C6:F15`. T&C check switched live. Cinthya/Nathaly: the 2:00/2:30 boards missed them because their first knock was 2:35 — relay path confirmed working (Raf's 2:54 relay carried both).
- 11-06 NDS board: Cinthya + Nathaly back — borrowed rows now come off the `ICD Knocks` relay (Raf's own Mac) when the `Lucy Knocks` share is absent (it has been since Raf left Lucy 1 on 11-03). `--share-dump` diagnostic added.
- 11-05 **NDS T&C check** (`automations/nds_tnc_check`, Lucy 2): 8:30pm + 9:30pm for today and 7:30am for yesterday, every day. Every NDS sale's View Customer card → `T&C Sent Via` / `Confirmation Date`; no DATE = Slack call-out in #alphalete-gp-sales (under the NDS Metrics thread when open) tagging Carlos + Sebastian Avellaneda: "Hey, customer <first> (rep: <rep>) — TNC has not been completed." LIVE 11-06 3pm (Carlos: "youree good to go"): the three cards carry `--post`.
- 09-29 Split knocks from gaps; Box hourly → once a day; AT&T daily boards stopped; Fiber board + gaps texted hourly; Fiber sales/credit feed off Raf's SaraPlus (SAL-7/8).
- 09-30 Jacob Ortega added to the crew.
- 10-03 Labels BOX/FIB/SAL/ATT; Fiber Saturdays from 10:30; morning threads + pins; campaign-first names; FIB-3 every 15 min, BOX-3 every 30; FIB-2 hourly; Sebastian Avellaneda added; loose pre-thread posts deleted.
- 10-04 Sunday run as Saturday (one-off).
- 10-08 Yesterday's final Fiber board at the top of the morning Fiber thread; `--backfill-yesterday`; payroll `--refresh-only`.
- 11-02 **NDS week-over-week board** (`nds_oof/week_compare.py`, `rerun nds_oof --compare <saturday> --week-thread 'NDS Metrics' --send`): every rep × every stat, "prev → last (Δ)", green better / red worse (lower is better for Gap + First Knock), OFFICE TOTALS first, "new" / "off board" for roster changes. Data = the row dump weekly_knock_dispositions now writes next to each PNG (`rows` in the .json); missing weeks are rendered dry (Ownerville pull). Hand-run only so far; one copy per thread.
- 11-02 **Monday-morning NDS weekly board**: every Monday the first NDS tick at/after 10:00 posts last week's Mon–Sat NDS Knocks Board as a reply in that day's `NDS Metrics —` thread (Slack only, one copy per thread; `nds_oof/config.WEEK_MONDAY_AFTER/_THREAD`, `_week_monday_due`). The Saturday after-last-board post (Slack + texts) stays. Hand run: `rerun nds_oof --week <saturday> --week-thread 'NDS Metrics' --send`. Also `START_OVERRIDES` (per-date earlier start, used 10-30 for a 1:30 start).
- 10-29 **B2B Box tracker text OFF**: the daily Tableau Country Trackers run (Lucy 3, `tableau_screenshots --text-trackers`) was still texting the B2B Box board picture to Box B2B + NEW A Players through Lucy 2 (`text_tracker b2b_box`). Carlos: "i saw some box stuff go out … on the box text chain". `tracker_texts/config.ROUTES['b2b_box'] = []`; the Slack post in the Country Trackers thread stays. The NDS tracker text (ATT B2B Leaders + NEW A Players) is unchanged. This was never in the BOX-1..5 list — it is a Tableau tracker, not a disposition report.
- 10-28 **Box Order Log OFF** too (Carlos: "the whole thing can go"): `com.alphalete.box-order-log` unloaded on Lucy 2; Box Metrics thread + Vantura Lucy Box Order Log tab stop.
- 10-28 **Box OFF entirely** (Carlos). Three Lucy 2 Box agents unloaded, weekly Carlos B2B board off the Sunday scheduler, Box gaps text route blanked. NDS + AT&T sales reporting unchanged.
- 11-03 NDS knocks board: weekdays open 1:30 (was 2:00); Cinthya Reyes + Nathaly Benitez (knocking on Raf's Ownerville) added to the board picture via `nds_oof/config.BORROWED_ROWS` off the `Lucy Knocks` tab. Board only. Same day 2:30pm: numbers were 26 min stale → board now waits for Raf's fresh share (posts ~:05/:35).
- 11-02 SaraPlus code wall took the sales post out 10:01–6:50pm; `icd_code_mail_register` one-off added (Lucy 1) so carlos-b2batt's code requests are answered from the reporting inbox; Carlos ran the sara-signin command on the office Mac at ~6:50pm (ALL SET).
- 10-27 `icd_correct_sales` queue action + `icd_alerts/correct_sales.py`: lower one rep's pinned count after a SaraPlus glitch (Andrew De La Torre 8 → 4 on 10-27).
- 10-26 (evening) **Texts no longer ride the queue sheet.** The Mini Control workbook stopped answering (every read/write timed out), Lucy 2's texts sat queued for hours and each NDS tick spent ~9 min trying to enqueue, so boards posted 20–40 min late. Now `nds_oof` and `b2b_dispositions` drop a ticket in `~/.config/recruiting-report/text_outbox/` and the main-lane poller drains it before and after every sheet poll (`day_orchestrator/text_outbox.py`, `mini_control._drain_text_outbox`). Same sender process, same groups, idempotent via the `.sent` marker. Stuck tickets park under `text_outbox/failed/` after 30 tries.
- 10-26 NDS board every 30 min (`nds_oof/config.BOARD_EVERY_MIN`).
- 10-26 NDS Mon–Sat combined board on Saturdays after the 5:30 board (weekly_knock_dispositions row `Carlos Hidalgo (NDS)`, run from nds_oof; texted too). `rerun nds_oof --week YYYY-MM-DD`.
- 10-24 Saturday credit checks until 11pm for Carlos's AT&T office (`icd_alerts/config.SELLING_END_OVERRIDES`; office mini self-update).
- 10-24 Saturdays: NDS from 10:15 (boards 10:15/10:30/10:45/11, then hourly); Carlos's AT&T sales reads from 10:30 (`icd_alerts/config.SALES_START_OVERRIDES`, lives on the office mini via self-update).
- 10-21/22 NDS board once per clock hour (the 9pm board had been skipped by 60-minute drift); extra 2:30pm board on weekdays (`nds_oof/config.EXTRA_BOARD_SLOTS`); `--no-gaps` hand-send.
- 10-19 (evening) BOX-1/2/3/4 now reply into the morning `Box Metrics — <Month D, YYYY>` thread (Carlos: "just post them in the metrics thread"); their own threads are fallbacks only. Morning job opens NDS threads only and pins the Box Metrics thread.
- 10-22 NDS board + 15-min gaps now reply INTO the morning `NDS Metrics` thread (own threads are pre-7:30 fallbacks only; the 7:30 job no longer opens them — `USE_NDS_METRICS_THREAD`). Verizon Metrics thread holds until after Lucy's 6am weather post (sales_boards gates it to 6:10+). The morning set — NDS Metrics, Box Metrics, Weather post, Tableau Country Trackers, Verizon Metrics — pins itself on post (`shared.slack_metrics_post.pin_message`); unpinning yesterday's still needs the `pins:read` scope, so old pins accumulate until Megan adds it.
- 10-21 **NDS Metrics thread** live: daily `NDS Metrics — <Month D, YYYY>` thread in #alphalete-gp-sales (the B2B Metrics thread's replacement, which stopped 10-21). Eight boards, crew-only: Revenue Board, Order Log, Activation Report Overview, Activation Revenue Overview, Activation Rate by Rep, Pending Orders, Churn Rates, Churn by Rep. Data: NDS-SN ORDERLOG (owner Carlos) + Carlos's own SaraPlus on Lucy 2; dollars = ATT-D2D-OOF SOW base comp (Tier 3-3). Code `automations/nds_metrics/` (Lucy 2); hand run `rerun nds_metrics -- --dm U046G04P5LG` (previews) / `-- --post`. Scheduled daily 7:30 Mon–Sat. Sales Metrics removed (Carlos 10-21). Order Tiered Bonus not built (the NDS SOW has no volume-tier bonus to rank).
- 10-19 Fiber → NDS: new `nds_oof` module on Lucy 2 off Carlos's own Ownerville (RES AT&T OOF = id 1); Fiber guest rooms and the Raf-SaraPlus sales feed switched off; morning threads now NDS. Campaign id found via `b2b_dispositions --probe-picker` (the id scan can't see it).
- **11/6** `nds_oof --recap-week`: last week's Mon–Sat board + the six end-of-day boards posted as one thread in #a-players-b2b (10/26–10/31; Mon 8:31 PM, Tue–Thu 9:01 PM, Fri 9:00 PM, Sat 5:03 PM). Reusable any week.
