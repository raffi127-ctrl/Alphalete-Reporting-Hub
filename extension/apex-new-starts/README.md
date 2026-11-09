# Lucy Onboarding — Chrome extension

Two things behind one icon:

- **the onboarding board** — who started this week, what each of them still
  needs, who to mark off, and one printed sheet per classroom;
- **new starts → Apex**, the Thursday job.

And one button on Apex itself: **Fill Apex**, bottom right. It fills each week's new starts
into Apex — Employment Record, User Profile, Tax & Bank — from the list the Hub
built off the sales board and everyone's signed Blue Ink packet. You type the
Socials; nothing else is typed by hand.

This replaces the **Fill Apex bookmark**. Same engine, same run, same panel.

## Install (per computer, ~1 min)
1. Chrome → `chrome://extensions` → turn on **Developer mode** (top right).
2. **Load unpacked** → pick this `extension/apex-new-starts` folder.
3. Pin it (puzzle icon → pin **Lucy Onboarding**).
4. Delete the old **Fill Apex** bookmark so nobody clicks the wrong one.

## Every week
1. **Hub → New Starts → Apex → Get this week's setup.** About a minute. The
   week's list lands on the clipboard.
2. **Open Apex** on Roster → Employees → **Pending**.
3. **Fill Apex** (bottom right). The first press takes the list off the
   clipboard and keeps it; after that the button just runs.
4. Type the Socials, **Try one person**, then **Start the run**.
5. The OBCL ticks itself a few seconds after the run ends.

The icon shows which week is loaded and who is in it, and has
**Forget this week** for starting over.

## Why an extension and not the bookmark
- **The code ships with the extension**, so a fix arrives by `git pull` instead
  of a re-copied bookmark. Three separate "nothing happens" reports were all
  one cause: macOS Smart Quotes rewriting `'` in a pasted bookmarklet, which
  then parses as nothing and cannot report anything.
- **The week's list survives a reload.** It lives in the extension, not in the
  page, so reloading Apex no longer loses it.
- **Clipboard text is parsed, never run.** A stale copy can no longer run last
  month's engine against this month's list.

## How it is built
`engine.js` is **generated** from `automations/apex_new_starts/filler.py`:

```
python -m automations.apex_new_starts.build_extension
```

Do not edit it by hand. It is the same engine the bookmarklet renders and the
same one `test_filler.py` / `test_fields.py` cover — a second copy would fork,
and a forked engine's symptom is a wrong value on somebody's payroll record.
`test_extension.py` fails if the file on disk has drifted.

## Shape
Two content scripts, in two worlds, on purpose:

- **MAIN world** — `engine.js` + `main.js`. The engine drives Kendo widgets
  through their own API and reads Angular's bindings; those objects belong to
  the page. An isolated-world engine would find every dropdown unsettable.
- **ISOLATED world** — `setup.js` + `loader.js`. The button, the clipboard read
  and `chrome.storage`, which the page world cannot reach.

They talk over `ans-run` / `ans-engine-ready` / `ans-failed` CustomEvents.

## Socials
Typed into the panel at run time, held in that tab for that run only. Never
read from Blue Ink, never logged, never in the clipboard payload, never written
to this machine or anywhere else. A test pins that what the extension stores
cannot carry one.
