# AppStream AI Settings — what every field does

Source: eStream's own walkthrough video of the AI Settings page, transcribed
2026-10-01 ([transcript](transcripts/ai-settings-walkthrough.md)). Unlike the
rest of this pack, this is **current** — recorded against the live product,
not the 2024 Looms.

Why it is here: Megan checked several offices on 2026-10-01 and **none were
set correctly**. These are not cosmetic settings; two of them decide whether
an applicant can accept the time the AI offers them.

Path: **AI tab → AI Settings**. Tabs across the top: Templates · Steps ·
Hours · Escalations · Settings · AI Voice Settings · Check Compliance.

---

## Office Info — left side (yours to edit)

| Field | What it does | The trap |
|---|---|---|
| **Name your AI Assistant** | The name the AI gives when asked "who am I talking to?" | **Must match the name in your Await Call message.** 11280 had the AI named *Aisha* while all three live SMS templates signed *Dani Pena*. |
| **Escalation Contact Title** | Used when the AI hands off: "I'll get my *Hiring Manager* to help answer that." | — |
| **Escalation Contact Person Name** | The name given if they ask who that person is. | **Must be different from the AI assistant name**, or someone who asks both questions hears one person. 11280 had both set to *Aisha* until 2026-10-01. Megan's rule (2026-10-01): the AI assistant name is a **persona** and need not be a real person; the escalation contact must be **the actual human who will place the call**, because that is who the applicant ends up speaking to. Note the AI currently says only the title in the handoff — across six weeks at 11280 it never gave the name once, so the field is set and unused. Raised with eStream. |
| **How long are your interviews?** | The answer the AI gives to "how long is it?" | — |
| **Allow AI to provide address to applicant** | Toggle. | — |
| **Interview Type** | In-person / Phone Call / Google Meet / Zoom Meeting. | **One setting for an office that runs two rounds.** 11280 runs Zoom 1st rounds and in-person 2nd rounds and can only say one. Raised with eStream 2026-10-01. |

## Office Info — right side (greyed out, eStream edits it)

Office Name · AI Recruiting Company Name · Office Address · City · State ·
Zip · Office Phone.

To change any of it, email **aisupport@estream.com** with the new values **and
your account number**.

Two faults found here on 2026-10-01:

- **No suite field.** Address Line 1 only, no Line 2, and no `officeAddress2`
  variable. 11280's suite had been typed into the **State** field as
  "TX Suite 207", which the AI dropped — it sent "3100 Premier Dr, Irving, TX
  75063" with no suite 9 times in one week, and applicants replied *"Is it
  suite 232 or 207"* and *"What suite it?"*. eStream has ticketed a suite
  field.
- **The AI uppercases the company name and uses the wrong field.** Office
  Name is stored as "Alphalete Marketing, INC." and AI Recruiting Company
  Name as "Alphalete Marketing", yet 40 of 40 outbound mentions on 28–29 Sep
  went out as "ALPHALETE MARKETING, INC." The street address renders in
  correct case, so it is the company name specifically.

---

## AI Preferences — the two that actually cost bookings

The pair is confusing because **both are buffers measured backwards from the
appointment**, so a bigger second number means the applicant gets *less* time.

**Timeslot Buffer — For Times Offered by AI (minutes)**
How far ahead the first offered slot is. Talking to someone at 9:30 with a
60-minute buffer, the earliest the AI can offer is 10:30. This is your prep
time.

**Timeslot Buffer — For Times Accepted by Candidates (minutes)**
How long before that slot the AI stops accepting it. With a 10:30 slot and 55
here, acceptance closes at 9:35 — so the applicant had five minutes.

**The window an applicant actually gets = (offered − accepted).**

11280 on 2026-10-01 was set to **15 offered / 10 accepted = a 5-minute
window**. Measured against 5,882 applicant replies in the week to 25 Sep:

| Applicant replies within | Share |
|---|---|
| 5 minutes | **32%** |
| 10 minutes | 39% |
| 15 minutes | 44% |
| 30 minutes | 52% |
| median | **26 minutes** |

So about two thirds of applicants were too slow to take the time they were
offered, and the AI has to offer again — extra round trips on a channel
already losing 11% of its texts.

### What 11280 was changed to, 2026-10-01

**Offered 60 · Accepted 5 · Ghosting 60** — a 55-minute acceptance window
instead of 5.

The window was widened by lowering the *accepted* cut-off, not by pushing
the offered time further out, because same-day interviews show up far
better at this office:

| Booked for | Booked | Show rate |
|---|---|---|
| Same day | 1,901 | **57%** |
| Next day | 1,801 | 42% |
| 2–3 days | 781 | 38% |
| 4+ days | 84 | 39% |

A longer offered buffer would start spilling bookings into tomorrow and
cost more than the wider window gains. 60 minutes keeps it same day.

**The trade-off:** at accepted = 5 an applicant can take a slot five
minutes before it starts. That only happens to someone replying ~55
minutes late, but the office has to be willing to run it. If the team gets
caught out, accepted = 15 gives a 45-minute window (about 57% of
applicants) with 15 minutes' notice guaranteed.

**Ghosting Threshold (minutes)**
Silence for this long puts a ghost icon on the conversation so a recruiter can
re-engage. 11280 is at 45, by which point 58% of applicants have replied
anyway — so roughly 4 in 10 conversations get flagged.

---

## The proposal put to eStream

[office-message-setup-mockup.html](office-message-setup-mockup.html) —
a working mockup of a per-office setup form. The ICD enters their own
details once and the AI's escalation messages are generated from them,
which answers the validator's objection: it rejects specific claims
because it cannot tell whether they are true for a given office, and
facts the office supplied and signed off on are verified by definition.

Open it in a browser; typing in any field rebuilds the ten messages on
the right. Fields marked NEW do not exist in AppStream today: suite,
campaign type, pay range, per-round interview type, a second Zoom link,
and languages recruited in. It also cross-checks the pair of timeslot
buffers and warns when the AI persona and the escalation contact share
a name.

The ten messages it generates are the top ten things applicants
actually say, measured across all four accounts (36,326 inbound
messages, six weeks to 25 Sep), per 1,000 inbound:

| | per 1k |
|---|---|
| Call me instead | 8.9 |
| Not interested / opt out | 7.2 |
| Spanish | 6.7 |
| What is the job / role | 6.2 |
| Pay / commission | 5.7 |
| Remote? | 4.3 |
| Scam / is this real | 3.1 |
| Commute too far | 2.2 |
| Directions / which suite | 2.1 |
| Does not remember applying | 1.1 |

Worth noting where offices differ: Spanish is worst at 11580 (9.5), pay
is worst at 23965 (9.4), and "does not remember applying" is almost
entirely 11280. The per-office form is the point.

## Checking an office

1. AI assistant name matches the Await Call template signature
2. Escalation contact name ≠ AI assistant name
3. Interview Type matches the round it is actually used for
4. (offered − accepted) is at least as long as that office's median
   applicant reply — measure it, do not guess
5. Ghosting threshold above the median reply, or everyone looks like a ghost

Items 1, 2 and 4 are checked by `automations.sms_audit.escalations`; item 4
needs the reply-speed number from
`analyze.applicant_reply_speed(convos)`.
