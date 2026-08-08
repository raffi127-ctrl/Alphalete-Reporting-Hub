# New-Start Follow-Up

Makes sure every Monday new start gets a text from the person who ran their
2nd-round interview — and tells Raf who didn't send.

## The manual loop this replaces

| When | Who | What |
|---|---|---|
| Fri ~4:54pm | Aisha | posts **"D2D Alphalete New Starts Scheduled for Monday"** in `#rafs-office-recruiting` with the copy/paste script |
| Sat 8:00am | **Aisha** | replied in that thread @-tagging every leader |
| Sat all day | leaders | reply `Sent` / `sent x4` as they text their new starts |
| Sat ~10am/1pm/5pm | **Raf** | pings the leaders chat to chase stragglers |
| Sun ~1:00pm | **Raf** | hand-builds a numbered ✅ checklist, then texts whoever is missing |

The **bold** rows are what this automates. Aisha still posts Friday's anchor;
Lucy took over the Saturday 8am tagging on 7/19/2026 (Raf's call) because the
hand-built list was under-tagging — on the 7/20 week it missed 4 leaders who had
new starts.

## What runs

| Job | When (Central) | Does |
|---|---|---|
| `com.alphalete.new-start-followup-rollcall` | Sat 08:00 | @-tags **every** leader with a new start, each with their count |
| `com.alphalete.new-start-followup-sat` | Sat 13:00 | ONE nudge, tagging **only** leaders who still haven't sent |
| `com.alphalete.new-start-followup-sun` | Sun 13:00 | posts the numbered ✅ roll-up + tags whoever is still out |

All three go through `deploy/new_start_followup.sh` →
`automations.new_start_followup.run`. The Saturday nudge uses `--when morning`
(the neutral "Reminder — if you haven't texted…" wording that reads right for a
lone nudge).

**Ping budget (why one Saturday nudge, not three).** Until 2026-07-26 the
Saturday nudge fired at 10:00 / 13:00 / 17:00 (a `-sat` plist with two intervals
plus a separate `-sat-pm` plist for the third, to stay under `schedule_guard`'s
2-interval poller cutoff). That meant a leader who hadn't replied got @-tagged
**5×** in a weekend (8am roll call + 3 nudges + Sun checklist). Megan flagged it
as too many pings, so it was cut to a single 1pm nudge — now ~3 tags max. The
`-sat-pm` plist is **retired** (`lucy rerun uninstall_new_start_nudge_pm_agent`);
with one interval left, `-sat` no longer needs the split. Confirm coverage any
time with `lucy rerun schedule_audit` — rollcall, sat, and sun should be listed
(sat-pm should NOT).

Installed on the mini (**Lucy 1**) with `lucy update` then
`lucy rerun install_new_start_rollcall_agent` /
`install_new_start_nudge_agent` / `install_new_start_checklist_agent`.
To stop the retired 5pm ping on the mini:
`lucy rerun uninstall_new_start_nudge_pm_agent`.

The roll call is **idempotent**: it looks for its own marker
(`New-Start Texts — Roll Call`) in the thread and no-ops if one is already
there, so a re-fire can't tag 21 people twice. `--force` overrides.

## Sources

- **Who owes a text** — workbook `D2D OBCL`
  (`1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4`) → tab `D2D OBCL <M>.<D>`
  (the one whose A1 holds the Monday date) → header row 2 → column B
  **"2ND Round Interviewer"**, one row per new start. Rows whose column J
  "Final Status" is declined/cancelled/no-show/rescheduled don't count.
- **Who already sent** — `#rafs-office-recruiting` (`C06881A7WLV`) → Aisha's
  Friday anchor post → replies after the Saturday roll call matching
  `/sent|done/i` (some leaders reply "Done!" instead of "Sent").
  The `xN` in "sent x4" is read as the claimed count. Aisha's hand-typed roll
  call is still recognised if she posts one, so a transition week parses either
  way; with no roll call at all, everything under the anchor counts.
  Since 2026-08-03 the reach-out list actually comes from **Aisha's weekly
  screenshot** in that thread (read via Claude vision), because the live tab
  carries not-moving-forward + duplicate rows. The sheet is still cross-read for
  one thing: an interviewer who is **on the sheet, not on the screenshot, and
  not taggable** is added to *"Unable to tag — needs a manual reach-out"*. That's
  how a row hand-added to the sheet after the screenshot went up (Megan's
  Quigley Nolan, 2026-08-08) still gets chased instead of vanishing. Such a name
  can never become an @-mention — the screenshot alone decides who gets tagged.
- **Name mapping** — `automations/new_start_followup/leaders.json`.
- **Who's left the company** — replayed from `channel_join` / `channel_leave`
  events in the channel history. Lucy's token has no `channels:read`, so
  `conversations.members` isn't available; history is. State accumulates in
  `output/new_start_membership.json` so an old leave isn't forgotten once it
  scrolls out of the scan window. **Silence means present** — only an observed
  leave marks someone gone, because wrongly writing off an active leader would
  mean their new starts never get chased.

## Commands

```bash
# print the current picture, no writes at all — safe any time
python -m automations.new_start_followup.run --mode status

# preview any of the posts
python -m automations.new_start_followup.run --mode rollcall
python -m automations.new_start_followup.run --mode nudge --when midday

# actually post (nothing posts without --live)
python -m automations.new_start_followup.run --mode rollcall --live
python -m automations.new_start_followup.run --mode nudge --when auto --live
python -m automations.new_start_followup.run --mode checklist --live
```

## Adding a leader

When someone new starts running 2nd rounds, add them to
`automations/new_start_followup/leaders.json`:

```json
{
  "slack_id": "U0…",
  "name": "Firstname Lastname",
  "short": "Firstname L",
  "obcl_names": ["every spelling that shows up in OBCL column B"],
  "phone": ""
}
```

Lucy's Slack token has no `users:read` scope, so a scheduled run **can't** look
names up live — that's why the file exists. Until someone is in it, the report
flags them under *"In OBCL but no Slack match"* rather than silently skipping
them.

## Flags it raises

Posted into Slack (the team should see these):

- **No longer a channel member** — the interviewer has left
  `#rafs-office-recruiting`. They are **never @-tagged, nudged, or texted**, and
  they don't count against the "N of M have sent" score. Their new starts are
  listed by name so somebody else picks them up.
- **Unable to tag — needs a manual reach-out** — an interviewer in OBCL column B
  with no Slack account to @-mention. Goes in **both** the Saturday roll call and
  the Sunday checklist: if nobody can tag them, their new start silently goes
  untexted unless a human chases them. Clears once they're in `leaders.json`.
  **Don't add a departed interviewer to `leaders.json` to clear it** — that turns
  the line into an @-mention of someone who has left. Leaving them here is the
  intended end state (Megan, 2026-08-08, re: Quigley Nolan).
- **Count looks short vs OBCL** — replied "Sent x2" but OBCL assigned 3.
- **Has new starts but wasn't tagged** — nobody ever asked them.

Console/log only, never posted — these are plumbing, not performance:

- **In OBCL but no Slack match** — the maintainer-facing half of the same
  finding: add them to `leaders.json`.
- **Tagged but not in leaders.json** — an unknown leader got tagged.

A leader who replies `Sent (Name)` is read as covering for **Name** — that
leader is credited instead of nudged (Raf's Sosa case).

## If it fails

Exit 2 means Aisha hasn't posted Friday's anchor yet. Everything hangs off that
post, and it refuses to post rather than guess at the wrong thread. Check the
channel, then re-run.

## Texting the stragglers — PARKED (no active iMessage)

Raf's Loom floated texting the leaders who still haven't sent, straight from a
Lucy phone number. **Parked 2026-07-22: there's no active iMessage number to
send from.** The report chases stragglers purely by **tagging them in the Slack
thread** (the roll call + the three Saturday nudges), which is Raf's core ask.

The code is still in the tree but fully unwired — no CLI mode, no Hub buttons,
not in the registry:

- `texts.py` — composes/sends the per-leader iMessage.
- `contacts.py` — resolves leader numbers from the mini's Contacts app.
- `obcl.phone_book()` + the phone plumbing in `roster.py` — the number lookup.

To revive it if a number is added later: re-add the `text`/`--send` mode to
`run.py`, the two Hub buttons, and the `fill_leader_contacts` registry entry.
Numbers come from the OBCL sheet (past new starts) — never stored, since the
repo is public.
