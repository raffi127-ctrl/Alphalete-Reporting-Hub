# Apex after the Beta rewrite — what is actually on the page

Read off the live site on 2026-11-11 with `output/apex_fields.py` (read only,
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

| On the page | type | name |
| --- | --- | --- |
| Rate of Pay * | text | *(none — Kendo widget, match by label)* |
| **Salary** | text | *(none)* — **NEVER WRITE THIS.** It sits under Rate of Pay and is the wrong box for an hourly rate. |
| Commission Threshold | text | *(none)* |
| Time Clock | checkbox | `TimeClock_192` |
| Require Break | checkbox | `RequireBreak_192` |
| Track Time Entries in Real Time | checkbox | `TrackRealTime_192` |
| Divisions | search | *(none)* |
| Office Admin | radio | `Role_6_192` |
| ICD Payroll Admin | radio | `Role_8_192` |
| **Sales Rep** | radio | `Role_11_192` |
| Owner | radio | `Role_12_192` |

The `_192` suffix is the OFFICE, not the person — these names are per office
block, so they change for another office and must never be hard-coded. Sales
Rep is still role 11, which is what `ROLE_VALUE` has always said.

**FIVE FIELDS THE OLD MAP WANTS ARE NOT ON THIS PAGE**: Position, State
Working In, Basis of Pay, Pay Frequency, Department. The page carries an
office block headed "Alphalete Marketing Inc. – Arlington" with an `Add Office`
button and chips (`× General`), so they are most likely inside that block and
not expanded when the dump ran. **This is the open question** — expand it and
re-run the probe before changing the map.

## User Profile & Account — `/employees/<id>/edit/user-profile`

Clean `name` attributes; map on these rather than labels.

| Field | name |
| --- | --- |
| First Name * | `FirstName` |
| Middle Name | `MiddleName` |
| Last Name * | `LastName` |
| Account Email * | `EmailAddress` |
| Date of Birth * | `BirthDay` |
| Gender * | `Gender_input` |
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
that writes this tab has to set it deliberately, never leave it as found.

Gender is a Kendo combobox (`Gender_input`), not a `<select>`.

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

## How to re-read this

    PYTHONPATH=. .venv/bin/python output/apex_fields.py --person "First Last"

Writes `output/apex-fields.json`. It opens one record and reads it; it types
nothing, clicks only the Edit control the engine itself uses, and saves nothing.
