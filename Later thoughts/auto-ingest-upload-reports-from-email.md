# Auto-ingest the upload reports from email (no manual upload)

Logged 2026-06-30 (Megan — "I know I asked for this"). **Wanted / not built.**

**Idea:** the three UPLOAD-gated reports — **Financial**, **First Sale / Last Sale**,
**Frontier OPT** — currently need a human to download the emailed file and upload it
to the Hub. Instead, have the Hub **auto-scan the inbox** (alphaletereporting@gmail.com
IMAP), grab the report's attachment, and run the report unattended — no human upload.

**Why now:** the pieces exist as of today.
- `automations/residential_rep_count/email_source.py` is a working IMAP-ingest
  template (search by sender+subject, pull the newest attachment).
- The **email-readiness gate** built 2026-06-30 (`readiness._probe_email` — waits for
  this period's source email to actually be in the inbox before running, fail-open on
  IMAP blips) generalizes to any email-fed report.
- So each upload report becomes: an `email_source` (its sender/subject) + `source_type:
  "email"` in schedule_config + the readiness gate → moves it from `excluded` (MANUAL)
  into the normal scheduled flow.

**Scope when picked up (per report):**
1. Identify each report's source email — sender + subject + attachment type
   (Financial xlsx, First/Last Sale xlsx, Frontier PDFs — Frontier is 3 PDFs, so the
   ingest must grab all matching attachments for the week).
2. Add an `email_source`-style fetcher (reuse residential's shape).
3. Point the report's file-read at the fetched attachment instead of a manual path.
4. Set `source_type: "email"` + move it out of `excluded` in schedule_config; the
   `_probe_email` gate needs a per-report branch (today it's residential-specific —
   generalize it, e.g. config-driven sender/subject + expected-week logic).
5. Keep the existing "Upload" button as a manual fallback for off-cycle re-runs.

**Watch-outs:**
- Partial-week emails / re-sends — Frontier is partial-upload-safe already; keep that.
- The "Not Found In Email" / "Not On Emailed Report" unmatched-ICD handling stays.
- Financial is incremental (never wipe missing ICDs) — preserve that on auto-ingest.

Ties into [[project_auto_login_direction]] (no human trigger) and
[[reference_hub_source_email_access]] (the IMAP + app-password access).
