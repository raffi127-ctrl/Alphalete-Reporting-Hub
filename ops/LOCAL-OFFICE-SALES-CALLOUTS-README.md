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
| One date on another day's rules | `shared/day_override.py` → `TREAT_AS_SATURDAY` (+ the date line in `deploy/gap_alerts_5min.sh`) | both |

Deploy flow: commit → `git push origin HEAD:main` → queue `update` on the
machine (Google-Sheet queue, tabs "Mini Control" = Lucy 1, "Mini Control -
Lucy 2") → verify by `logtail`. See `~/alphalete-readmes/LUCY2-OPERATIONS-README.md`.

---

## 5. Hand commands (queue `rerun …`)

| Command | Machine | Does |
|---|---|---|
| `b2b_dispositions --morning --send` | Lucy 2 | Open today's threads, post yesterday's boards, pin |
| `b2b_dispositions --backfill-yesterday "Fiber Knocks Board" --send` | Lucy 2 | Put yesterday's final board into today's thread of that name |
| `b2b_dispositions --delete-loose "<prefix>" --send` | Lucy 2 | Delete TODAY's loose Lucy posts starting with prefix (never thread parents) |
| `b2b_dispositions --which gaps --text --headless` | Lucy 2 | Dry run of the Box gaps (resolves the chat, posts nothing) |
| `sales_board_standings` | Lucy 1 | Raf's board + crew standings now (read-only, no lock) |
| `sales_board_standings --week 2026-09-28 2026-10-04` | Lucy 1 | Crew sales per day / per rep for a range (state keeps 10 days) |
| `gap_alerts --force --only rafael` | Lucy 1 | Preview a Fiber pass (sends nothing) |
| `vantura_payroll --refresh-only` | Lucy 2 | Rebuild the payroll Commission tab after hand-written Adjustments |

---

## 6. Known issues / gotchas

- **Unpinning needs `pins:read`** on the Lucy Reporting Slack app (pinning works). Until Megan adds the scope, yesterday's pins stay.
- **Lucy 1 is slow some days**: each Fiber pass can take ~10 min, so "every 15 min" lands every 20–30. The sales sweep holds a lock most of each 5-minute cycle; use `sales_board_standings`, not `alphalete_sales_board …`, for reads.
- **BOX-1 needs the office mini**. "last relayed … too old" in Lucy 1's poster log = the mini is asleep/off/logged out.
- **Hourly Fiber board stops at 8:08pm**: the hourly anchor lands at :05 and the window ends 9:00. Set `stop` to `21:10` if a 9pm board is wanted.
- **Thread title formats differ on purpose**: Lucy 2's are `Prefix M/D/YY`; the two Lucy 1 posts into are `Prefix — Month Dth YYYY`. Each job looks up its own format.
- **The b2b_dispositions reply dedupe** matches the caption at the START of a reply (a `"2 PM" in "12 PM"` bug used to skip 2pm posts).
- **Never post blank**: gap lists and the gaps text skip a slot when nobody is over 15 minutes.
- **A SaraPlus glitch sticks**: the sales feed only ever moves UP (so it never re-announces a sale). If Sara briefly shows a rep too high and then corrects, Lucy keeps the high number all day and the poster log says `BACKSLID … 8 -> 4` every pass. Fix from anywhere: queue on Lucy 1 (`Mini Control` tab) `icd_correct_sales carlos-b2batt "Andrew De La Torre" NL=4` (metric names: NL, Int, Int Up, DTV; Box uses Sales). The next standings text then carries the corrected number.
- **Texts stop but Slack keeps posting** = the queue sheet is the problem, not Messages. Since 10-26 texts use the local outbox, so this only happens if the poller itself is down (`restart_poller`). Pre-10-26 symptom: `text_dispositions` rows sitting `queued`.
- **2026-10-04** ran as a Saturday (one-off). The date in `shared/day_override.py` and `deploy/gap_alerts_5min.sh` can be removed; it's harmless to leave.
- **Payroll adjustments** (Vantura board, `Adjustments` tab): `Week | Rep | Type | Amount | Label`, Type ∈ {Bonus, NPA, REMOVEALL, REMOVELINE}; use the Commission-tab spelling of names; "bring up to $X" = Bonus of X − current commission; then `vantura_payroll --refresh-only`.

---

## 7. Change log

- 09-29 Split knocks from gaps; Box hourly → once a day; AT&T daily boards stopped; Fiber board + gaps texted hourly; Fiber sales/credit feed off Raf's SaraPlus (SAL-7/8).
- 09-30 Jacob Ortega added to the crew.
- 10-03 Labels BOX/FIB/SAL/ATT; Fiber Saturdays from 10:30; morning threads + pins; campaign-first names; FIB-3 every 15 min, BOX-3 every 30; FIB-2 hourly; Sebastian Avellaneda added; loose pre-thread posts deleted.
- 10-04 Sunday run as Saturday (one-off).
- 10-08 Yesterday's final Fiber board at the top of the morning Fiber thread; `--backfill-yesterday`; payroll `--refresh-only`.
- 10-29 **B2B Box tracker text OFF**: the daily Tableau Country Trackers run (Lucy 3, `tableau_screenshots --text-trackers`) was still texting the B2B Box board picture to Box B2B + NEW A Players through Lucy 2 (`text_tracker b2b_box`). Carlos: "i saw some box stuff go out … on the box text chain". `tracker_texts/config.ROUTES['b2b_box'] = []`; the Slack post in the Country Trackers thread stays. The NDS tracker text (ATT B2B Leaders + NEW A Players) is unchanged. This was never in the BOX-1..5 list — it is a Tableau tracker, not a disposition report.
- 10-28 **Box Order Log OFF** too (Carlos: "the whole thing can go"): `com.alphalete.box-order-log` unloaded on Lucy 2; Box Metrics thread + Vantura Lucy Box Order Log tab stop.
- 10-28 **Box OFF entirely** (Carlos). Three Lucy 2 Box agents unloaded, weekly Carlos B2B board off the Sunday scheduler, Box gaps text route blanked. NDS + AT&T sales reporting unchanged.
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
