# Apex "Add Roster Employee" — what each field actually is

Read off the live form at `apex.herbjoyent.com/employees/new`, 2026-11-08, in
Megan's own Chrome session. **Nothing here is guessed.** Until this existed,
every fix to the Apex fill was reasoning about a page nobody could see, which
is how Marital Status cost five rounds.

## How the form is built, and why it matters

Apex is AngularJS with Kendo widgets, and most "dropdowns" are **two halves**:

- a widget the person sees and clicks, and
- a plain `<input>` carrying the chosen **id**, which is what the form submits.

So a dropdown's `ng-model` is usually a name ending in `ID`. Typing a label
into that input puts a *word* where an *id* belongs: the page looks right and
the save is wrong or silently ignored. Set the widget, let it set the id.

## The map

| Label | Control | `ng-model` |
|---|---|---|
| First Name \* | text input | `$ctrl.user.FirstName` |
| Middle Name | text input | `$ctrl.user.MiddleName` |
| Last Name \* | text input | `$ctrl.user.LastName` |
| User Name \* | text input | `$ctrl.userName` |
| Account Email \* | email input | `$ctrl.user.EmailAddress` |
| Hire Date \* | **Kendo DatePicker** (`k-widget k-datepicker`) | — (widget) |
| Rate of Pay \* | **Kendo NumericTextBox** (`k-widget k-numerictextbox`) | — (widget) |
| Position \* | id input | `$ctrl.employmentRecord.JobTitleID` |
| Pay Frequency \* | id input | `$ctrl.employmentRecord.PayFrequencyID` |
| Basis of Pay \* | id input | `$ctrl.employmentRecord.BasisOfPayID` |
| State Working In \* | id input | `$ctrl.stateWorkingIn` |
| Department | id input | `$ctrl.employmentRecord.CompensationProfileID` |
| Salary | input | `$ctrl.employmentRecord.Salary` |
| Status | button | `$ctrl.employmentRecord.EmployeeStatus` |
| Divisions | ui-select (multiple) | `$ctrl.employmentRecord.Divisions` |
| Time Clock | checkbox | `$ctrl.employmentRecord.TimeClock` |
| Require Break | checkbox | `$ctrl.employmentRecord.RequireBreak` |
| Security role | **radios**, all sharing one model | `$ctrl.roleID` |

### The security role is a radio with a known value

The four roles are radios on `$ctrl.roleID`:

    Office Admin · ICD Payroll Admin · Sales Rep · Owner

**Sales Rep is `value="11"`.** That replaces all the caption-hunting in the
bookmarklet's `role()` / `roleByClicking()` / `roleShape()`, which exists only
because the label text sits behind a styled circle and a `?` help icon.

## Two controls nothing may touch

- **`$ctrl.sendUserPassword`** — the "Send this user a password reset to their
  Account Email" checkbox. Ticking it emails a real person.
- **`$ctrl.employmentRecord.Salary`** — sits directly under Rate of Pay and is
  the wrong box for $10/hr. `test_form_match.py` already guards the label
  match; this names the model so it can be excluded outright.

## Getting to the form

**Navigate in-app, never by URL.** While Apex shows its standing
"Please change your password" banner (which never needs actioning —
[[reference_apex_password_prompt]]), loading `/employees/new` or `/roster`
directly **redirects** to the change-password page. Clicking ROSTER →
Employees → Add Employee lands on the form, banner and all.

`run.py`'s `_open_add_employee` tries `page.goto(.../employees/new)` first and
falls back to clicking the menu. On any session showing that banner the URL
attempt will always miss and the fallback is what works — worth knowing before
someone "fixes" the fallback away.

## The roster, while we were there

- Tabs are `<li class="uib-tab nav-item">` with text exactly `Pending`,
  `All Employees`, `Terminated` — **no counts, no badges**.
- **Add Employee** is `<a class="btn btn-primary">`, text exactly
  `Add Employee` — no plus sign in the text.
- Both tabs carry a filter row: six `<input placeholder="Filter">`, one per
  column (First Name, Last Name, User Name, Job Title, Office, Status), plus an
  **Apply Filters** control.

That last one is worth chasing: if typing into the filter boxes does not filter
until **Apply Filters** is pressed, it is a far better candidate for the
2026-10-02 "adding the missing reps isn't working" than the exact-text matching
that was blamed at the time — and that blame was checked today and is wrong.
