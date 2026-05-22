# Alphalete Org NDS build — current state (updated 2026-05-21 PM)

**If you're a fresh Claude session reading this:** check git log first
(`git log --oneline -10`), then read this file. All code is on `main`.

---

## Where we are: 8 of 13 NDS metrics filling on all 6 visible NDS tabs

Last successful run (verify on the Alphalete Org sheet, col `5/24/26`):

| Rep | Cells | Notes |
|---|---|---|
| Colten Wright - NDS | 8 ✓ | All metrics, after Megan standardized labels |
| Drew Tepper - NDS | 8 ✓ | All metrics |
| Isaiah Revelle - NDS | 8 ✓ | All metrics |
| Jairo Ruiz - NDS | 8 ✓ | All metrics |
| Khalil Mansour - NDS | 8 ✓ | All metrics |
| Maxamed Aden - NDS | 7 | Missing 90 Day Churn (his data is 0% across all buckets) |

**Metrics auto-filled per rep:**
1. Active Selling Heads
2. Scorecard Ranking
3. National AVG for sales (5.3, shared across all NDS tabs)
4. 0-30 Day Churn
5. 60 Day Churn
6. 90 Day Churn
7. Next Up % (59.32%, shared)
8. Extra/Premium % (82.67%, shared)

To re-run: `.venv/bin/python -m automations.alphalete_org_report.opt_nds`
(add `--skip-download` to skip Tableau, `--only "Isaiah"` to scope.)

---

## What's still blocked (5 metrics + Rep Breakdown chart)

The remaining 5 NDS Tableau views all hit the same wall — when the
script connects to Chrome via CDP, the Crosstab Download button stays
disabled in the dialog even when CSV is correctly selected (verified
via DOM inspection). But Megan's manual browser sees CSV+enabled fine.

| View | Worksheet | Blocked metric |
|---|---|---|
| SARAPLUSSALESSUMMARY (iid=2) | "Sara Plus Sales Summary (2)" | Personal Production + New Lines per-rep |
| NDSWeeklyMetricsRep | "Weekly Metrics (Rep)" | 0-30 Day Cancel Rate 4wk avg |
| ACTIVATIONRATES | "Activation Rates (ICD)" | Activation % by Week |
| LeadPenetrationOverview | (worksheet name TBD) | Total Leads |
| DirectDeposit | (worksheet name TBD — not "Consultant ORG Title") | Direct Deposit |
| ProductSalesSummaryRep | "Sales By ICD (Weekly View)" | Rep Breakdown chart at bottom |

**Also computed (depends on per-rep New Lines):**
- AVG Apps Per Active Headcount = New Lines / Active Selling Heads

**Hypothesis on the root cause:** The debug-port Chrome session
(launched via the Hub) connects to Tableau differently than Megan's
regular browser. Tableau may be limiting CSV exports for the CDP-attached
session — possibly because of stale cookies, missing user preferences,
or a security restriction on automated sessions. Latest debug
discovered the radio test-ID is `-RadioButton` suffixed (not `-Label`)
and that fix is committed; but the Download button stays disabled even
after correctly clicking CSV.

**Next investigation (if continuing):** compare cookies, localStorage,
and user identity between the debug Chrome's Tableau session and
Megan's regular browser's Tableau session. May need to log into Tableau
directly in the debug Chrome (not via ownerville SSO) to see if that
unblocks downloads.

**Workaround for Monday:** the 5 missing metrics can be entered
manually by Eve until the Tableau download issue is resolved.

---

## Key fixes shipped today (all on main)

| Commit | What |
|---|---|
| 80b3947 | Hub "🔄 Reset Google Sign-In" button — auto-resolves OAuth lockouts (Maud's issue) |
| 24161dc | NDS comma-strip + Extra/Premium % + CSV/Excel format fallback in download_crosstab |
| (uncommitted, environmental) | Fixed `.venv/bin/python` symlink — was pointing to Python 3.9, now correctly points to Python 3.14.5 |

---

## Other things wrapped up today

- ✅ Python upgraded from 3.9 to 3.14.5 (real fix for asyncio race that was killing Tableau downloads)
- ✅ Streamlit credentials file created at `~/.streamlit/credentials.toml` to skip welcome prompt after venv rebuilds
- ✅ Colten Wright's tab labels standardized by Megan to match Isaiah's
- ✅ Hub OAuth-reset button live — next teammate to hit token expiry has a one-click fix

---

## Open asks from Megan

- **B2B Tableau URL(s)** — for Valeria Tristan's B2B program build
- **BOX / Retail / JE / Frontier walkthroughs** — for those program builds
- **The 5 stuck Tableau downloads** — need someone to dig into the debug Chrome vs regular Chrome session difference

---

## How to continue in a fresh Claude session

If you start a new chat:

1. Tell new Claude: "Read MORNING_SUMMARY_NDS_BUILD.md and the
   `resources/opt-section/alphalete-org-campaign-sources.md` doc, then
   tell me where we are."
2. New Claude will read both, scan git log for recent commits, and
   summarize the state.
3. Then say what you want to work on next (B2B, Tableau debug, etc.)

You will NOT lose progress. Everything important is in git + the docs.
