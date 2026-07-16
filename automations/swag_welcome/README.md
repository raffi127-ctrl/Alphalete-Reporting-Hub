# New-Hire Swag Texts  ·  🏢 Office Operations

Text each Friday's new hires a personalized welcome with a photo of their
swag package that has **their name written on the card**. Send from whatever
machine runs it (Hub / mini / laptop) — no iMessage account is hardcoded.

## Flow
1. **Upload** the roster screenshot (columns: Name · Last Name · Phone).
2. **Preflight** — Claude vision reads the rows; we normalize the phone
   numbers and split any quoted name. You review/edit:
   - fix a misread name or number,
   - for a quoted name, pick real-name (pronunciation) vs. nickname,
   - uncheck anyone to leave out of the batch.
3. **Run** — composites each card + sends via iMessage. `--dry-run` (default)
   previews everything and sends nothing; `--send` goes live.

## Try it (standalone, while it's being built)
```
streamlit run automations/swag_welcome/preflight_app.py
```

## CLI
```
python -m automations.swag_welcome.run --roster roster.json            # dry run
python -m automations.swag_welcome.run --roster roster.json --send     # live
```

## Naming rule (Megan 2026-07-13)
A quoted part in a name means one of two things and we can't auto-tell them
apart, so preflight always asks:
- `Auryn "RN"` → pronunciation → use the real name (**Auryn**)
- `Jonathan "Jon"` → nickname → use the nickname (**Jon**)

## Still to wire (blocked on assets)
- **`resources/swag/swag-card.png`** — the real swag photo. Until it's there,
  the tool draws on a labeled placeholder card.
- **`compose.NAME_BOX` / `FONT_CANDIDATES`** — tune where/how the name sits
  once the real photo is in.
- **`message.DEFAULT_TEMPLATE`** — replace with Megan's real welcome copy.
- **Hub card** under 🏢 Office Operations — wired after a preview is approved
  (preview-before-rollout).

## Files
| file | does |
|------|------|
| `roster.py` | phone normalization + quoted-name splitting (pure, tested) |
| `extract.py` | screenshot → rows via Claude vision |
| `compose.py` | writes the name onto the swag card (Pillow) |
| `message.py` | the welcome-text copy |
| `imessage.py` | sends from this Mac's iMessage account (AppleScript) |
| `run.py` | orchestrates a batch; `--dry-run` default |
| `preflight_app.py` | the upload → review → run UI |
