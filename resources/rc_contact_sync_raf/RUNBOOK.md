# Runbook — Raf Wrap-Up Check (`rc_contact_sync_raf`)

The B2B Customer Contacts report (`rc_contact_sync`, Carlos's office),
mirrored for **Raf's office** and checked against **Dylan's** RingCentral line.
"Who sent a wrap-up and who didn't," for every rep selling under Raf's code.

## What it does, in one line
For each sale under Raf's SaraPlus code yesterday (all reps) → was the customer
ever messaged on Dylan's RingCentral line? → the ones who weren't go to
**#alphalete-sales**, grouped by rep.

## The two accounts (both easy to get wrong silently)
- **SaraPlus = Raf's dealer** (`alphaletemarketing@gmail.com`,
  `saraplus-creds.json` + the verified `.saraplus_profile`). This login only
  works on **Lucy 1**, and it has no emailed-passcode step there. This is why
  the pull runs on Lucy 1. (Same login the sales board / `sp_order_log.raf_guest`
  already use.)
- **RingCentral = Dylan's account** — the SAME one baked into
  `automations/rc_autoread/run.py` (main +1 214-845-6450, ext 62883924016,
  owner_id 62672491016). The run verifies owner_id before it posts; a token for
  any other user is refused.

## Why there is no contacts step
Carlos's version also writes each customer into Taylor's RingCentral address
book. Dylan's RingCentral app holds `ReadMessages ReadAccounts EditMessages`
but **not** `ReadContacts` — the address-book API returns 403. The wrap-up
check needs only `ReadMessages` and works today. To add the contacts half
later: in the RingCentral developer console, add `ReadContacts` + `Contacts`
to Dylan's app, re-mint the JWT, and mirror `rc_contact_sync`'s contacts block
into `run.py`. Nothing else changes.

## Daily flow — both steps on Lucy 1, in order

```
# 1. Pull Raf's full Sales Order History -> control sheet (Lucy 1 only)
python -m automations.rc_contact_sync_raf.pull_raf --pull

# 2. Wrap-up check + Slack post (any box; run on Lucy 1 right after the pull)
python -m automations.rc_contact_sync_raf.run --live
```

A bare `run` (no `--live`) is a DRY RUN: it prints exactly what it would post
and posts nothing. `run --probe` is read-only (proves identity + shows counts).
`pull_raf --show` reads the handoff back without re-pulling.

## Scheduling (to make it "100% automated")
Schedule both on **Lucy 1**, Mon–Sat, in the morning before the metrics flow —
e.g. the pull at **4:00 AM** and the run at **4:10 AM** Central (the pull takes
a few minutes; the run is seconds). Register them the same way the other Lucy
reports are scheduled (the mini's day-orchestrator / LaunchAgent, driven from
the Mini Control sheet). The handoff is good for 26h, so the run always has a
fresh pull to read; if the pull is missing or stale the run fails loudly rather
than posting "everyone texted."

## When something looks off
- **"no Raf all-orders pull / STALE"** → the Lucy 1 pull didn't land. Run
  `pull_raf --pull` on Lucy 1 (or the Hub card's **Refresh Raf pull**).
- **"token belongs to extension id X, not 62672491016"** → the RingCentral JWT
  isn't Dylan's. It's read from `rc_autoread`, so fix it there.
- **"missing the ReadMessages scope"** → the app's scopes changed; re-mint the
  JWT with ReadMessages.
- **Everyone shows as un-texted** → almost always the message read returned
  nothing (scope/token). The run guards against this, but if a post ever looks
  that way, check `run --probe` first.

## Files
- `pull_raf.py` — Lucy 1: pull Raf's SOH (all reps) → control-sheet handoff.
- `customers.py` — decode the handoff → customer rows (reuses
  `rc_contact_sync.guest`'s header/date helpers).
- `run.py` — identity check → message read → `texted_any` → Slack post.
- `config.py` — the ids, the channel (#alphalete-sales), the handoff tab.
- Reused from `rc_contact_sync`: `ringcentral.sms_since` / `texted_any`,
  `run.missing_names_reply`. Reused from `sp_order_log`: `raf_guest.pull`.
