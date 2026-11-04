# Applicant reply templates

The approved wording for every question applicants ask the ApplicantStream
AI, and the tooling that keeps three surfaces in step.

## What is here

| File | What it is |
|---|---|
| `editor.html` | The source of truth. 23 question cards + the reference sheets, published as Megan's private editor artifact. |
| `edits/*.json` | What was typed into the editor and saved. A row only holds what someone typed — an empty slot falls back to the card. |
| `build_doc.py` | Writes `resources/recruiting-context/ai-reply-templates.md`. |
| `build_ai_sheet.py` | Writes the shared page for eStream and the voice-AI team (shortcodes, build status). |
| `build_recruiter_sheet.py` | Writes the shared page for human recruiters (blanks to fill in, no shortcodes, Zoom / in-person toggle). |

## The three live pages

| | Who | URL |
|---|---|---|
| Editor | Megan, private | https://claude.ai/artifact/SE9sdkrTUvtVxx92QumsX9 |
| AI build sheet | eStream / voice AI, link-shared | https://claude.ai/artifact/QqHyfff9tDpzU9C2SRUCKL |
| Recruiter sheet | recruiters, link-shared | https://claude.ai/artifact/EQrUxzky6T3R1DABGD25Th |

**They do not update themselves.** After a change: pull the saved edits
down from the editor's database into `edits/`, rebuild, and publish each
page back to the same URL so the links people hold keep working.

## Gotchas learned the hard way

- **A saved row overrides the card.** Editing variation 1 used to save four
  empty strings beside it, and those blanks then hid variations 2-5 for
  good. Both the editor and the generators now fall back per slot.
- **Deleting a saved row is not enough** if a page is open — the live sync
  only ever added rows, never removed one that had been deleted, so a card
  kept showing text that no longer existed anywhere. Fixed in `editor.html`.
- **The generators refuse to build** if a reply uses a shortcode the tables
  do not know. That guard is deliberate: it stops a recruiter being handed
  a message with `{bookedSlot}` still sitting in it.
