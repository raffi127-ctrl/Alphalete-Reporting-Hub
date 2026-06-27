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
    const reportName = b.title.replace(/^(Run|Hub) glitch —\s*/, "");
    const subject = "🚩 Hub glitch: " + reportName;
    const url = ss.getUrl();

    // Plain-text fallback (clients without HTML). The Details already lead with
    // the cause + the paste-to-Claude block, so just pass them through.
    const plain =
      "A Hub report run failed (auto-filed on the Bug Reports tab).\n\n" +
      b.details + "\n\n" +
      "Submitter: " + b.submitter + "  ·  Priority: " + b.priority +
      "  ·  " + b.submittedAt + "\n" +
      "Bug Reports tab: " + url + "\n";

    // Clean, scannable HTML: header, one-line meta, a "how to fix" callout, then
    // the details (cause + paste-to-Claude block) in a copyable monospace box.
    // (Megan 2026-06-27: clean + engaging, not a wall of text.)
    const html =
      '<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:640px;margin:0 auto;color:#1a1a1a">' +
        '<div style="background:#c0392b;color:#fff;padding:16px 20px;border-radius:10px 10px 0 0">' +
          '<div style="font-size:18px;font-weight:700">🚩 ' + escapeHtml(reportName) + '</div>' +
          '<div style="font-size:13px;opacity:.9;margin-top:3px">A report run failed and was auto-filed.</div>' +
        '</div>' +
        '<div style="border:1px solid #ececec;border-top:none;border-radius:0 0 10px 10px;padding:18px 20px">' +
          '<div style="font-size:12.5px;color:#777;margin-bottom:14px">' +
            '👤 ' + escapeHtml(b.submitter || 'unknown') + '&nbsp;&nbsp;·&nbsp;&nbsp;' +
            '🕐 ' + escapeHtml(b.submittedAt) + '&nbsp;&nbsp;·&nbsp;&nbsp;🔥 ' + escapeHtml(b.priority) +
          '</div>' +
          '<div style="background:#fff8e1;border-left:4px solid #f5a623;border-radius:6px;padding:12px 14px;font-size:14px;margin-bottom:16px">' +
            '💡 <b>To fix:</b> copy the <b>PASTE THIS TO CLAUDE</b> block below and drop it into Claude — it has the cause, the command, and the error.' +
          '</div>' +
          '<pre style="background:#f6f8fa;border:1px solid #e6e9ec;border-radius:8px;padding:14px;font-size:12.5px;line-height:1.55;white-space:pre-wrap;word-break:break-word;font-family:SFMono-Regular,Consolas,monospace">' +
            escapeHtml(b.details) +
          '</pre>' +
          '<div style="margin-top:14px">' +
            '<a href="' + url + '" style="display:inline-block;background:#3498db;color:#fff;text-decoration:none;font-size:13px;padding:8px 14px;border-radius:6px">Open the Bug Reports tab →</a>' +
          '</div>' +
        '</div>' +
      '</div>';

    MailApp.sendEmail({ to: GLITCH_RECIPIENTS, subject: subject, body: plain, htmlBody: html });
    Logger.log("Emailed " + GLITCH_RECIPIENTS + " about bug " + b.id + ".");
  }

  props.setProperty(GLITCH_LAST_SEEN_PROP, newestId);
}

// Minimal HTML escaper for values dropped into the email markup.
function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
