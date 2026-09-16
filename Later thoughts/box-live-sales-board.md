# Box columns on the live ICD sales boards

**Parked 2026-09-15.** The Box *alerts* are built and going live for Ryan
and Carlos. The *board* is the next piece and is a real job, not a
wire-up — logged here rather than squeezed in behind a rollout.

Megan, 2026-09-15: *"we're building live sales boards for the ICDs — this
is what will 'feed' the box ones."*

---

## Why it isn't already done

`icd_sales_board/relay_read.py` says it plainly: **"the shape on the wire
IS the shape of the board."** That is true, and it is exactly the
problem — the wire now carries Box's shape, and the board is still built
around AT&T's.

The relay and the Slack alerts were fixed on 9/15: metric names are a
property of the campaign, via `sale_hype.shape(campaign)`. The board
never got that treatment.

## What a Box office's sales actually look like on the wire

```
{'sales': {REP: {'Sales': 3, 'Volume': 78406, 'Big': 2, 'Huge': 1}}}
```

vs AT&T's `{'Int', 'Int Up', 'DTV', 'NL'}`.

- **Sales** — the count. The only thing that may ever be summed.
- **Volume** — annual **kWh**, not dollars. Box is an energy broker.
  A `$` anywhere on this column is wrong by three orders of magnitude.
- **Big / Huge** — Carlos's escalation counts (24-month contract;
  24-month at 20k kWh+). Display-only; never summed, probably never a
  board column at all.

## The files that hardcode AT&T's four

| File | Where | Note |
|---|---|---|
| `icd_sales_board/site.py` | `RELAY_MEASURES` (line 57) | **15 uses** — totals, week tables, day columns, week-over-week |
| `icd_sales_board/site.py` | line 445 | a separate inline copy of the same four |
| `icd_sales_board/relay_read.py` | `MEASURES` (line 48) | plus the module docstring |
| `icd_sales_board/tableau_days.py` | `MEASURES` (line 46) | |
| `icd_sales_board/new_sheet.py` | `DAY_PRODUCTS` (line 79) | includes Apps / EN / Cx |

`board_read.py` already carries `ATTR_CAMPAIGN`, so the board can tell
which campaign an ICD runs — the join exists, nothing uses it for
columns.

## Not in scope (deliberately)

`alphalete_sales_board/` (calc, notify, state, run) and
`rep_sales_fill/board.py` also hardcode the four. Those are the **AO
board**, which is AT&T and stays AT&T. Don't generalise them by
accident — `calc.py`'s Apps formula deliberately excludes Int Up, and
that rule is not Box's.

## The shape of the work

1. Give the board the same campaign-shape treatment the relay got —
   most of the logic is "for m in MEASURES", so it is mechanical once
   the source of the list is right.
2. Decide what a Box board's columns are. Probably **Sales** and
   **Volume (kWh)** only — Ryan wanted both, Carlos wanted the clean
   count, and two columns means neither loses.
3. Column *widths and totals* are the trap: a volume column sums to six
   or seven figures beside a sales column that sums to single digits.
4. `new_sheet.py` creates the tab — a Box office's new sheet needs Box
   headers, or the first fill writes into AT&T columns.

## Watch out for

- **A derived writer hiding a hardcoded reader.** Standing rule, and
  this codebase has burned it before: fixing the writer and leaving a
  reader on the old four gives a board that fills and reads blank.
- **Zeros vs no reading.** `relay_read` is careful that an office with
  no rows is an office whose agent has not run. Keep that.
- **Box's volume can be blank.** 3,903 of 6,514 order-log rows had a
  readable volume; the rest were empty. A blank is not a zero.

## Related

- Alerts, settled rules, verbiage: `output/box-alerts-verbiage.md`
- What counts as a sale: `output/box-statuses-chart.md`
- The reader: `automations/icd_alerts/box_read.py`
- The campaign shapes: `automations/shared/sale_hype.py`
