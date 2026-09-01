# Daily Dispositions Sign-Up

The enrollment link an office owner fills in to start getting their own
**KNOCKS & DISPOSITIONS** board — Raf's five questions from the #11280
"Webform" thread (2026-09-01), answered as a link rather than a web form
(Megan, same thread: *"we have enrollment links not web forms"*).

- **Owner-facing:** `disposition_signup/app.py`
- **Megan's confirm view:** the same app at `?confirm=<office key>`, gated by
  the `disposition_signup_code` secret
- **Deploy:** Streamlit Community Cloud, subdomain `alphaletedispositions`
- **Linked from the Hub:** Office Operations → *Daily Dispositions Sign-Up*

## The five questions → what they wire

| Raf's question | Field | Where it lands |
|---|---|---|
| 1. ICD first + last name | `owner` | the office key + how impersonation resolves the office |
| 2. Applicant / owner ID | `ov_account` | carried for Megan; optional on purpose (the name is what resolves) |
| 3. Email, iMessage, or both | `deliver`, `email_to`, `imessage_group` | the two send legs in `gap_alerts.run` |
| 4. Every 15 / 30 / 60 min | `cadence_min` | `gap_alerts.config.cadence_for` → the per-office due check |
| 5. Hourly Slack channel | `slack_hourly`, `slack_channel_id` | `gap_alerts.config.slack_channel_for` |

Three more the other intake forms taught us to ask (they are not in Raf's list,
and each one is a way an enrollment silently half-works without them):

| Also asked | Why |
|---|---|
| Office name in OwnerVille, if different | impersonation resolves through it — the same `knocks_office` split `office_onboarding` carries |
| Time zone | four offices here are Eastern; the windows used to be hardcoded Central, so an Eastern office would have lost its last hour |
| Field hours (Mon-Fri + Saturday) | the org default is Raf's 1:30-10 / Sat 10:45-6:30; an office that knocks different hours would otherwise be texted into an empty evening |

## The flow

1. Owner submits → row on the **Disposition Signup** tab of the AUTOMATION
   MASTER sheet as `status=pending`, plus a heads-up in
   #claudecorrections-and-requests with a `?confirm=<key>` deep link.
2. Megan opens that link, sets the campaign (this pins `invD2DClientId` — a
   wrong pin silently reports the wrong business), ticks **Office Access is
   granted**, and confirms.
3. Confirm flips the row to `wired` and enqueues `onboard_apply disposition
   <key> --post`, which on the runner: applies the row into the working tree
   (`automations/gap_alerts/onboarded_offices.json`, merged into
   `gap_alerts.config.OFFICES` at import), then **preflights** it.
4. Preflight (`disposition_signup.preflight`) impersonates the office and
   resolves its iMessage room. Both hold → it switches the office **on** and
   posts the result to #claudecorrections-and-requests. Either fails → the
   office stays off and the post says which check failed.
5. The next tick picks it up. The nightly auto-commit
   (`tracker_onboarding.auto_commit`, 03:15 + 17:30 on Lucy 1) commits the
   registry, so it survives `lucy update`.

Megan's part is one click on the confirm link. Everything after it is the
runner's.

## Two things the form can't know, and how they get settled

- **Office Access.** Impersonation has to be granted in OwnerVille, which is
  invisible from a Streamlit deploy. So a confirmed office is wired
  `enabled=false` and the runner's preflight is what turns it on — an office we
  cannot impersonate fails *every* tick and opens incidents instead of posting.
  (There is a "skip the check, switch it on now" override for when you have
  already verified it yourself.)
- **The campaign.** The OwnerVille campaign is a sticky session-global that any
  other job on the box can move, so every pull re-pins it. The form asks in the
  owner's words ("AT&T" / "Energy Wells"), Megan confirms the id, and the
  preflight's board pull is what proves the grid has the columns the scraper
  needs.

## Timezones changed the wrapper

`deploy/gap_alerts_5min.sh`'s hour gate exits before Python runs, so it can no
longer be "the schedule" — it is now an **envelope** (Central 12:00-23:00
weekdays, 09:00-21:00 Saturday) around every supported zone, and
`config.in_office_window` makes the exact per-office call. Pacific is not
offered on the form: its 10 PM lands at midnight Central, a different calendar
day.

## Local

```bash
.venv/bin/streamlit run disposition_signup/app.py          # saves a local draft
DISPOSITION_SIGNUP_LOCAL_ONLY=1 .venv/bin/streamlit run disposition_signup/app.py
.venv/bin/python -m pytest automations/disposition_signup/ -q
```

Secrets for the Cloud deploy: `[gcp_service_account]` or `[gcp_oauth]` (master
sheet), `slack_user_token` **top-level, above any `[section]`** (the ping + the
Lucy membership check), `disposition_signup_code` (confirm gate).
