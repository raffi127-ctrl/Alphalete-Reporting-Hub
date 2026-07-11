# ABP% Report — Add a New Office (onboarding recipe)

The **New Internet ABP%** report (per-rep Auto Bill Pay mix, 4-wk rolling,
posted to a Slack Metrics thread) is built to add offices with almost no
new code. To add an office, Megan gives me the 4 inputs below and I do the
rest.

## What Megan gives me (per office)

1. **Owner name** — the ICD owner, e.g. `Aya Al-Khafaji`. (I confirm the
   exact spelling from the pulled data — don't sweat variants.)
2. **Tableau view URL** — a saved view in **ATT TRACKER 2.1 - D2D → Metrics**
   (Chris Wilford's tab), filtered **ICD Owner Name (rep) = <owner>** and
   **drilled to per-rep** (click the `+`). Any view name is fine. Example:
   `.../ATTTRACKER2_1-D2D/Metrics/<guid>/<Name>ABP`.
   → It must expose `New Internet Count (Metrics)` + `New Internet ABP Mix %
   (Metrics)` (every Metrics view does; I verify with a discovery pull).
3. **Google Sheet** — a sheet with a tab named **exactly**
   `Local Office - New Internet ABP%`. ⚠️ Each office needs its **own
   sheet** (tab names are identical across offices, so they can't share
   one sheet). Send the sheet link.
4. **Slack channel** — where this office's post goes (name or ID), e.g.
   Rashad → `#elevate-sales` (C0B3KTCCMT7), Raf → `#alphalete-sales`
   (C068PH3RFSM).

Optional: **color bands** (default 🟢≥85% / 🟡75–85% / 🔴<75%). Say if the
office wants different thresholds.

## What I do

1. **Discovery pull** on the view → confirm ABP columns + pin the exact
   owner string.
2. Add one dict to `automations/new_internet_abp/run_all.py` `OFFICES`
   `{key, label, view_url, owner, sheet_id, channel}`.
3. **Bootstrap-fill** the tab (sheet-only preview) — office avg + per-rep
   %/units, sorted desc, blanks hidden.
4. Apply the **house style**: my value-based red/yellow/green color rules
   (`fill.apply_color_rules`, insert-proof) + carry Megan's static
   formatting (borders / yellow header / font / centering) — the daily
   insert PASTE_FORMATs it forward.
5. Show Megan the preview → on her **"roll out"**, wire it into the daily
   post (both/all offices run under ONE Tableau session via `run_all.py`).

## Mechanics (same for every office)

- **Daily:** inserts a fresh date-pair column (B=%, C=units like `3/5`),
  writes today, pushes history right. Idempotent (refreshes if today's
  already there).
- **Colors:** value-based conditional formatting → recomputed each day
  from that day's %, never carries stale. Megan must NOT hand-paint %
  cells.
- **Hide rule:** hide reps blank today; show reps with data incl. explicit
  0%; names are never deleted.
- **New reps:** auto-appended, then sorted by today's % desc.
- **No mixups:** each office is keyed end-to-end by view → owner → sheet →
  channel; nothing is pooled (proven: one office's owner filter returns
  empty on another's CSV).

## Office roster

| Office | Owner | View | Sheet | Channel | Status |
|---|---|---|---|---|---|
| Raf | RAFAEL HIDALGO | RafLocalofficeINTABP | AT&T Fiber Metrics Report (`1Xddk…`) | #alphalete-sales | tab filled; not auto-posting yet |
| Rashad | RASHAD REED | RashadNLABP | ⚠️ was `11lou…` — now titled "Aya" (needs its own sheet) | #elevate-sales | blocked on sheet |
| Aya | Aya Al-Khafaji | ⏳ need view URL | `11lou…` "Metrics Reports -Aya" (empty ABP tab ready) | ⏳ need channel | blocked on view + channel + sheet overlap |
