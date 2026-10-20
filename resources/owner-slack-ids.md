# Owner & team Slack IDs (Alphalete workspace)

**The one place to look up who's who on Slack.** Use these IDs for DMs, @-mentions
and `post_note users=…`. Never guess from a name search: several people have
duplicate or look-alike accounts (marked ⚠ below).

When you confirm a new ID, add it here in the same commit.

## Team

| Person | Role | Slack ID |
|---|---|---|
| Megan Hines | Hub owner | U04G5HJBGFN |
| Evelyn (Eve) Sobrino | Approver: review gates, bulletins | U088E2KJEV8 |
| Rafael (Raf) Hidalgo | Owner | U045Z8N0ZQC |
| Maud Miller | | U045USN7NCD |
| Lucy Reporting | The bot account all reports post as | U0BCG8F9B5Z |

## ICD / office owners

| Owner | Office | Slack ID | Notes |
|---|---|---|---|
| Aisha Ceron | | U083X5ZJWSH | |
| Analay Ruiz | | U069URK7752 | |
| Aya Al-Khafaji | Aya's Local Office (ECO `aya`) | U07QGLA10EN | |
| Carlos Hidalgo | Carlos's Local Office, B2B AT&T + Box | U046G04P5LG | ⚠ many other "Carlos" accounts exist; this is the owner. Moving to NDS (Megan, 2026-10-18) |
| Colten Wright | South Shore | U047M3AAN0G | |
| Cyrus Wade | Cyrus's Local Office (ECO `cyrus`) | U06A1QA642X | |
| Elena Camargo | | U0B1G4T0MUN | |
| Eveliz Wright | Eveliz's Local Office | U048WU3EUFJ | |
| Jairo Ruiz | Profits (ECO `jairo15`) | U04Q6T14M34 | |
| Kash (Akashdeep) Rai | Kash's Local Office (ECO `kash`) | U046XBPN0G2 | |
| Khalil Mansour | Khalil's Local Office (ECO `khalil`) | U045F9JCPJT | |
| Luke Baldwin | Luke's Local Office (takeoff-b2b) | U0B7HR6TVEE | |
| Maxamad Aden | Maximal (ECO `maxamad-nds`) | U09SDDHGWQH | ⚠ A second account, "Maxamad Aden" U0AHTR9V2MD, also exists. The alert system uses U09SDDHGWQH. |
| Rashad Reed | Rashad's Local Office | U08LSELFTDW | |
| Roshan Amin Ahmad | Roshan's Local Office (ECO `roshan`) | U066B1ZUT4J | |
| Tre Mitchell | Mission III (ECO `tre`, #mission-iii-sales) | U07TYS3V32A | ⚠ NOT "Tre" U09AASADF8E. Confirmed by Megan 2026-10-18 (tre.mitchell60@gmail.com, DM channel D0C7LM3SR5G) |
| Valeria Rodea | | U06JQ4S1MRA | |
| Valeria Zavala | | U054BLVL94N | ⚠ two Valerias |

## Recruiting audit channels — one per AppStream account number

Raf, via Megan 2026-10-20: each account gets its own channel, named by the
account number. The daily audit flags that day's offenders there so coaching
happens the same day; a weekly overall follows. ONE SHORT HEADER POST, all
detail in the thread. [[feedback_short_header_posts]]

| Account | Owner | Channel ID | Notes |
|---|---|---|---|
| 11280 | Rafael Hidalgo (main) | C0AUAS88FGW | Confirmed by Megan 2026-10-20 |
| 11580 | Carlos Hidalgo | C09L1S3MQ1E | Confirmed by Megan 2026-10-20 |
| 23965 | Tiffani Brown | C0CAV0P4RRS | `raf-hidalgo-recruiting-23965-tiffani`, created 2026-10-20 |
| 24065 | Maria Quintero | C0CBLLEF2CQ | `raf-hidalgo-recruiting-24064-maria` — **the channel name says 24064, the account is 24065.** No `SMS Dump 24064` tab exists and 24065 is what resume_pushing, schedule_config and first_round_scorecards all use. Channel name is the typo; worth renaming. |

## Where else IDs live in code (keep in sync)
- `automations/icd_alerts/offices.py`: `slack_user_id` per ECO office.
- The "ICD Signup" rows in the Lucy Access App: owner IDs for relay offices.
- `automations/override_bulletin/review_gate.py` `APPROVERS`: Eve.
