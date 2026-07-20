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
| `com.alphalete.new-start-followup-sat` | Sat 10:00 / 13:00 | replies in the thread, tagging **only** leaders who still haven't sent |
| `com.alphalete.new-start-followup-sat-pm` | Sat 17:00 | same, the last call of the day |
| `com.alphalete.new-start-followup-sun` | Sun 13:00 | posts the numbered ✅ roll-up + tags whoever is still out |

All four go through `deploy/new_start_followup.sh` →
`automations.new_start_followup.run`. Wording for the Saturday pings is picked
from the clock (`--when auto`), so they don't need separate flags.

**Why the 5pm ping is a separate plist.** `schedule_guard` treats any job with
**more than 2 calendar intervals** as a high-frequency poller and skips it
(`schedule_guard.py` → `_timed_schedule`) — which would leave a single
3-interval job outside the nightly anti-drift reload that exists because timed
jobs on the mini have silently drifted before. Two intervals here + one there
keeps both inside it. **Don't merge them back into one plist.** Confirm coverage
any time with `lucy rerun schedule_audit` — all four should be listed.

Installed on the mini (**Lucy 1**) with `lucy update` then
`lucy rerun install_new_start_rollcall_agent` /
`install_new_start_nudge_agent` / `install_new_start_nudge_pm_agent` /
`install_new_start_checklist_agent`.

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
  Friday anchor post → replies after the Saturday roll call matching `/sent/i`.
  The `xN` in "sent x4" is read as the claimed count. Aisha's hand-typed roll
  call is still recognised if she posts one, so a transition week parses either
  way; with no roll call at all, everything under the anchor counts.
- **Name mapping** — `automations/new_start_followup/leaders.json`.

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

- **Unable to tag — needs a manual reach-out** — an interviewer in OBCL column B
  with no Slack account to @-mention. Goes in **both** the Saturday roll call and
  the Sunday checklist: if nobody can tag them, their new start silently goes
  untexted unless a human chases them. Clears once they're in `leaders.json`.
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

## Texting the stragglers (Lucy 1 only)

The Sunday half: after the checklist posts, iMessage everyone still missing.

```bash
# see the exact text each person would get — sends nothing
python -m automations.new_start_followup.run --mode text

# actually send, from Lucy 1
python -m automations.new_start_followup.run --mode text --send
```

Or the Hub card's **Preview Texts** / **Text Stragglers** buttons.

**Not on a timer, on purpose.** These are personal messages from a real phone
number to ~20 people, so they go out when a human asks — never on a schedule.

### Phone numbers

Numbers come from **Lucy 1's Contacts app** (they're not in OBCL, and Slack
profiles don't carry a phone). Resolve them once:

```bash
# on Lucy 1 — dry-run first
python -m automations.new_start_followup.contacts
python -m automations.new_start_followup.contacts --write
```

or remotely: `lucy rerun fill_leader_contacts`.

They're cached to **`~/.config/recruiting-report/new-start-leader-phones.json`**,
keyed by Slack ID — **machine-local and outside the repo on purpose, because
this repo is PUBLIC on GitHub.** Never put a phone number in `leaders.json`.
`roster.load()` merges the overlay, so `leader.phone` reads the same either way;
on a machine without it every number is blank and the texting step reports
"no number on file" rather than skipping people silently.

Contacts access needs macOS Automation permission. If the fill returns `-1743`,
somebody has to approve it once at the mini — that's why it's resolved ahead of
time instead of at send time, where a TCC prompt would hang a headless run.

A leader is only auto-filled when the contact name matches a spelling already in
`leaders.json` **and** exactly one distinct number comes back. Two numbers under
one name is reported, not guessed.
