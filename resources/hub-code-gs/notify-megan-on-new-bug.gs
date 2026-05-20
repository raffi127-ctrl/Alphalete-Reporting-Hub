/**
 * notifyMeganOnNewBug — emails Megan whenever a new row lands on the
 * "Bug Reports" tab of the Hub intake Sheet.
 *
 * The Hub's _file_run_glitch (dashboard.py) appends a row to this tab any
 * time a report run fails. Without this script, Megan only sees the row by
 * opening the Sheet. With this script + a 5-minute time-driven trigger,
 * Megan gets an email with the full glitch details automatically.
 *
 * SETUP (one-time, in the intake Sheet's Apps Script editor):
 *   1) Paste this whole file into Code.gs (or a new .gs file beside it).
 *   2) Run `setupNotifyMeganTrigger` once. Approve any permission prompts.
 *      It installs a time-driven trigger that fires every 5 minutes.
 *   3) Optional: run `notifyMeganOnNewBug` manually once to confirm the
 *      "no new bugs" log line appears (or to send a backfill email if old
 *      rows haven't been notified yet).
 *
 * BEHAVIOR:
 *   - First run: marks the current newest bug ID as "seen" and sends nothing
 *     (so old bugs don't suddenly all email Megan).
 *   - Subsequent runs: emails Megan for every row whose ID is greater than
 *     the last seen ID, then advances the marker.
 *   - Megan's email address is read from a script property MEGAN_EMAIL.
 *     Defaults to meganhidalgo1191@gmail.com if not set.
 *   - Only emails for rows whose Title starts with "Run glitch —"
 *     (auto-filed report failures). Manual bug submissions are not emailed.
 *     Change BUG_TITLE_PREFIX = "" to email for every new bug.
 */

const BUG_TAB           = "Bug Reports";
const BUG_TITLE_PREFIX  = "Run glitch —";        // only auto-file failures
const DEFAULT_MEGAN     = "meganhidalgo1191@gmail.com";
const LAST_SEEN_PROP    = "BUG_REPORTS_LAST_SEEN_ID";
const MEGAN_EMAIL_PROP  = "MEGAN_EMAIL";

function setupNotifyMeganTrigger() {
  // Remove any existing trigger for this handler (idempotent re-run).
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
  const sh = ss.getSheetByName(BUG_TAB);
  if (!sh) { Logger.log("Bug Reports tab not found — skipping."); return; }

  const lastRow = sh.getLastRow();
  if (lastRow < 2) { Logger.log("No bug rows yet."); return; }

  const headers = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0];
  const rows    = sh.getRange(2, 1, lastRow - 1, headers.length).getValues();

  const col = name => headers.indexOf(name);
  const idCol       = col("ID");
  const titleCol    = col("Title");
  const typeCol     = col("Type");
  const detailsCol  = col("Details");
  const submitterCol= col("Submitted By");
  const submittedAt = col("Submitted At");
  const priorityCol = col("Priority");
  if (idCol < 0 || titleCol < 0) {
    Logger.log("Bug Reports headers don't match — bailing.");
    return;
  }

  const props    = PropertiesService.getScriptProperties();
  const lastSeen = props.getProperty(LAST_SEEN_PROP) || "";
  const meganEmail = props.getProperty(MEGAN_EMAIL_PROP) || DEFAULT_MEGAN;

  // Bug IDs are timestamps like "20260520143000" — string compare works
  // and gives us a stable monotonic ordering.
  let newestId = lastSeen;
  const toEmail = [];
  for (const r of rows) {
    const id    = String(r[idCol] || "");
    const title = String(r[titleCol] || "");
    if (!id) continue;
    if (id > newestId) newestId = id;
    if (lastSeen && id > lastSeen) {
      if (!BUG_TITLE_PREFIX || title.indexOf(BUG_TITLE_PREFIX) === 0) {
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
    props.setProperty(LAST_SEEN_PROP, newestId);
    Logger.log("First run — marked " + newestId + " as seen, no email sent.");
    return;
  }

  if (!toEmail.length) {
    Logger.log("No new bugs since " + lastSeen + ".");
    if (newestId > lastSeen) props.setProperty(LAST_SEEN_PROP, newestId);
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
    MailApp.sendEmail(meganEmail, subject, body);
    Logger.log("Emailed Megan about bug " + b.id + ".");
  }

  props.setProperty(LAST_SEEN_PROP, newestId);
}
