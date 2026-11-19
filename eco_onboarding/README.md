# LucyECO Onboarding enrolment

A per-office link. An ICD answers once and the answers land on the
**Office Settings** tab of the relay workbook — the tab Sterling, the
onboarding board and the Apex fill all already read.

**Separate from the LucyECO install sign-up** (`icd_signup/`), on purpose
(Megan, 2026-11-19). That form gets their computer running; this one collects
the facts their onboarding needs.

- **Owner-facing:** `eco_onboarding/app.py`
- **Logic + schema:** `automations/eco_onboarding/`
- **Writes:** `Office Settings`, by column name, only the columns it was given

## Why it exists

On 2026-11-19 two columns the code reads — `Blue Ink` and `Rate of Pay` —
**did not exist on that tab**. They had been written into the code and never
into the sheet, so `office_steps.rate_of_pay()` returned `None` for every
office and every non-Raf person was held back on a question nobody had been
given a way to answer. The same was about to be true of the eight Apex fields.

So the form creates any column it needs and then asks for it.

## What it asks

| Section | Questions |
|---|---|
| Where the job is | State, City — Sterling's "Location of Job/Position" |
| Your onboarding | Blue Ink account?, Rate of pay |
| Payroll | State Working In, State Taxed In |
| The rest | Position, Pay Basis, Pay Frequency, Department, Country, Security Role — behind one "the standard one" tick |

The two state questions are **required and start blank**. A default would be
Texas, which is exactly the bug: an office outside Texas getting Texas on a
tax record, where it is wrong and invisible.
