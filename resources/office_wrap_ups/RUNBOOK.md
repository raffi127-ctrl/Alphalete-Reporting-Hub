# Runbook — Office Wrap-Up Check (`office_wrap_ups`)

The multi-office version of the Raf Wrap-Up Check (`rc_contact_sync_raf`).
"Which reps didn't send a wrap-up text," for every office in Raf's captainship,
posted to each office's own Slack channel.

## One line
Pull the org-wide Tableau Order Log once → per office, filter to that owner's
yesterday customers → were they texted on Dylan's RingCentral line? → the ones
who weren't go to that office's channel, grouped by rep.

## Why Tableau, not SaraPlus / LucyECO
- Each office is a **separate SaraPlus dealer**, and those logins live only on
  the owners' own machines — they never reach Lucy. The **LucyECO relay** only
  carries per-rep sale COUNTS, not customer names/phones.
- The **org-wide Tableau Order Log** (the ALLREPS crosstab) carries
  `Owner Name` + `Customer Phone` + `Rep` + `Product Type` for every office, so
  ONE pull covers all 12 with no per-office logins. Trade-off: Tableau refreshes
  on a lag, fine for a morning run. (Raf's own report stays on near-live
  SaraPlus.)

## The accounts
- **RingCentral = Dylan's line** (rc_autoread account), shared across every
  office. If an office reads ~100% un-texted, its wrap-ups go out from a
  different line.
- **Slack** per office from `office_metrics.OFFICES`. Hammad + Salik share
  #elite-prime-sales. **Trang** = the FRESH SUCCESS workspace — posted with its
  bot token `~/.config/recruiting-report/slack-token-freshsuccess` (same file
  office_metrics uses for trang_metrics).

## Running it (Lucy 4)
```
python -m automations.office_wrap_ups.run                 # DRY RUN, all offices
python -m automations.office_wrap_ups.run --live          # post all offices
python -m automations.office_wrap_ups.run --office aya     # DRY RUN one office
python -m automations.office_wrap_ups.run --office aya --live
python -m automations.office_wrap_ups.run --csv order.csv  # offline, use a saved crosstab
```
From a laptop, queue it on the mini: `lucy rerun office_wrap_ups --machine "Lucy 4"`.

## Schedule
Armed `on_scheduler` + `--live` in schedule_config (report id `office_wrap_ups`),
machine Lucy 4 — runs in the morning batch. The 12 keys: haytham trang hammad
jacob joseph kash rashad aya cyrus nii cody salik.

## Notes
- Dylan is @tagged at the bottom of every reply (his AO id, or his FRESH SUCCESS
  id for Trang) so the morning posts are readily visible to him.
- Internet UPGRADES / cancelled + disconnected orders are excluded; customers
  are deduped by phone and products collected across their order lines.
- Reuses `rc_contact_sync_raf`'s identity guard + tagged reply formatter and
  `disconnects.pull.fetch_crosstab` for the Order Log.
