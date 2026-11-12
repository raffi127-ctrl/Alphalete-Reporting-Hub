# Apex after the Beta rewrite — what is actually on the page

Read off the live site on 2026-11-11 with `automations/apex_new_starts/probe_fields.py` (read only,
types nothing). Victoria Newsom, employee 3421274, Alphalete Marketing Inc. –
Arlington. Re-run it rather than trusting this page once Apex moves again.

## What changed, and what it broke

* **No Angular injector on any page** — the landing page, the roster and an
  employee record all answer `angular? : False`. `goSpa` moved through
  `$location`, so it returned **false everywhere**. `runPerson` navigates with
  `goSpa` for all three tabs, so the extension's "Run the whole week" stopped
  at its first one. Fixed by clicking the tab's real anchor instead.
* **Every tab is a full page load.** The injected script does not survive one,
  so a driven run has to put it back after each move (`drive.keep_loaded`).
* **A tab renders, then fetches.** The feature toggle `roster.separateEditPages`
  ("Beta" in the nav) loads the employment record separately, and the page
  says `Loading Employment Record data...` while it does. Reading it then finds
  **zero fields**, which is why every label came back missed. The engine now
  waits for that text to go (`waitLoaded`) instead of a fixed 800ms.

## Employment Record — `/employees/<id>/edit/employment-record`

**EVERY DROPDOWN HERE IS A KENDO WIDGET**: a visible span over an
`<input type="hidden">`. A hidden input has `display:none` from the browser's
own stylesheet, so a dump that skips invisible elements shows none of them —
which is why Position, Basis of Pay, Pay Frequency, Department and State
Working In read as "not on this page" for a day (2026-11-12). They were always
there.

| On the page | name | kind |
| --- | --- | --- |
| Position * | `JobTitleID_192` | id |
| Basis of Pay * | `BasisOfPayID_192` | id |
| Pay Frequency * | `PayFrequencyID_192` | id |
| State Working In * | `StateWorkingInID_192` | id |
| Department * | `CompensationProfileID_192` | id |
| Rate of Pay * | *(none — match by label)* | text |
| **Salary** | *(none)* | **NEVER WRITE THIS.** It sits under Rate of Pay and is the wrong box for an hourly rate. |
| Commission Threshold | *(none)* | text |
| Divisions | *(none)* | search |
| Time Clock | `TimeClock_192` | checkbox |
| Require Break | `RequireBreak_192` | checkbox |
| Track Time Entries in Real Time | `TrackRealTime_192` | checkbox |
| Office Admin | `Role_6_192` | radio |
| ICD Payroll Admin | `Role_8_192` | radio |
| **Sales Rep** | `Role_11_192` | radio |
| Owner | `Role_12_192` | radio |

**They are IDs, not labels.** `JobTitleID` wants the id of "Sales Rep", not the
words — typing a label into one puts a word where an id belongs, the page looks
right and the save is wrong. That was already the rule; it still is.

**`_192` IS THE OFFICE, NOT THE PERSON.** Every one of these names carries the
office's id, so they differ for another office and must never be hard-coded.
Find them by label and read the name off the element.

## User Profile & Account — `/employees/<id>/edit/user-profile`

Clean `name` attributes; map on these rather than labels.

| Field | name |
| --- | --- |
| First Name * | `FirstName` |
| Middle Name | `MiddleName` |
| Last Name * | `LastName` |
| Account Email * | `EmailAddress` |
| Date of Birth * | `BirthDay` |
| Gender * | `GenderID_364` (the id) / `Gender_input` (what you see) |
| State * | `StateProvinceID` |
| Country * | `CountryID` |
| Street Address * | `StreetLine1` |
| Apt/PO Box | `AptNum` |
| Street Address 2 | `StreetLine2` |
| City * | `City` |
| Zip Code * | `PostalCode` |
| Phone Number | `PhoneNumber` |
| Extension | `Extension` |

**The password box moved here.** "Override the user's password with a temporary
password" is a checkbox on this tab now (no name attribute). It is the same
hazard as the create form's: saving with it on emails the person. Everything
that writes this tab has to set it deliberately, never leave it as found —
and with a DRIVER click, not `box.click()` from JavaScript. An untrusted
click on this rewrite reports success and leaves the tick on
(`drive.password_email_off`).

**Phone Number, not Home Phone.** `filler.LABEL_FOR` calls it "Home Phone",
which is what the old form said, so the engine's label lookup misses this box
and the bookmarklet has never typed a phone number onto a profile. The driven
path goes by `name` and fills it.

Gender is a Kendo combobox: `Gender_input` is the visible box and `GenderID_364` is the hidden id that actually saves. Write the id.

## Tax & Bank Information — `/employees/<id>/edit/bank-info`

| Field | name |
| --- | --- |
| Social | `SSN` |
| Confirm Social | `ConfirmSSN` |
| Fed. Tax Exempt | `FederalTaxExempt` |
| Withholding State | `WithholdingState` |
| State Tax Exempt | `StateTaxExempt` |
| Marital Status | `MaritalStatus_input` |
| Multiple jobs or spouse work | `MultipleJobs` |
| State To Be Taxed In | `StateToBeTaxedIn_input` |
| Additional Withholding Amount | `AdditionalWithholdingAmount` |

The two Social boxes carry **no label at all**, so a label-only lookup cannot
find them — match on `name`. Several labels on this tab are plainly wrong in
Apex's own markup ("Fed. Tax Exempt" appears on the Marital Status box), which
is the other reason to key on `name` here.

**Claim Dependants has no name**, and it is required — Apex refuses the tab
without it. It is the one field here that has to go by label, and Apex spells
it with an A (`drive.TAX_BY_LABEL`).

## Driving all three tabs

`drive.fill_profile` and `drive.fill_tax` fill the second and third tabs the
way `set_dropdowns` / `type_into` fill the first: real clicks, real
keystrokes. They are keyed on `name` rather than label for the reasons above,
and `drive.FILLS` is checked against `filler.PAGE_OF` by the tests, so a value
cannot be built and previewed and then quietly never typed.

Each tab is its OWN page load, and each one clears "Loading ... data" before
its boxes exist — so after every move: `keep_loaded`, then
`wait_for_field_named` on a box that tab owns (`Gender_input`,
`MaritalStatus_input`). Waiting on the loading message is not enough; that
trap cost a day on the employment tab.

Neither function presses Save. `absent()` names the starred boxes this person
has no value for, because Apex's refusal names only the first one.

## How to re-read this

    PYTHONPATH=. .venv/bin/python -m automations.apex_new_starts.probe_fields --person "First Last"

Writes `output/apex-fields.json`. It opens one record and reads it; it types
nothing, clicks only the Edit control the engine itself uses, and saves nothing.
