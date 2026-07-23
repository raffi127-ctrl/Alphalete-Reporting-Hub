# Add a B2B Metrics office (recipe)

Goal: Megan says **"new ICD `<Owner Name>` → `<#channel>` (channel id `<Cxxx>`),
board `<sheet_id>`"** and the agent wires the full 10-item B2B Metrics thread for
that office in one pass. Churn + activation ride **per-office Tableau saved views**
(kept pixel-perfect on purpose — do NOT try to sheet-render them). Everything else
is config the agent fills in.

Decision on file (2026-07-23): churn/activation stay on saved views; the age-window
sheet-rebuild was rejected (colors/tiers live only in Tableau, would be approximate).

---

## What Megan provides
- **Owner Name** — EXACTLY as Tableau's "Owner Name" spells it (drives Sales/OOB
  URL slice + the order-log rep filter). Confirm spelling via
  `att_churn --probe-owners` or the office's own Tableau if unsure.
- **Owner & Office** — the compound "`<OWNER NAME>\r [company]`" string (drives the
  churn/activation slice value). Pull the exact string (embedded CR) from the view.
- **Slack channel** name + id.
- **Board** Google Sheet id (the office's "All In One" board).

## What Carlos makes (the only non-agent step, ~2 min in Tableau)
Two saved views on ATTTRACKER-B2B, filtered to this office (mirror Atef's):
1. **CHURNRATES** saved view, Owner & Office = this office, Wireless default —
   product-switchable by URL (the agent appends `?Product Type (Broken Out)=…`).
   Name it `<Office>EXPANDEDCHURN` (like `CarlosLocalOfficeEXPANDEDCHURN` / Atef's
   `AtefExp`). Note whether its 0-30 disconnect-count sort is **baked** (it should
   be — churn views are).
2. **ACTIVATIONRATES** saved view, Owner & Office = this office. Name it
   `<Office>EXPANDED` (like `CarlosLocalOfficeEXPANDED` / `AtefEXP`). Note whether
   its "0-7 Days" sort is **baked**: if yes → add to `baked_sort_views`; if no →
   leave it out (the capture clicks "0-7 Days" for it).

Carlos sends the agent the two saved-view URLs (GUID + name).

## What the agent does

### 1. `automations/b2b_metrics/offices.py` — one `B2BOffice` row
```python
"<key>": B2BOffice(
    key="<key>", label="<Label>", owner="<Owner Name>",
    channel_id="<Cxxx>", channel_name="<#channel>",
    sheet_id="<sheet_id>",
    owner_office="<OWNER NAME>\r [company]",     # exact compound value
    view_overrides={
        "churn_wireless": _T + "ATTTRACKER-B2B/CHURNRATES/<guid>/<Office>EXPANDEDCHURN"
                          "?Product%20Type%20(Broken%20Out)=WIRELESS",
        "churn_int":      "…<same view>…?Product%20Type%20(Broken%20Out)=NEW%20INTERNET",
        "churn_air":      "…<same view>…?Product%20Type%20(Broken%20Out)=AIR/AWB",
        "activation_rate": _T + "ATTTRACKER-B2B/ACTIVATIONRATES/<guid>/<Office>EXPANDED",
    },
    # ONLY if the activation view's 0-7 sort is baked (like Atef's AtefEXP):
    baked_sort_views=frozenset({"activation_rate"}),
),
```
Sales Metrics + Out of Bounds need NO override — they slice by "Owner Name" in the
URL automatically from `owner`.

### 2. `automations/vantura_churn` config — feeds #6 Customer Churn + #7 Activation-by-Rep
Add the office's `OWNER_CFG` row (key, owner_prefix, sheet_id, "LUCY CHURN", has_act)
and its `_activation_cfg` entry (the ACTIVATIONRATES view URL + custom-view name +
owner prefix). This writes the office's `LUCY CHURN` tab that #6/#7 screenshot.

### 3. Board tabs (semi-manual — do once per board)
Duplicate onto the new board from Carlos's board (template):
- **`LUCY CHURN`** — copy the tab, then **copy its 3 conditional-format rules** and
  **clear the static red fills** (the CF must follow the product dropdown; Atef's
  didn't until the rules were copied — see [[project_b2b_metrics_atef]]).
- **`Lucy At&t Order Log`** + **`Lucy At&t Data`** (hidden) — the order-log workbook.
Confirm the LUCY CHURN tab's activation cells (E5/F5, AE:AF) fill after vantura runs.

### 4. Verify (before it's live)
- `lucy --machine "Lucy 2" rerun b2b_metrics --office <key> --dry-run` → 10/10 captured.
- Spot-check on a **readable channel** (the agent can read #alphalete-gp-sales, NOT
  Domin8): confirm churn shows the right product + owner-scope, activation is sorted
  0-7. Megan eyeballs the office's own channel.
- It's already in the 4am flow via `--all` (on_scheduler:true) — one hub card, no
  per-office scheduler entry needed. The b2b-metrics card reads OFFICES dynamically,
  so the new office shows up automatically.

## Gotchas (learned 2026-07-21..23)
- **"Owner & Office" can NOT be URL-sliced** (compound value w/ embedded CR) — that's
  why churn/activation need per-office saved views, not a `?Owner & Office=` slice.
- **Activation sort is per-office**: baked view → skip the click (`baked_sort_views`);
  un-baked view → the "0-7 Days" click sorts it. A wrong choice posts it unsorted.
- **Deploy AFTER noon**: the Lucy 2 orchestrator runs 4am→noon; an `update` during
  that window re-triggers `b2b_metrics --all --post` and can duplicate posts.
- **DM previews don't reach Megan** (old id U04G5HJBGFN) — verify on readable channels.
