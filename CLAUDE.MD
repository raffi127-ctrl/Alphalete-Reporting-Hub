# Project Context

This is my AI agent workspace for the Alphalete Reporting Hub. The Hub
runs every weekly/daily automated report my team uses — recruiting, OPT,
financial pulls, daily focus, first-sale/last-sale, production
breakdowns. Code lives under `automations/`, surfaced as cards in
`automations/dashboard.py` (a Streamlit app).

# About Me

We own a D2D sales company. My goal is to automate communication with
applicants looking for jobs at our company AND automate the weekly
reporting across ~52 ICDs. I prefer clear, jargon-free output without
fluff. I need clear visuals and concise communications.

# Rules — always

- Ask clarifying questions before starting a complex task.
- Show your plan and steps before executing.
- Concise output, bullet points over paragraphs.
- Cite sources when doing research.
- Save any one-off outputs to `output/`.

# Rules — when working in this codebase

- **Preview before rollout.** New report fills / formatting changes go
  on ONE preview tab first (default: Marcellus Butler on the ATT
  Program - Focus Report). Wait for my "looks good, roll out" before
  touching the other tabs.
- **Don't commit unless I ask.** Repo lives on GitHub
  (raffi127-ctrl/Alphalete-Reporting-Hub). When I say commit, write a
  lowercase title + bullet body, end with
  `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- **No hardcoded rows or columns.** Find rows by column-B label, find
  weeks by date header (`fill.find_sunday_columns`). Templates change —
  label/header lookup survives, indices don't.
- **Cite the full source path** when telling me where a number comes
  from: workbook → view → worksheet → filter → row/col. I forget once
  I send the metric to you, so spell it out.
- **Name-spelling mismatches → the ICD Aliases sheet**, not per-report
  patches. The "ICD Aliases" tab in the
  `PROJECT REQUESTS FROM REPORT HUB` workbook is canonical. Use
  `automations.focus_office_att.aliases.save_alias(canonical, alias)`.
- **7-year-old-simple UI.** No clever syntax inputs. One input per
  concept. Pick the obvious default. Non-technical users run these.
- **Don't touch user data without confirming.** Append or overwrite
  mapped cells only — never delete a tab someone filled in, even to
  "rebuild cleanly". (I lost work once that way. Don't.)
- **Cross-platform.** Every report has to run on macOS AND Windows. No
  hardcoded `.venv/bin/python`, no `%-I` strftime, no Mac-only paths.
- **Hub ownership.** I (Megan) own `automations/dashboard.py`'s
  structure / layout / nav / card schema. Report-flow + assignee + new
  module additions are open — you can edit those freely.

# Rules — when building new reports (Eve)

- **Sandbox-first.** While I'm building a new report, always point it at
  a DUPLICATED test Sheet — never the production Sheet — until I
  explicitly say "use the real Sheet".
- **Always `--dry-run` while testing.** Run new scripts with `--dry-run`
  (no writes to the Sheet) until I confirm the output looks correct.
- **Hub uploads are open** (2026-05-29). Anyone on the Hub can upload a
  new report / add it to the shared library without my approval — no
  sign-off gate. (Sandbox + `--dry-run` while building still apply; this
  lifts only the approval gate, not the correctness checks.)

# Specific reports in the codebase

- `automations/recruiting_report/` — ATT Program - Focus Report (Hub's
  primary card). AppStream + Tableau → ~52 ICD tabs weekly.
- `automations/financial_report/` — financial section, uploaded xlsx.
  "Not Found In Email" for unmatched ICDs.
- `automations/production_breakdown/` + `automations/team_breakdowns/`
  — auto-run as last steps of the OPT phase. Don't have separate Hub
  cards.
- `automations/focus_office_att/` — Focus Office ATT report
  (ownerville.com → Sheet per-rep breakdowns).
- `automations/dashboard.py` — the Streamlit Hub. Cards live in the
  `AUTOMATED_REPORTS` list. Library is a flat alphabetical list.

# Backups

- Google Sheets data is auto-backed by Google.
- The CODE is only on this Mac unless pushed. After any session of
  building, ASK me if I want to commit + push to GitHub.

# Project Structure

- `automations/` — all report modules + the Hub dashboard.
- `resources/` — reference docs, report specs, screenshots, the
  `report-screenshots/` PNGs for Hub cards.
- `workflows/` — plain-English recipes the agent follows.
- `output/` — finished deliverables, scratch CSVs, downloaded
  crosstabs.
- `Later thoughts/` — deferred Hub ideas parked for "circle back later".
