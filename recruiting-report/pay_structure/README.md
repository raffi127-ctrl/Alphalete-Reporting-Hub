# Alphalete Pay Structure — self-serve editor

A per-office link. An ICD enters the code we sent them and lands on **their**
office's pay structure only. They name their leader levels and fill in what a
rep earns per unit of each product at each level. The next morning's Order Log
shows every rep, on their own tab, what they'd earn at each level from the
active lines they sold.

If an office never fills it in, the Order Log shows nothing extra — no error,
no blank block.

## Run locally

```bash
.venv/bin/streamlit run pay_structure/app.py
```

With no secrets, structures save to local JSON under
`automations/pay_structure/data/` and any code of the form `<office>-pay`
(e.g. `cody-pay`) logs into that office — for building only.

## Deploy (Streamlit Community Cloud)

- Repo: `raffi127-ctrl/Alphalete-Reporting-Hub`, branch `main`
- Entry point: `pay_structure/app.py`
- Separate app from the Document Builder (its own URL).

### Secrets

```toml
pay_structure_sheet_id = "<google sheet id>"   # where structures live

[pay_structure_codes]      # one code per office key; the code identifies them
raf   = "…"
cody  = "…"
rashad = "…"
# … one line per office in automations/pay_structure/offices.py

# Google creds for the sheet (any ONE of these):
[gcp_service_account]      # a service-account JSON, OR
# … full service account block
[gcp_oauth]                # the Hub OAuth token block (token/refresh_token/…)
```

The **office keys** come from `automations/pay_structure/offices.py` (derived
from `office_metrics.offices` + Raf). The **Sheet** gets one tab per office,
each a grid of `Product Type × Level → $/unit`. The mini's Order Log reads the
same Sheet with the Hub OAuth token (no secrets needed there).

## How the Order Log uses it

`automations/pay_structure/store.load(office_key)` returns the office's grid;
`estimate.estimate_by_level(active_counts, grid)` prices a rep's active-line
counts into `{level: dollars}`. The Order Log injects an "Estimated Pay by
Level" block on each rep tab, and calls `grid.ensure_products(...)` so newly
sold product types show up in the editor automatically.
