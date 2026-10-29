# Hub Code.gs snippets

Apps Script (.gs) files that live in the Hub intake Sheet, NOT in this
repo. Per [reference_hub_code_gs](memory), they need a manual paste into
the Sheet's Apps Script editor — they don't deploy automatically with
the rest of the Hub.

The intake Sheet:
https://docs.google.com/spreadsheets/d/1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw/

## How to install a .gs file

1. Open the intake Sheet.
2. Extensions → Apps Script.
3. Paste the contents of the .gs file into Code.gs (or as a new file).
4. If the file's header comment lists a setup function (like
   `setupNotifyMeganTrigger`), run it once and approve permissions.
5. Done — no further action needed.

## Files in this folder

- **notify-megan-on-new-bug.gs** — emails Megan whenever the Hub
  auto-files a "Run glitch" row (a report run failed). Runs as a
  5-minute time-driven trigger, so Megan gets an email within 5 min of
  any glitch landing on the Bug Reports tab.
