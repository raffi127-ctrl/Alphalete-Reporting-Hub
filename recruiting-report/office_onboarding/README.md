# Metrics Onboarding

Megan's one-form tool to add a new office to daily metrics posting and drive
wiring it into the right report family on the right machine (Lucy 1 / Lucy 2).
For Megan, not ICDs — the form is dense and honest rather than simplified.

Same self-serve Streamlit pattern as `pay_structure/` and `document_builder/`:
code gate → form → write to a Google Sheet tab (the config store the reports +
Hub read from).

## What a submission sets up

1. **Config → source of truth.** The form appends the office's full config to the
   **Office Onboarding** tab of the AUTOMATION MASTER sheet
   (`1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw`).
2. **Into the registry + machine.** `python -m automations.office_onboarding.apply
   --write` reads that tab and materializes each office into a committed
   `onboarded_offices.json` that the family's `offices.py` merges at import
   (D2D → `office_metrics`, B2B → `b2b_metrics` + `att_order_log.churn_run`),
   plus a `<key>_metrics` entry in `day_orchestrator/schedule_config.json`
   assigned to the machine the office's Tableau **view owners** imply
   (Raf → Lucy 1, Carlos → Lucy 2).
3. **Hub self-updates.** The Hub's *Office Daily Metrics* / *B2B Metrics* cards and
   *Pay Structure* all read the registry, so a merged office appears with no
   `dashboard.py` edit.

`apply` is dry-run by default, runs the family's `validate()` (refuses a duplicate
channel / view / key), and writes nothing until `--write`. Nothing is committed or
pushed — review `git diff`, run the office `--dry-run` on its machine, then commit.

## Machine = view owner (why it matters)

Saved Tableau views render as whoever is logged in on that machine — Lucy 1 is Raf,
Lucy 2 is Carlos. A Raf-owned view only renders Raf's scope, so it must run on
Lucy 1; a Carlos-owned view must run on Lucy 2. The form captures a Raf/Carlos
owner per per-office view; any Carlos-owned view forces Lucy 2, and an office that
mixes both owners is refused (it can't run on both machines).

Most D2D metrics slice a shared org-wide view sliced to the owner in Python, so a
normal office needs **no** per-office view — it inherits its family's machine.

## Run

```bash
# local preview (writes only to a local draft JSON — never the live sheet)
OFFICE_ONBOARDING_LOCAL_ONLY=1 .venv/bin/streamlit run office_onboarding/app.py
```

Deploy to Streamlit Community Cloud with `office_onboarding/app.py` as the entry
point.

## Secrets (Streamlit Cloud dashboard, or `.streamlit/secrets.toml` locally)

```toml
[gcp_service_account]                 # OR [gcp_oauth] — creds for the master sheet
# … service-account json …
```

No access-code gate — it's an internal Megan/Eve tool.

Without creds the form still runs and saves to
`output/office_onboarding_submissions.json` (fine for building / sandbox — it never
touches the live master sheet). Set `OFFICE_ONBOARDING_LOCAL_ONLY=1` to force the
local draft even when creds are present.
