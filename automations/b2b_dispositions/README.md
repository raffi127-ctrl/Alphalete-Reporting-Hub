# B2B Dispositions

Auto-posts Carlos's OwnerVille B2B dispositions to Slack. **Slack-only** — Lucy
can't text (Apple blocked the Messages automation, 7/29).

Source: Carlos Loom (36f30a9222fb4b0fb9307450e0b6d2b7) + #b2b-dispositions spec.

## What it posts

Three per-day threads, each in **both** `#alphalete-gp-sales` and
`#a-players-b2b` (bold dated parent, image replies underneath):

| Thread | Content | Cadence (Central) |
|---|---|---|
| **Today's Activity** | rep list + knock counts, AT&T + Box | 12,1,2,3,4,5,6pm + 6:30pm |
| **Time Tracker** | the two gap-summary cards, AT&T + Box | same |
| **B2B Dispositions** | Territory Stats, one shot per territory, AT&T + Box | 6:30pm only |

Replies are captioned `AT&T — 1:00 PM`, `Box — 6:30 PM (Final)`, `AT&T — luis`.

## OwnerVille page map (office 11580 / Carlos — verified from the Loom)

- **Today's Activity** — `index.cfm?p=88&rqst=…`
- **Disposition by Rep** — `p=89`; **Territory Stats** = `&pane=territoryStats&teritoryId=<id>`
  (param is spelled `teritoryId`, one r). Territories enumerated live from the page's dropdown.
- **Time Tracker** — `p=510`
- **Campaigns**: `B2B AT&T SBS` = default · `B2B-BOX-Energy` = `&invD2DClientId=16`

## Run

```
# capture only — saves PNGs to output/b2b_dispositions/<date>/, posts nothing (DEFAULT)
python -m automations.b2b_dispositions.run --which all --dry-run

# hourly job
python -m automations.b2b_dispositions.run --which hourly --send

# 6:30 final: hourly (tagged Final) + every-territory dispositions
python -m automations.b2b_dispositions.run --which all --final --send
```

`--send` is the only flag that touches Slack. Everything else is dry-run.

## Deploy (Lucy 2 — Carlos's OwnerVille session lives there)

Must run on **Lucy 2** (Carlos / office 11580) — that machine's OwnerVille login
is where the B2B campaigns are visible.

1. Push, then `git pull` on Lucy 2.
2. First run: `--which all --dry-run` on Lucy 2. Review the PNGs in
   `output/b2b_dispositions/<date>/`. Any shot logged `⚠ FULL-PAGE` means the
   crop anchor missed — its `.domdump.txt` sibling lists the containers to pin.
3. Tune crops in `capture.py`, re-dry-run, preview to Carlos.
4. Once approved: install the launchd agent (StartCalendarInterval array with the
   8 slots) via `python -m automations.day_orchestrator.install_agent b2b-dispositions`.
   A Hub card auto-registers on first run (`hub_coverage`).

## Notes

- Lucy 2's mini runs **Python 3.9** — keep to 3.9 syntax.
- Crops are computed from on-screen text anchors, not fixed pixels (templates move).
- No hardcoded territory list — read from the dropdown each run.
