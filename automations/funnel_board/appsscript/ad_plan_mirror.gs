/**
 * Ad Plan true mirror (Carlos, 2026-09-07).
 * The formula mirror (INDIRECT over IMPORTRANGE) can only carry values, so
 * Ad Plan never showed the source tracker's colors. This script repaints the
 * view area with a real copy — values AND formatting — of the selected
 * person's actual "*Indeed Tracking" page, pulled straight from their own
 * spreadsheet (the URL is parsed out of their hidden tab's IMPORTRANGE, so
 * there is no separate config to maintain).
 *
 * Wiring it reuses: B1 picker, AD1:AE40 name→tab map. Untouched.
 * What changes: A2 is no longer a formula — the area is a pasted snapshot,
 * refreshed when B1 changes and hourly by trigger.
 *
 * Install once: open this script from the sheet (Extensions -> Apps Script),
 * pick `install` in the function dropdown, Run, approve the permissions.
 * If a person's tracker sheet is not shared with the installing account the
 * repaint falls back to a plain values-only copy from their hidden tab and
 * notes it in A1's row (source sharing is a manual human step, same lesson
 * as captainship_boards 8/27).
 */

var AP = 'Ad Plan';
var MAX_ROWS = 999;   // paints A2:Z1000, same footprint as the old formula
var MAX_COLS = 26;    // A..Z; helper columns AA+ are never touched

function install() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    var fn = t.getHandlerFunction();
    if (fn === 'onEditInstallable' || fn === 'refreshCurrent') ScriptApp.deleteTrigger(t);
  });
  var ss = SpreadsheetApp.getActive();
  ScriptApp.newTrigger('onEditInstallable').forSpreadsheet(ss).onEdit().create();
  ScriptApp.newTrigger('refreshCurrent').timeBased().everyHours(1).create();
  refreshCurrent();
}

function onEditInstallable(e) {
  var r = e.range;
  if (r.getSheet().getName() !== AP || r.getA1Notation() !== 'B1') return;
  repaint();
}

function refreshCurrent() {
  repaint();
}

function repaint() {
  var ss = SpreadsheetApp.getActive();
  var ap = ss.getSheetByName(AP);
  var name = String(ap.getRange('B1').getValue()).trim();
  var area = ap.getRange(2, 1, MAX_ROWS, MAX_COLS);
  if (!name) return;

  var map = ap.getRange('AD1:AE40').getValues();
  var tab = '';
  for (var i = 0; i < map.length; i++) {
    if (String(map[i][0]).trim() === name) { tab = String(map[i][1]).trim(); break; }
  }
  area.clear();
  if (!tab) {
    ap.getRange('A2').setValue('No ad tracker connected for ' + name);
    return;
  }

  var hidden = ss.getSheetByName(tab);
  if (!hidden) {
    ap.getRange('A2').setValue('Mapped tab "' + tab + '" not found for ' + name);
    return;
  }

  // The hidden tab's A2 IMPORTRANGE tells us where the real page lives.
  var f = hidden.getRange('A2').getFormula();
  var m = f.match(/IMPORTRANGE\(\s*"([^"]+)"\s*,\s*"([^"!]+)!/i);
  var src = null;
  if (m) {
    try {
      src = SpreadsheetApp.openByUrl(m[1]).getSheetByName(m[2]);
    } catch (err) {
      src = null; // not shared with this account, or sheet gone
    }
  }

  if (src) {
    copyLook_(src, ap, name + ' — live copy of their tracker page');
  } else {
    // Fallback: values-only copy of the hidden tab (what the old formula showed).
    copyLook_(hidden, ap, name + ' — VALUES ONLY (tracker sheet not shared with this account)');
  }
}

// Copy the used range of src into Ad Plan starting at A2: values, number
// formats, backgrounds, font colour/weight/style/size, alignment, wrap,
// and column widths. Cross-file Range.copyTo is not allowed, hence by hand.
function copyLook_(src, ap, note) {
  var nr = Math.min(src.getLastRow(), MAX_ROWS);
  var nc = Math.min(src.getLastColumn(), MAX_COLS);
  if (nr < 1 || nc < 1) { ap.getRange('A2').setValue('Source page is empty'); return; }
  var s = src.getRange(1, 1, nr, nc);
  var d = ap.getRange(2, 1, nr, nc);
  d.setValues(s.getValues());
  d.setNumberFormats(s.getNumberFormats());
  d.setBackgrounds(s.getBackgrounds());
  d.setFontColors(s.getFontColors());
  d.setFontWeights(s.getFontWeights());
  d.setFontStyles(s.getFontStyles());
  d.setFontSizes(s.getFontSizes());
  d.setHorizontalAlignments(s.getHorizontalAlignments());
  d.setWrapStrategies(s.getWrapStrategies());
  for (var c = 1; c <= nc; c++) ap.setColumnWidth(c, src.getColumnWidth(c));
  ap.getRange('F1').setValue(note + ' · refreshed ' +
    Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'M/d h:mm a'));
}
