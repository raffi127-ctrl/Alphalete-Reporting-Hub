/**
 * JD's Focus Report Automation — Google Apps Script (REFERENCE ONLY).
 *
 * This is the CURRENT semi-automated system: a human downloads CSVs from
 * Tableau, pastes them into hidden "_*" input tabs, and runs a menu item.
 * The script parses the pasted CSV and writes values into each ICD tab.
 *
 * We are NOT porting this as-is. It is kept here as the spec for:
 *   - which metric maps to which Tableau-CSV column
 *   - which metric maps to which tab row label / section
 *   - the ICD name aliases
 * Our rebuild pulls from Tableau directly (no manual downloads) and writes
 * with the same label-based / date-column logic as the recruiting fill.
 */

// ============================================================
// MENU
// ============================================================
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('🤖 Automations')
    .addItem('Update Recruiting (Test: 3 ICDs) — PAUSED', 'updateRecruitingTest')
    .addSeparator()
    .addItem('Update Internet Metrics (Test: 3 ICDs)', 'updateInternetMetricsTest')
    .addItem('Update Internet Metrics (All ICDs)', 'updateInternetMetricsAll')
    .addSeparator()
    .addItem('Update OPT Metrics (Test: 3 ICDs)', 'updateOPTMetricsTest')
    .addItem('Update OPT Metrics (All ICDs)', 'updateOPTMetricsAll')
    .addSeparator()
    .addItem('Update Wireless Metrics (Test: 3 ICDs)', 'updateWirelessMetricsTest')
    .addItem('Update Wireless Metrics (All ICDs)', 'updateWirelessMetricsAll')
    .addToUi();
}

// ============================================================
// SHARED CONSTANTS / ALIASES / SECTION ANCHORS
// ============================================================
const DATE_HEADER_ROW = 1;

const ICD_ALIASES = {
  "Raf Hidalgo":    ["Raf Hidalgo", "Rafael Hidalgo"],
  "JR Young":       ["JR Young", "John Richard Young"],
  "Zach Hogue":     ["Zach Hogue", "Zachary Hogue"],
  "Sharon Stephen": ["Sharon Stephen", "FNU Stephen Sharon"],
  "Hammad Haque":   ["Hammad Haque", "Salik Haque", "Salik Mallick"]
};

const KNOWN_SECTION_ANCHORS = [
  "Office Metrics",
  "Wireless Metrics",
  "ATT INT Office Performance Tracker (OPT)",
  "OPT",
  "Extra Data"
];

// ============================================================
// OPT (ATT ICD Summary + INT ICD Summary) CONFIG
// ============================================================
// Two CSV exports: _ICD_Summary_ATT and _ICD_Summary_INT.
// ICD name column = "ICD Owner Name". National rows = "Grand Total".
const OPT_SECTION = "OPT";
const OPT_CSV_INPUT_TAB_ATT = "_ICD_Summary_ATT";
const OPT_CSV_INPUT_TAB_INT = "_ICD_Summary_INT";

const OPT_METRICS = [
  { metric: "Scorecard Ranking",              labelB: "Scorecard Ranking",              csvHeader: "Ranking",                 source: "ATT" },
  { metric: "Active Headcount on Tableau",    labelB: "Active Headcount on Tableau",    csvHeader: "Rep Count",               source: "ATT" },
  { metric: "National AVG for sales",         labelB: "National AVG for sales",         csvHeader: "Sales Per Rep Avg",       source: "ATT", useTotalRow: true, altLabels: ["National AVG Apps"] },
  { metric: "% of Wireless Rep Count",        labelB: "% of Wireless Rep Count",        csvHeader: "% Wireless rep count",    source: "ATT", altLabels: ["% of Wireless Attachment", "% Wireless Rep Count", "% Wireless Attachment"] },
  { metric: "New Internets",                  labelB: "New Internets",                  csvHeader: "New Internet",            source: "ATT" },
  { metric: "Upgrades",                       labelB: "Upgrades",                       csvHeader: "Upgrd Internet",          source: "ATT" },
  { metric: "DTV",                            labelB: "DTV",                            csvHeader: "Video Sales",             source: "ATT" },
  { metric: "New Lines",                      labelB: "New Lines",                      csvHeader: "Wrlss Lines New/Port",    source: "ATT" },
  { metric: "AVG New INT Per Active Headcount", labelB: "AVG New INT Per Active Headcount", csvHeader: "New Int Sales Per Rep Avg", source: "INT" },
  { metric: "National New INT AVG",           labelB: "National New INT AVG",           csvHeader: "New Int Sales Per Rep Avg", source: "INT", useTotalRow: true }
];

// ============================================================
// OFFICE METRICS — INTERNET CONFIG
// ============================================================
// CSV export: _Internet_Metrics. ICD column = "ICD Owner Name (rep)".
const INTERNET_SECTION = "Office Metrics";
const INTERNET_METRICS = [
  { metric: "1 GIG%",                  labelB: "1 GIG%",                  csvHeader: "New Internet 1Gig+ Mix% (Metrics)" },
  { metric: "6+ days out scheduled",   labelB: "6+ days out scheduled",   csvHeader: "% of sales scheduled 6+ days out (4 wks)" },
  { metric: "0-30 Day Cancel Rate",    labelB: "0-30 Day Cancel Rate",    csvHeader: "0-30 day internet cancel rate" },
  // "30-60 Day Cancel Rate" is a formula — skip
  { metric: "Activation /Approval %",  labelB: "Activation /Approval %",  csvHeader: "Rolling 4 Weeks" },
  { metric: "30-60 activation rate %", labelB: "30-60 activation rate %", csvHeader: "30-60 day New Internet activation rate" },
  { metric: "0-30 Day Churn",          labelB: "0-30 Day Churn",          csvHeader: "0-30 day new internet churn rate" }
];

// ============================================================
// WIRELESS METRICS CONFIG
// ============================================================
// CSV export: _Wireless_Metrics. ICD column = "ICD Owner Name (rep)".
const WIRELESS_SECTION = "Wireless Metrics";
const WIRELESS_METRICS = [
  { metric: "BYOD Lines",                    labelB: "BYOD Lines",                    csvHeader: "BYOD Lines (Metrics)" },
  { metric: "BYOD %",                        labelB: "BYOD %",                        csvHeader: "BYOD Line % (Metrics)" },
  { metric: "New Lines %",                   labelB: "New Lines %",                   csvHeader: "New Line % (Metrics)" },
  { metric: "Approval % (Rolling 4 weeks)",  labelB: "Approval % (Rolling 4 weeks)",  csvHeader: "Approval % (Rolling 4 Weeks)" },
  { metric: "0-30 day cancel Rate",          labelB: "0-30 day cancel Rate",          csvHeader: "0-30 day wireless cancel rate" },
  { metric: "0-30 day Wireless Cancels",     labelB: "0-30 day Wireless Cancels",     csvHeader: "0-30 day wireless cancels" },
  { metric: "0-30 Day Churn",                labelB: "0-30 Day Churn",                csvHeader: "0-30 day wireless churn rate" },
  { metric: "90 Day Churn",                  labelB: "90 Day Churn",                  csvHeader: "90 day wireless churn rate" },
  { metric: "30-60 Activation Rate",         labelB: "30-60 Activation Rate",         csvHeader: "30-60 Activation Rate" },
  { metric: "Extra / Premium Plan % Metrics", labelB: "Extra / Premium Plan % Metrics", csvHeader: "Extra/Premium Plan % (Metrics)", altLabels: ["Extra / Preimum Plan % Metrics"] },
  { metric: "Next up %",                     labelB: "Next up %",                     csvHeader: "Next Up % (Metrics)" }
];

/*
 * NOTES carried over from JD's original (behaviour to preserve / fix):
 *  - Input tab format: A1 = week-ending date, row 3 = CSV headers, row 4+ = data.
 *  - Writes: row found by label in column B (scoped to the section anchor),
 *    column found by matching the week-ending date in row 1.
 *  - National-average metrics use the CSV's "Grand Total" row and write the
 *    same value to every tab.
 *  - Known accuracy bugs to fix in the rebuild: New Lines not pulled for
 *    anyone; some owners (Edgar, Carissa) not filled.
 *  - Raf Hidalgo's OPT tab uses a different section header — JD excluded him.
 *
 * Full original menu/parse/write functions (updateOPTMetrics*, parseOPTCsv,
 * processOPTIcd, the Internet + Wireless equivalents, and the shared
 * helpers buildLabelRowMapInSection / findDateColumn / normalizeLabel) are
 * the spec we are reimplementing in Python — see the chat history for the
 * verbatim source if a behavioural detail needs checking.
 */
