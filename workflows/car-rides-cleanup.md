# Car-Rides Cleanup — Prompts for Claude Code

Three scheduled car-rides cleanup tasks. They share the same core logic; the only
differences are run context (how many changes to expect) and pace. Run the variant
that matches the schedule, or use "Morning full reconcile" as the general-purpose
prompt.

Runner: Claude Code driving the Claude-in-Chrome extension (browser "vantura").
Intended to run on Lucy2 (the always-on Mac mini) on the schedules below.

---

## Shared reference (applies to all runs)

**GOAL:** Make each car-ride leader's territory in OwnerVille/TeleMapper match the
Stations tab of the "Vantura Master Sales Board" Google Sheet, for BOTH campaigns.

**TOOLS:** Use any browser that's already logged into OwnerVille (via the
Claude-in-Chrome extension) — the specific browser name doesn't matter. Never
enter credentials. Start on the OwnerVille **Territory Assignments** page and
follow the steps below. Use the Google Sheet via Drive/Chrome (do not
download/re-upload).

**SOURCE OF TRUTH — Stations tab** (spreadsheet id
`1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY`, Stations gid `1999003555`):
- AT&T car-ride box = A6:E25 (col A = Territory Leader, B–E = Rep #1–4 riders). Header row 5.
- BOX car-ride box = A29:E38. Header row 28.
- Read ONLY columns A–E; columns to the right are the station matrix, not the car ride.

**WHERE TO EDIT:** OwnerVille → TeleMapper Leads → Territory Assignment. Campaign
selector is top-right next to the star:
- For AT&T rows, select campaign "B2B AT&T SBS".
- For BOX rows, select campaign "B2B-BOX-Energy".

**PER LEADER:** Search the leader's FIRST name only (last names aren't indexed).
Open the territory (click the name; if it only zooms the map, click again) to get
the Edit Layer modal. The territory should contain the LEADER plus their riders
from the sheet row. Add anyone missing (type first name → pick from dropdown),
remove anyone present who isn't in that sheet row (click the x on their chip),
then Save ("Territory Updated Successfully").

**RULES:**
- One rep, one car ride: if a rep is correctly in their car ride per the sheet,
  remove them from any OTHER territory they appear in (search their first name to
  find all territories containing them).
- No territory found for a leader = that person needs a new team. Only Carlos
  assigns new T's — do NOT create one; just flag it.
- Leave road trips alone (e.g. "RT ...", territories with the road-trip/share icon
  and old dates).
- Rename a territory only if its title is shortened/weird/ambiguous; first-name-only
  titles are fine.
- Hidden-space bug: if a search returns nothing right after adding someone,
  backspace once then retype. CAUTION: do not backspace past the typed text or you
  will delete existing rep chips — if that happens, re-add the leader.
- Campaign-specific rep pool: the Assigned Sales Reps dropdown only lists reps
  enrolled in the currently selected campaign. If a sheet rider returns "No results
  found", they aren't enrolled in that campaign — flag it, don't force it.

**DO NOT:** empty trash / hard-delete, change sharing/permissions, touch the
"Assign Clients" attention popup, or post anything to Slack. Make only the
territory add/remove edits above.

**REPORT at the end:** a concise summary of every change made (per leader, what was
added/removed), plus a clearly separated list of FLAGS for Carlos to handle
(needs-new-team, reps not enrolled in a campaign, name mismatches, anything ambiguous).

---

## 1. Morning full reconcile (8:30 AM)

Run the daily car-rides cleanup — this is the 8:30 AM run, the big reconcile,
expect the most changes. Follow the shared reference above.

---

## 2. Mid-morning scrub (10:00 / 10:30 / 10:40 / 10:50 AM)

Run the car-rides cleanup — this is a mid-morning SCRUB run; people are arriving
and assignments shift, so expect only a few changes and move quickly. Follow the
shared reference above. If nothing needed changing, say so briefly.

---

## 3. Pre-departure final check (11:00 / 11:20 AM)

Run the car-rides cleanup — this is a PRE-DEPARTURE final check; reps are about to
head out to sell, so make sure everyone has the right leads/territory. Move quickly,
expect few changes. Follow the shared reference above. If nothing needed changing,
say so briefly.
