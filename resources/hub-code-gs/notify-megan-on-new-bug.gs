/**
 * GLITCH EMAIL section of the Hub intake Sheet's Code.gs.
 *
 * This is ONLY the bottom "glitch" block of the full Code.gs that lives in
 * the intake Sheet (the full file also handles backlog + bug-intake emails).
 * When a Hub report run fails, dashboard.py's _file_run_glitch appends a
 * "Run glitch —" row to the Bug Reports tab; a 5-minute time-driven trigger
 * runs notifyMeganOnNewBug, which emails the glitch details.
 *
 * RECIPIENTS: Megan + Eve (2026-05-29 — Megan asked that Eve get glitch
 * emails "like I do"). Add more anytime — GLITCH_RECIPIENTS is a plain
 * comma-separated string.
 *
 * TO UPDATE IN THE SHEET (no re-setup needed — function/trigger names are
 * unchanged): Extensions → Apps Script, replace the existing glitch block
 * (from `const GLITCH_BUG_TAB` to end of file) with this, Save. The
 * existing 5-minute trigger keeps firing the same notifyMeganOnNewBug.
 */

const GLITCH_BUG_TAB        = "Bug Reports";
const GLITCH_TITLE_PREFIX   = "Run glitch —";          // only auto-file failures
const GLITCH_LAST_SEEN_PROP = "BUG_REPORTS_LAST_SEEN_ID";
// Who gets the glitch email — comma-separated. Add teammates here anytime.
const GLITCH_RECIPIENTS     = "meganhidalgo1191@gmail.com,alphaletereporting@gmail.com"; // Megan + Eve

function setupNotifyMeganTrigger() {
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === "notifyMeganOnNewBug")
    .forEach(t => ScriptApp.deleteTrigger(t));

  ScriptApp.newTrigger("notifyMeganOnNewBug")
    .timeBased()
    .everyMinutes(5)
    .create();

  Logger.log("Installed 5-minute trigger for notifyMeganOnNewBug.");
}

function notifyMeganOnNewBug() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName(GLITCH_BUG_TAB);
  if (!sh) { Logger.log("Bug Reports tab not found — skipping."); return; }

  const lastRow = sh.getLastRow();
  if (lastRow < 2) { Logger.log("No bug rows yet."); return; }

  const headers = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0];
  const rows    = sh.getRange(2, 1, lastRow - 1, headers.length).getValues();

  const col = name => headers.indexOf(name);
  const idCol        = col("ID");
  const titleCol     = col("Title");
  const typeCol      = col("Type");
  const detailsCol   = col("Details");
  const submitterCol = col("Submitted By");
  const submittedAt  = col("Submitted At");
  const priorityCol  = col("Priority");
  if (idCol < 0 || titleCol < 0) {
    Logger.log("Bug Reports headers don't match — bailing.");
    return;
  }

  const props    = PropertiesService.getScriptProperties();
  const lastSeen = props.getProperty(GLITCH_LAST_SEEN_PROP) || "";

  let newestId = lastSeen;
  const toEmail = [];
  for (const r of rows) {
    const id    = String(r[idCol] || "");
    const title = String(r[titleCol] || "");
    if (!id) continue;
    if (id > newestId) newestId = id;
    if (lastSeen && id > lastSeen) {
      if (!GLITCH_TITLE_PREFIX || title.indexOf(GLITCH_TITLE_PREFIX) === 0) {
        toEmail.push({
          id, title,
          type:        String(r[typeCol] || ""),
          details:     String(r[detailsCol] || ""),
          submitter:   String(r[submitterCol] || ""),
          submittedAt: String(r[submittedAt] || ""),
          priority:    String(r[priorityCol] || ""),
        });
      }
    }
  }

  // First-ever run: just mark the newest ID seen, don't email backfill.
  if (!lastSeen) {
    props.setProperty(GLITCH_LAST_SEEN_PROP, newestId);
    Logger.log("First run — marked " + newestId + " as seen, no email sent.");
    return;
  }

  if (!toEmail.length) {
    Logger.log("No new bugs since " + lastSeen + ".");
    if (newestId > lastSeen) props.setProperty(GLITCH_LAST_SEEN_PROP, newestId);
    return;
  }

  for (const b of toEmail) {
    const subject = "🚩 Hub run glitch: " + b.title.replace(/^Run glitch —\s*/, "");
    const body =
      "A Hub report run just failed and was auto-filed on the Bug Reports tab.\n\n" +
      "Title:      " + b.title + "\n" +
      "Submitter:  " + b.submitter + "\n" +
      "Priority:   " + b.priority + "\n" +
      "Submitted:  " + b.submittedAt + "\n" +
      "ID:         " + b.id + "\n\n" +
      "Sheet link: " + ss.getUrl() + "\n\n" +
      "--- Details ---\n" + b.details + "\n";
    MailApp.sendEmail(GLITCH_RECIPIENTS, subject, body);
    Logger.log("Emailed " + GLITCH_RECIPIENTS + " about bug " + b.id + ".");
  }

  props.setProperty(GLITCH_LAST_SEEN_PROP, newestId);
}
