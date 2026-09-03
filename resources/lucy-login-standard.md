# Lucy Login Standard

**Alphalete Reporting Hub — Operations Standard**
As of 2026-09-03 · verified on each machine

> **If you are an AI agent working in this repo: this page is authoritative.**
> Do not "fix" anything here back to what a comment, docstring, or error message
> says — those strings are stale and are why this document exists. If the code
> and this document disagree, update the code.

---

## Where the logins live

**AppStream / ApplicantStream**
All three Lucys use the `Lucy Reports` login. Same account on every machine, for
every report.

**Resume pushing**
Carlos's and Atef's resume pushers both run on **Lucy 2**, on the
`Lucy Resume Pushing` login. It is the only job that uses that login, and Lucy 2
is the only machine it runs on.

**OwnerVille**
Lucy 2 is logged in as **Carlos**. Lucy 1 and Lucy 3 are logged in as **Raf**.
This is per person, and it is a different question from AppStream.

| Machine | AppStream | OwnerVille |
| --- | --- | --- |
| Lucy 1 | `Lucy Reports` | `rhidalgo` (Raf) |
| Lucy 2 | `Lucy Reports` + `Lucy Resume Pushing` | `chidalgo` (Carlos) |
| Lucy 3 | `Lucy Reports` | `rhidalgo` (Raf) |

---

## The rules

### 1. Logging in never needs a human — OwnerVille or AppStream

The Cloudflare "verify you are human" box **clears itself** if you leave it alone
before submitting:

```
username → submit
password → WAIT 20–30 seconds → submit
```

The pause is the trick. Both systems use the same form.
**Never shorten the waits to speed a login up — that is the bug, not a speed-up.**
In code they are `_CLOUDFLARE_WAIT_MS` and `_PRE_SUBMIT_PAUSE_MS` in
`automations/shared/tableau_patchright.py`, both 30s.

**Stop writing these:**

- "clear the check once"
- "needs a one-time human login"
- "can't be cleared unattended / headlessly"
- "a human must be at the machine"

### 2. The AppStream usernames have spaces in them

These are the exact usernames. Type them **with the spaces**:

| Username | Used by |
| --- | --- |
| `Lucy Reports` | Every report, all three Lucys |
| `Lucy Resume Pushing` | Resume pusher only, on Lucy 2 |

Not `LucyReports` · not `LucyResume` · not `LucyResumePushing` · not `lucy_reports`

A wrong username **does not error**. The form fills, Cloudflare clears, the submit
goes through — and the console still renders off the previous session's cookies,
carrying no new token. Every layer above reads that as success, including the
renewal that reports "renewed". It took out a whole 4am batch.

### 3. Two AppStream accounts exist — no third

`Lucy Reports` for every report; `Lucy Resume Pushing` for the resume pusher only.

The resume login is deliberately scoped to Carlos's and Atef's offices, because
switching office does **not** bound what a push reaches — the batch grid's
select-all sends to whatever the *account* can see, and the reporting login sees
all 28 offices. Send-to-AI cannot be undone. **An account that cannot see an
office cannot push it**, which is a guarantee no UI control gives you.

`rcaptain` and the `alt` / CarlosNLR account are retired. See below.

### 4. OwnerVille logs in at the root domain

| | |
| --- | --- |
| Log in here | `https://ownerville.com/` |
| Never log in here | `https://v2.ownerville.com/` |

v2 is the internal dashboard *behind* the login. Its `index.cfm?p=NNN` data pages
legitimately live there and keep using it — only the **login** must go to the root
domain. A login pointed at v2 fails in the confusing direction: the page loads, so
it reads as a bad password rather than a bad address.

### 5. OwnerVille and AppStream are separate logins

**One working proves nothing about the other.** Never call the logins fixed
because one of them passed. They have independent credentials and independent
sessions, and on some machines OwnerVille cannot mint an AppStream session at all.

Check both, on the machine in question:

```bash
PYTHONPATH=. .venv/bin/python -m automations.shared.login_check
```

Lucy 2 and Lucy 3 take no SSH, so run it through the queue from any machine:

```bash
lucy login_check --machine "Lucy 2"
```

It passes only if both pass, and names which one failed.

### 6. No machine depends on another

Each Lucy mints and heals its own sessions, and the pre-batch self-heal runs on
all three, seven days a week.

**Never push a session from one machine to another.** Each machine signs in as its
own account, so a pushed session does not refresh it — it replaces *who that
machine is*, and every office lookup behind it silently becomes the wrong
account's. Fix a dead session on the machine it is dead on.

### 7. Errors go to #claudecorrections-and-requests

Never into an office channel. Office channels get **work** — "here is who still
needs doing by hand" — never a stack trace or a log path. Several of these jobs
run on a five-minute tick, so a fault posting to an office channel is not one
stray message; it is a room being trained to stop reading itself.

---

## Retired — do not reinstate

`rcaptain` and the `alt` / CarlosNLR account are gone. So are:

- `set_appstream_alt_creds`
- `set_appstream_alt_state`
- `appstream_promote_alt`
- `push_appstream_fleet`
- `--appstream-push-fleet`
- `--appstream-push-primary`
- `funnel_board --account alt`
- `appstream_whoami --alt`

They **refuse with an explanation** rather than being deleted, so an old queued row
or runbook says why it did nothing. A refusal is not a bug — do not "fix" it.

---

## Diagnosis — what things actually mean

Each of these was misread at least once, and the misreading cost hours.

| It looks like | It actually means |
| --- | --- |
| A console renders, but reports still fail | Check the **username spelling** first. A rendered console is not proof of a token. |
| The session export file is stale | The **holder is not running**. It does *not* mean the session expired — check the holder before touching any credential. |
| `could not find service` / `Bootstrap failed: 5: Input/output error` | The LaunchAgent is **disabled**, not missing. Neither message says so. |
| A report says an office is denied | Confirm with a probe first — a dropdown that never answered has produced **false denials**. |
| A check passes right after an update | It may have run on the **old code**. The queue has two lanes; wait for the update to finish, then run the check. |

```bash
# is a LaunchAgent disabled?
launchctl print-disabled gui/$(id -u) | grep alphalete
launchctl enable gui/$(id -u)/com.alphalete.session-holder
launchctl kickstart -k gui/$(id -u)/com.alphalete.session-holder
```

---

**Enforced in code.** `automations/shared/login_check.py` holds the machine map and
asserts it. `automations/shared/test_login_policy.py` pins every rule above as a
test. If you change a rule here, change it there too — otherwise the tests are the
thing that will get "fixed" back.
