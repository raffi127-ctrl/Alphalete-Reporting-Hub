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
| 3. Email, iMessage, or both | `destinations[]` | one entry per place, each `{kind, name, channel_id, emails, cadence_min}`, straight into `gap_alerts.run`'s send loop |
| 4. Every 15 / 30 / 60 min | `destinations[].cadence_min` | `run._dest_due` → the per-destination due check |
| 5. Hourly Slack channel | a `slack` destination with `cadence_min=60` | same list; Slack is not a separate concept |

**SLACK AND EMAIL ONLY** (Megan 2026-09-02: *"take the option they have of
getting an imessage out of this form. it's only slack and email so my number
can also be removed"*). `schema.FORM_DELIVERY_CHOICES` is what the form offers;
`schema.DELIVERY_CHOICES` still carries `imessage` because the **runner** texts
— Raf's board goes to Alphalete Partners, Calvin's and Jay's to ENERGY WELLS
DOMINATION — and a sign-up taken before that date may still carry one, which
the confirm view has to render. What changed is only what an owner can create.

A destination's cadence can also be **`0` = fixed times** (Cody Cannon's 2:00
PM first knocks / 5:15 money lap / 9:00 end of day, read from
`knocks_intraday.schedule.SLOTS`), matched against the office's own clock.
`0` is falsy — `cadence or 15` turned three boards a day into ninety, and there
is a test named for it.

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
   pulls its board (and resolves the iMessage room, on an older sign-up that
   still carries one). It holds → the office is switched **on** and the result
   is posted to #claudecorrections-and-requests. It fails → the office stays
   off and the post says which check failed.
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

## Campaigns, and what is not wired yet

| Campaign | `invD2DClientId` | Box | State |
|---|---|---|---|
| D2D — AT&T Fiber (Internet & Phones) | 3 | Lucy 1 | live |
| D2D — Energy Wells | 40 | Lucy 1 | live |
| D2D — NDS Wireless | 3 | Lucy 1 | live since 2026-09-02 |
| B2B — AT&T | 2 | Lucy 2 | **enrollable, not running** |
| B2B — Box Energy | 16 | Lucy 2 | **enrollable, not running** |

**NDS pins 3 (RES AT&T) like every other knocks office.** It used to carry no
id and sit on the waiting list, and both halves of that were wrong. NDS names
the *business*, not the campaign: Megan read Isaiah Revelle's own OwnerVille
picker on 2026-08-25 (BASE Energy / RES AT&T / RES-ENERGYWELL) and his reps
knock RES AT&T like everyone else — the same default `knocks_pull` carries. And
an empty id never meant "this office's own campaign": the campaign is a sticky
session-global, so it meant "whatever the office before it in the batch
pinned". What an NDS office gets is a *smaller* board, not no board — those reps
mostly knock without dispositioning, so `p=89` comes back empty, `knocks_pull`
builds the rows from the Time Tracker instead and the renderer draws the Time
Gaps board alone (`render.SHAPE_GAPS_ONLY`). The form says so where they pick it.

**B2B takes sign-ups but cannot post yet.** Three things are in the way, and
`schema.b2b_blockers` prints all three on the confirm view so the decision is
made with them in front of you:

1. **No runner.** `gap_alerts` has one LaunchAgent — `com.alphalete.gap-alerts`
   on Lucy 1. The `gap_alerts_b2b` schedule entry and Hub card exist so the
   report has an id to hang on, but nothing on Lucy 2 ticks.
2. **The B2B Disposition grid has never been mapped.** `knocks_pull` knows the
   fiber, wireless and Energy Wells column sets. A B2B grid carries Total
   Knocks and no house Talk-To split, so it *satisfies* `_is_wireless_dispo`,
   and the wireless scrape is tolerant by design — which means it would have
   rendered a clean, plausible board with `0` in every disposition column. It
   now raises instead (`_is_b2b_dispo`, keyed on the B2B-only `Corp - No Opp`
   column). To map it, from **Lucy 2**, outside the b2b_dispositions hours
   (Mon-Sat 12-7pm):

   ```bash
   python -m automations.gap_alerts.run --probe-campaigns --office "<owner>" --campaign 2
   ```

   (and again with `--campaign 16`), then add `_B2B_COLUMNS` / `_B2B_COUNTS` /
   `_B2B_TALK_TO_PARTS` beside the Energy Wells set, a `SHAPE_B2B` in
   `total_knocks.render`, and delete the guard. Pass `--campaign` — unpinned,
   the probe dumps whatever campaign the box was last left on.
3. **iMessage does not work from a LaunchAgent on Lucy 2.** macOS granted
   "control Messages" there to the poller's executable identity
   (`.venv/bin/python`), not to a `/bin/bash` wrapper — which is why
   `b2b_dispositions` hands its sends to the poller through a manifest.
   `gap_alerts` texts inline, so that route would block on an unattended
   consent dialog. Moot for new sign-ups now that the form is Slack + email
   only; it still matters for any B2B row added by hand.

## Timezones changed the wrapper

`deploy/gap_alerts_5min.sh`'s hour gate exits before Python runs, so it can no
longer be "the schedule" — it is now an **envelope** (Central 12:00-23:00
weekdays, 09:00-21:00 Saturday) around every supported zone, and
`config.in_office_window` makes the exact per-office call. Pacific is not
offered on the form: its 10 PM lands at midnight Central, a different calendar
day.

## A push is not always a deploy — REBOOT after changing `automations/`

Streamlit Cloud's "Updated app!" on a push re-runs **`app.py` only**. Anything
already imported — everything under `automations/disposition_signup/` — stays
the module object the process imported at boot. So a commit that changes
`app.py` AND `schema.py` together deploys half of itself: the new page calling
the old module, which fails as
`AttributeError: module '...schema' has no attribute '...'` (2026-09-01).

The fix is a real reboot: **Manage app → ⋮ → Reboot app**, which reclones and
restarts the process. Same failure family as the Hub's stale-getsource restart.
Rule of thumb: touched only `app.py`, the push is enough; touched anything in
`automations/`, reboot.

## Local

```bash
.venv/bin/streamlit run disposition_signup/app.py          # saves a local draft
DISPOSITION_SIGNUP_LOCAL_ONLY=1 .venv/bin/streamlit run disposition_signup/app.py
.venv/bin/python -m pytest automations/disposition_signup/ -q
```

Secrets for the Cloud deploy: `[gcp_service_account]` or `[gcp_oauth]` (master
sheet), `slack_user_token` **top-level, above any `[section]`** (the ping + the
Lucy membership check), `disposition_signup_code` (confirm gate).
