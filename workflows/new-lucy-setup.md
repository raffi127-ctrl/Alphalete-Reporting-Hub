# Setting up a new Lucy (Lucy 5 and after)

The whole process, as it actually went on Lucy 4 (2026-09-17 → 09-19), with every
fix it needed folded in. Lucy 4 came up healthy on the first morning, after
Lucy 3 ran nothing for four hours on its first morning. Follow this in order.

`workflows/lucy4-provisioning.md` keeps the long reasoning. This page is the
checklist.

---

## 0. Before the machine exists — two edits, from Megan's laptop

1. **`automations/shared/fleet.py`**: append a `Machine(...)` for the new box.
   Copy Lucy 4's entry and change the name, badge and OwnerVille account.
   **Every capability flag stays OFF** (`holds_appstream`, `runs_appstream`,
   `can_text`, `morning_clock_since=None`). They're turned on at go-live, one at a
   time.
2. **`automations/dashboard.py` `MEMBERS`**: add its profile card with a new
   ring colour and badge. The Pack's top row fills itself in from this list.
3. Run `python -m unittest automations.shared.test_fleet`. It fails if either
   edit is missing. Commit and push.

Decide which **OwnerVille account** the box uses (Raf `rhidalgo` or Carlos
`chidalgo`). It sets whose numbers the reports show, not just whether they run.

## 1. At the new machine — one line

Log in as the machine's own user, open Terminal, paste (put the right name at
the end):

```bash
curl -fsSL https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main/deploy/lucy_walkthrough.sh -o /tmp/lucy.sh && bash /tmp/lucy.sh Lucy 5
```

It walks the person at the machine through everything, and it can be re-run:
closing the window is fine, because it skips any step that's already done. What it
asks for:

- **Mac password, GitHub sign-in, Google sign-in.** For Google, use
  **alphaletereporting@gmail.com**, never a personal account.
- **Four switches:** FileVault **off first** (macOS greys out automatic login
  until it's off), then automatic login, then signing in to Messages as
  alphaletereporting@, then Remote Login.
- **One Allow click** for Messages.
- Credentials come over from Lucy 1. **Nobody types a password.**
- It checks its own work, including waiting 6 minutes to prove the OwnerVille
  session is being refreshed rather than just existing.

## 2. On Megan's laptop — one line

The script prints the exact command at the end. It looks like this:

```bash
ssh-copy-id lucy5@Lucys-Mac-mini-3.local
```

It asks for the new Mac's password once. After that, Claude can log in directly.

## 3. Claude verifies (tell it "Lucy N is done")

Each of these is a real check, and passing the step before doesn't count:

| Check | How | Pass |
|---|---|---|
| Logins | `lucy login_check --machine "Lucy N"` | "BOTH logins are live" (AppStream reads "off on purpose") |
| Setup | over SSH | autoLoginUser set · `fdesetup` Off · `pmset autorestart 1` |
| Remote restart allowed | `sudo -n /usr/bin/pmset -g` over SSH | succeeds. **Don't test with `sudo -n true`**: the rule only covers pmset/shutdown/reboot, so that test fails even when it's set up right |
| Session refreshing | `diag` twice, 6+ min apart | the age is **younger** the second time |
| Texting | re-run the Messages step (**ask Megan first**: it posts a line and a picture to Admin Staff) | both arrive → set `can_text=True` in fleet.py |
| **Survives a restart** | `sudo -n /sbin/shutdown -r now` over SSH | **uptime shows a fresh start**, the screen user is the Lucy, all 5 jobs are loaded, the session file is fresh, the queue answers |

Prove the restart with **uptime**. "The jobs are loaded" is also true of a
machine that never went down. On Lucy 4 it was called passed before it had
actually happened.

## 4. Resume extension for AppStream ("Resume Helper")

Megan, 2026-09-19: new Lucys also need the resume extension for AppStream. It's the
little **robot icon** at the right edge of the AppStream console, just under the
office picker.

| | |
|---|---|
| Name | **Resume Helper** |
| What it says it is | "Internal ApplicantStream plugin for MFA users to extract resume data…" |
| Chrome extension id | `goofbdglmeckblcbcoffnkdnmpehhhmo` |
| Version seen | 1.0.9 (on Megan's laptop, Chrome Profile 20) |
| Runs on | `*.applicantstream.com/index.cfm*`, `*.indeed.com/*`, `employers.indeed.com` |
| Install page (unverified) | https://chromewebstore.google.com/detail/goofbdglmeckblcbcoffnkdnmpehhhmo |

**Where it goes — settled 2026-09-19** (the "Resume pushing offices" session,
checked against `automations/resume_pushing/run.py`):

1. Install it in **regular Google Chrome, Default profile**, logged in as the
   Lucy's own Mac user. **Not** Chrome for Testing: applicant push doesn't use
   that. `_copy_default_profile()` copies the everyday Default profile ("holds
   the Resume Helper plugin + the live login") into its own working copies
   under `/tmp` (`/tmp/rp_cdp_*`, each marked with `.rp_seeded`).
2. Those copies were made **before** the extension existed, so remove their
   markers and the next run copies it across:
   ```bash
   rm -f /tmp/rp_cdp_*/.rp_seeded
   ```
   A **restart does the same thing**, because macOS clears `/tmp` on every
   restart.
3. **Only needed if the batch stage is on.** The scheduled push runs
   `--oat-only`, which never reaches the batch stage that uses the extension.

Once the install method is confirmed (whether the Web Store page above works for
this internal plugin), add it to `deploy/lucy_walkthrough.sh` as its own step.

## 5. Go-live, when the box gets its first report

Move one report at a time, turning on only what that report needs:

- `runs_appstream` / `holds_appstream`: **all Lucys share one AppStream
  account.** Watch the other machines the next morning.
- **Applicant push:** take the offices **off** the old machine's rotation in the
  **same commit** that puts them on the new one. A push can't be undone, and an
  office on two machines gets pushed twice. It does **not** need the AppStream
  fleet flags above: it signs in as its own `lucyresume` login through real
  Chrome and never touches the shared `Lucy Reports` session (moved Raf's three
  streams to Lucy 4 this way, bc9ff04). Its working profiles live in `/tmp`, so
  a restart wipes them and the next run rebuilds them from Default.
- `morning_clock_since` = tomorrow's date, if it joins the 4am batch. That date
  also arms its heartbeat watchdog.
- Delete the "not yet live" pin tests for that machine as each flag turns on.

## Traps it has already cost us

- **"Not Delivered" in Messages** with the right account = iMessage not yet
  activated on the new Mac. Fix: sign out of Messages, restart, sign in.
- **Remote Login** often doesn't stick from a script. The walkthrough opens the
  panel. Leave Remote Application Scripting **off**.
- **A green-looking login check** used to say FAIL AppStream on a box that
  deliberately has no AppStream. Fixed: it reads the roster now. Never log
  AppStream in by hand on a box with `runs_appstream=False`.
- **Push is not deploy.** A Lucy pulls nothing on its own. Queue `update` after
  every push that has to reach it.
- **Two sessions on one Lucy:** its main queue runs one thing at a time. A long
  dry run from another session makes your checks wait. That's not a fault.
