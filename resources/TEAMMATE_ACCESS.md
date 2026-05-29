# Giving a teammate edit access (e.g. Eve)

Goal: a teammate can talk to **their own** Claude inside this repo and edit
the **reports** + **report-flow** that live in the Hub, then push their
changes — the same way Megan does.

## What the teammate CAN edit
- Any report under `automations/` (recruiting, OPT, financial, churn, focus
  office, etc.) and its report-flow / assignee wiring.
- New report modules.

## What stays Megan-only
- `automations/dashboard.py` **structure / layout / nav / card schema.**
  Claude already enforces this — it reads the rule from `CLAUDE.MD` on every
  session, so a teammate's Claude will refuse to restructure the Hub shell.

## One-time setup (teammate)
You already have Claude Code installed and a checkout of the repo.
1. **Accept the GitHub invite** Megan sends (email → "View invitation").
   This gives you push access.
2. In a terminal, go to your repo folder and **pull the latest**:
   ```
   git pull
   ```
3. **Talk to your Claude in that folder.** It auto-loads `CLAUDE.MD` (the
   project rules) — no extra setup. Ask it to make report edits in plain
   English, same as Megan does.
4. **Shipping a change:** ask Claude to "commit and push," or push yourself.
   It goes straight to `main`, so the Hub picks it up on the next pull.

## Credentials (must already be on the teammate's machine)
Reports won't run without these local (gitignored) files / secrets:
- `oauth-token.json` (Google Sheets) — ⚠️ see rotation note below
- `ownerville-creds.json` (ownerville login)
- AppStream credentials (env vars + profile dir)

If a report errors with a missing-creds message, that file isn't present
on that machine yet.

## Admin checklist (Megan only)
- [ ] Invite the teammate as a **collaborator with write (push)** access.
- [ ] Once **all** active teammates are collaborators, flip the repo back to
      **private** (it's public right now only so installs work without
      collaborator access — private is fine once everyone's added).
- [ ] **Rotate the Google OAuth token** before spreading it further — the
      current `oauth-token.json` was shared + shown in a screenshot. Rotate
      at myaccount.google.com → Security, then redistribute the new file.

## Ground rules a teammate's Claude already follows (from CLAUDE.MD)
- Preview new report fills on the Marcellus Butler tab first; wait for a
  "looks good, roll out" before touching the other ~52 tabs.
- Don't commit unless asked.
- No hardcoded rows/columns — look up by label/header.
- Sandbox + `--dry-run` while building a new report.
