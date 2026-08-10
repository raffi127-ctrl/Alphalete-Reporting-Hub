# New Owners — the waiting list that adds itself to the boards

Two halves of one idea: nobody should have to remember to put a person on a
board the day they start selling.

Code: `automations/new_owners/`. No schedule of its own — the campaign half runs
inside the daily Org Sales Board fill, the captainship half inside whichever
captainship report sees the rep first.

---

## 1. Campaign side — the bank

**Tab `New Owners`** in the Org workbook (`1IpDs2…Wu6E`, next to the board).
Eve fills three columns; the automation owns the last three.

| column | who | what |
|---|---|---|
| Name | Eve | the person, spelled as Tableau spells them (aliases are applied anyway) |
| Campaign | Eve | **dropdown** of the board's real section labels |
| Org Head | Eve | the board's col-M value (Raf / Carlos / …) — nothing can infer this |
| Captainship | Eve | optional, informational |
| Added On | Eve | when you put them on the list |
| Status | auto | blank/`Waiting` → `Added` (or `Already on board` / `Campaign?`). Set it to `Skip` yourself to park a row |
| Activated On | auto | the day they went onto the board |
| Notes | auto | units, first sale, and the rows they landed on |

**What happens each morning** (inside the Org Sales Board daily run, after every
section has pulled):

1. every waiting row is checked against its campaign's own pull;
2. the first day someone has ANY production in the reporting week they get a row
   in that campaign's **daily breakdown** AND its **weekly leaderboard** (total
   apps) — history columns left blank, Org Head copied from the bank;
3. that section is re-filled from the same pull, so their days land in the same
   run;
4. the bank row is stamped, a line goes in the log, and a bullet is posted.

A campaign that didn't pull that day (failed / skipped / granular retry) is not
judged — its people keep waiting rather than being read as "no sales".

Someone added to a campaign section this way is picked up by the **All Campaigns
Org Sales Board** on its next run (its roster sync reads the campaign sections).

## 2. Captainship side — no bank, but a ✅

Source of truth is **Tableau**, not the VA's board. That board stopped being
maintained (Eve, 2026-08-10), so the roster diff that used to drive this is
retired: `roster_sync`'s VA self-heal no longer runs and the daily "no copy row"
gate no longer fires.

    detect   a captainship report pulls its captain's team and finds a rep with
             no row -> `captain_gate.propose()` posts ONE line in the year's
             captainship thread, tagging Evelyn and Jolie
    approve  either of them reacts ✅ on that line
    apply    the next Org Sales Board captainship run calls `captain_gate.
             resolve()`: it inserts the rep into EVERY table of that captainship
             and replies saying where they landed

A fiber captain owns six tables (leaderboard + daily for each of the two boxes,
plus the two bottom delta tables); a single-box captain owns three. A rep missing
from any one of them is a silent undercount, so `cap_insert` does all of them or
refuses (it raises if the captainship has no leaderboard/daily block, and the rep
stays pending).

**Detection coverage** (measured 2026-08-10):

| captainship | detected by |
|---|---|
| Wayne · Starr · Chan · Tony · Sahil | Cancel Rate · Activation Rate · ABP & 6 days (their own daily pulls) |
| Raf | Captainship Metrics - Rafael |
| Khalil · Colten · Jairo | `--scan` — `?NDS Captain Teams=<X>'s Team` on `ProductSalesSummaryRep` |
| Carlos · Eveliz · Luis | `--scan` — one saved custom view per captain on the `B2B 1-PAGER_Captain View` tab (Carlos also via his Bonus report) |

**B2B goes through saved views, not a filter.** On `D2D1-PAGERV3` the captain
dropdown never reached the export — driven to Carlos's Team by URL param *and*
by clicking the options (the checked set really did become `["Carlos's Team"]`),
the ICD sheets still exported all 74 program owners and the dropdown snapped
back to "(All)"; the workbook opens on a default custom view
(`ALLTEAMsALLREPS`), the likeliest culprit. So the roster comes from a **saved
custom view per captain** on the `B2B 1-PAGER_Captain View` tab —
`Roser-Carlos` / `Roster-Eveliz` / `Roster-Luis`, listed in
`cap_roster.PROGRAM_PULLS["b2b"]["views"]`. A new B2B captain = save one more
view and add its URL there. (The URLs are opaque handles: keep them verbatim,
typo included.)

### Re-creating a broken custom view (e.g. b2b `ALL TEAMS`)

1. Open the view and set the filters the way the view should open.
2. Toolbar → the **View:** dropdown (it shows the current custom view) → the
   custom-view list → delete the broken entry.
3. Same menu → **Save Custom View** → give it the SAME name → tick *Make it my
   default* if it was, and **Make visible to others**.
4. Do it from the account the automation logs in as (the bot enters Tableau as
   **Rafael**) or make sure it's shared, otherwise the bot won't see it.
5. The URL carries the custom view's GUID, so open the new one and copy the
   address bar — that string is what goes in `captainship.PROGRAMS`.

Seen on the way: the b2b **`ALL TEAMS` custom view now errors** ("An error
occurred while loading the custom view") — that is the view the daily board pull
uses, so it is worth re-creating.

Approving works for any captainship regardless (`captain_gate.propose` takes any
name), so Eveliz and Luis can be added through the same gate by hand.

## 3. The Slack notices

Channel **#revision-emails** (`C0BLLU9M0A2`), one parent thread per year:

- `New Owners - Active and Added <year>` — campaign side. Pure notice, tags
  nobody, nothing to approve: the bank row was the decision.
- `Captainship New Owner - Active and Added <year>` — the GATE. Each new rep is
  one line tagging Evelyn and Jolie; the ✅ is what puts them on the board, and
  a reply confirms where they landed.

The parent's ts lives in the `New Owners Log` tab (not a file on one machine) so
the Windows box and the mini post into the same thread — and it is written RAW,
because USER_ENTERED turns `1700000000.000002` into `1700000000` and the thread
is then unfindable.

`NEW_OWNERS_CHANNEL_ID` retargets the channel for a live test.

## 4. Commands

```
python -m automations.new_owners.run --init      # create/refresh the two tabs
python -m automations.new_owners.run --status    # who's waiting, what's logged
python -m automations.new_owners.run --scan      # roster the captainships in
                                                 # Tableau, gate anyone new
python -m automations.new_owners.run --scan --captains Khalil --dry-run
```

## 5. Gotchas

- **Where the row goes matters.** Inserts land *before* a block's last row, so
  the daily `Totals` =SUM, the leaderboard =SUMIF, its TOTALS and the ALL TOTALS
  row all expand by themselves. Appending after the last row would give the
  person a row no total ever sees — the board would read low and look perfect.
  Single-row blocks (Frontier) can't have an interior insert, so `repair_ranges`
  rewrites those ranges; it runs every time and is idempotent.
- **Frozen history is never copied** — leaderboard D.., daily K/L stay blank.
- Ranks (col A) are renumbered on the spot; the daily `sort.apply_sort` re-ranks
  by production right after anyway.
- The real VA tab is refused outright (`board_add._guard`).
