# B2B Dispositions

Auto-posts Carlos's OwnerVille B2B dispositions to Slack, and texts the same
shots to the iMessage groups (`--text`, live since 8/6 on Lucy 2).

Source: Carlos Loom (36f30a9222fb4b0fb9307450e0b6d2b7) + #b2b-dispositions spec.

## What it posts

Three per-day threads, each in **both** `#alphalete-gp-sales` and
`#a-players-b2b` (bold dated parent, image replies underneath):

| Thread | Content | Cadence (Central) |
|---|---|---|
| **Today's Activity** | rep list + knock counts, AT&T + Box | Mon–Fri 12,1,2,3,4,5,6pm + 7pm · Sat 12,1,2,3pm + 4pm |
| **Time Tracker** | the two gap-summary cards, AT&T + Box | same |
| **B2B Dispositions** | Territory Stats, one shot per territory, AT&T + Box | the final run only (7pm Mon–Fri, 4pm Sat) |

**No Sunday runs** — Sunday was turned off 2026-08-09 (`b8b89e6`), same commit
that moved Saturday's wrap to 4pm. The days live in the two plists' `Weekday`
arrays AND in `schedule_config.json` → `b2b_dispositions.standalone_weekdays`;
change one, change the other, or the error watcher starts guessing the cadence
from the Activity log and posts a false "didn't run today".

Replies are captioned `AT&T — 1:00 PM`, `Box — 7:00 PM (Final)`, `AT&T — luis`.

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
