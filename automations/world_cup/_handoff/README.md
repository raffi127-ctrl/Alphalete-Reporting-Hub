# AT&T World Cup 2026 — Bracket Flyer Handoff

This folder is everything you need to keep generating Rafael's World Cup bracket flyers each time Smart Circle pushes a new tracker update. Two PDFs come out per run:

1. **Alphalete version** (filtered to only groups containing Rafael's reps, ~1–3 pages, Alphalete reps highlighted in gold) — for Rafael to use internally.
2. **Public version** (all groups, no highlights, share with the wider team / other office leaders) — drop into group chats.

---

## What's in this folder

| File | What it is |
|---|---|
| `README.md` | This document. |
| `build_bracket.py` | The flyer generator. Reads a CSV from `~/Downloads` and writes HTML. |
| `make-flyers.sh` | One-command wrapper that runs the generator AND uses Chrome to render the PDFs. **This is the only command you usually need to run.** |
| `World Cup 2026 - Round N Bracket.pdf` | The Alphalete-highlighted output (created when you run `make-flyers.sh`). |
| `World Cup 2026 - Round N Bracket (Public).pdf` | The public-share output. |

**Setup needed (one time):**
- macOS
- Python 3 (already on every recent Mac)
- Google Chrome installed at the default location

That's it. No `pip install`, no dependencies.

---

## The routine (when a new tracker email arrives)

Smart Circle sends an automated tracker email **daily during a round window**. Sender is usually `noreply@thesmartcircle.com`, subject like *"Res AT&T World Cup Tracker"*. Round-start announcements come from `cwilliford@thesmartcircle.com` (subject like *"FIFA World Cup Contest - Round of 144"*) and tell you when group structure changes.

When you get one:

### 1. Export the CSV from Tableau

Tableau report: <https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER2_1-D2D/WorldCup2026>

You need to be signed in. Once it loads:

1. Click the **Download icon** in the toolbar (top right, ⬇ with a small dropdown caret).
2. Click **Crosstab**.
3. In the *"Select a sheet from this dashboard"* dialog, pick the sheet named after the current round. **Examples:**
   - Round 1 → **"Round of 864"**
   - Round 2 → **"Round of 432"**
   - Round 3 → **"Round of 144"**
   - Round 4 → **"Round of 72"** (when it arrives)
   - **Do NOT pick "Overall Contest Tracker" — that one only contains the title text, no rep data.**
4. Set format to **CSV** and click **Download**.

The file will land in `~/Downloads` as something like `Round of 144.csv` (or `Round of 144 (1).csv` if Chrome added a number to avoid overwriting an older one — that's fine, the script picks whichever is newest).

### 2. Run the wrapper

Open Terminal, then:

```bash
cd ~/Desktop/"World Cup Handoff"      # or wherever this folder lives
bash make-flyers.sh
```

You'll see something like:

```
Round 3 (Round of 144) | CSV: /Users/admin/Downloads/Round of 144.csv
Groups: 4 (of 36 total) | Cut-line ties: 1 | Total Gig+: 217
Alphalete: 4 in play | 4 top-2 | 1 leading group

Done. Two PDFs saved next to this script:
  Alphalete view (for Rafael): World Cup 2026 - Round 3 Bracket.pdf
  Public view (to share):      World Cup 2026 - Round 3 Bracket (Public).pdf
```

### 3. Send to Rafael

Both PDFs are now in this folder. Email or message Rafael:
- The **Alphalete version** is his personal sheet (highlights his reps).
- The **Public version** is the one he forwards to other office leaders.

---

## When the round changes (group structure shifts)

Smart Circle has changed group size mid-contest. **Round 1 and 2 used groups of 6** (top 3 → top 2 advance). **Round 3 switched to groups of 4** (top 2 advance). They'll probably do this again.

If you run `make-flyers.sh` and it errors with *"No config for Round of N"*, the round size isn't yet listed in the script. To fix:

1. Open the round-start email from Chris Williford. It will say something like *"36 groups of 4, with the top two reps moving on to Round 4."*
2. Open `build_bracket.py` in any text editor.
3. Find the `ROUND_CONFIGS` block near the top.
4. Add a new entry with the round size as the key:
   ```python
   72:  {"num": 4, "groups": 18, "group_size": 4, "top_n": 2, "window": "Jun 15-21, 2026", "next": "Round of 36"},
   ```
   - `num` = which round number this is (1, 2, 3...)
   - `groups` = how many groups in total
   - `group_size` = reps per group
   - `top_n` = how many advance per group
   - `window` = the round's date window from the email
   - `next` = name of the next round
5. Save and run `make-flyers.sh` again.

The configs for rounds 1–5 are already pre-filled with reasonable defaults — only update them if Smart Circle changes the structure.

If you're not sure what to set, **just send the round-announcement email to Rafael's Claude** and it'll edit the script for you.

---

## When something goes wrong

| Symptom | Likely cause / fix |
|---|---|
| `No 'Round of *.csv' file found in ~/Downloads` | You haven't exported the CSV yet, or it was saved with a different name. Re-export from Tableau. |
| `Cannot detect round from CSV header` | The CSV is just the dashboard title (e.g. `Overall Contest Tracker.csv`, ~100 bytes). Re-export and **pick the right sheet** in the Crosstab dialog. |
| `No config for Round of N` | Smart Circle started a new round the script hasn't seen. See "When the round changes" above. |
| `Google Chrome not found` | Install Chrome, or edit the CHROME path at the top of `make-flyers.sh`. |
| The PDF has the wrong number of groups | Check that the CSV you just exported is actually the latest. Chrome sometimes adds `(1)`, `(2)` suffixes. The script auto-picks the newest matching file. |

---

## What the colors mean

In every group card:

- 🟢 **Green rows** — Top N (advancing to next round)
- ⚪ **Grey rows** — Bottom (need to climb)
- 🟡 **Yellow rows with "TIE AT CUT" badge** — Two or more reps tied at the cut line. Smart Circle's tiebreakers (Wireless → DTV → cancel% → churn%) decide once the round closes.
- 🌟 **Gold rows with a ★** — Alphalete Marketing reps (Rafael's team). Only in the non-public version.

---

## Background context (for you AND your Claude)

- **The contest:** Smart Circle's annual AT&T D2D sales tournament. Five knockout rounds: 864 → 432 → 144 → 72 → 36 → Finals (8 tickets + $25K pot for the winners).
- **The metric:** Gig+ New Internet Sales count per rep, with tiebreakers (Wireless, then DTV, then lowest 0–30d cancel%, then lowest churn%).
- **Who is Rafael:** Rafael Hidalgo, owner at Alphalete Marketing Inc. ([alphalete marketing inc. (tx) dba algan a] is how his name appears in the Owner & Office column of the Tableau export). He runs the office under Smart Circle's D2D AT&T program.
- **Why two flyer versions:** Rafael uses the gold-highlighted version to motivate his team and track who's in play. The public version goes to other office leaders in the wider Smart Circle chat without playing favorites.
- **Why some rounds have group-of-6 and some have group-of-4:** Smart Circle's choice. Round 1 (864) and Round 2 (432) used groups of 6. Round 3 (144) switched to groups of 4. They'll likely stick with groups of 4 through to the finals, but watch the round-start email each time.

---

## If you want to use your Claude instead of running the shell script

Paste the following block into a fresh Claude Code session as the **first message**. This is a self-contained primer that tells Claude exactly what to do and gives it all the context it needs:

> I'm Rafael Hidalgo's admin. We have a recurring task: every time Smart Circle releases a new World Cup tracker, I export a CSV from Tableau and need both bracket PDFs regenerated (one for Rafael with Alphalete highlighted, one public for sharing).
>
> The toolchain is in `~/Desktop/World Cup Handoff/`:
> - `build_bracket.py` — Python script. Auto-detects the round from the newest `Round of *.csv` in `~/Downloads`. Use `--public` flag for the no-highlight version.
> - `make-flyers.sh` — Wrapper that runs both Python builds AND uses headless Chrome to print the PDFs. The simplest path: just `bash make-flyers.sh`.
>
> When I drop a new CSV (it'll be a file like `Round of 144 (1).csv` in my Downloads), please:
> 1. If Chrome added a `(1)` suffix, move/rename it to the canonical name (overwriting).
> 2. Run `bash ~/Desktop/"World Cup Handoff"/make-flyers.sh`.
> 3. Tell me where the two output PDFs are and a quick summary of Alphalete's standings (in play / advancing / leading group).
>
> Read `~/Desktop/"World Cup Handoff"/README.md` for full context if you need it. If Smart Circle changes the group structure (currently groups of 4, top 2 advance for Round 3), you may need to update `ROUND_CONFIGS` in `build_bracket.py` — the README explains how.
