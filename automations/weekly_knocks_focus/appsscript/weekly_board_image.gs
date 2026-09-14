/**
 * Weekly Knock Dispositions board -> its owner's Focus Report tab
 * (Rafael via Eve, 2026-09-14).
 *
 * Every week the Weekly Knock Dispositions board of each office is pasted into
 * that office's tab of the ATT Program - Focus Report, so the per-rep
 * breakdown sits next to the office numbers. ONE image per tab: last week's is
 * removed before the new one goes in, they never pile up.
 *
 * WHY A SCRIPT AND NOT =IMAGE(url): =IMAGE needs a PUBLIC link, and the board
 * carries rep names and numbers. This pastes the picture straight into the
 * sheet, so only people who can already open the Focus Report ever see it.
 *
 * INSTALL (once, by someone with EDIT access to the Focus Report):
 *   1. Focus Report -> Extensions -> Apps Script -> new file, paste this.
 *   2. Project Settings (gear) -> Script properties -> Add:
 *        WKF_KEY = <the key Claude gave you>
 *   3. Deploy -> New deployment -> type "Web app":
 *        Execute as: Me        Who has access: Anyone
 *      ("Anyone" only because Lucy calls it without a Google login — the
 *       WKF_KEY check below is what stops anyone else from using it.)
 *   4. Authorize, then send Claude the /exec URL.
 *
 * Lucy POSTs JSON: {key, tab, row, col, png_b64, name, tag, width}
 */
var DEFAULT_TAG = 'WEEKLY_KNOCKS_BOARD';

function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents);
    var key = PropertiesService.getScriptProperties().getProperty('WKF_KEY');
    if (!key || body.key !== key) return out_({ ok: false, error: 'bad key' });

    var sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(body.tab);
    if (!sh) return out_({ ok: false, error: 'no tab named ' + body.tab });

    var tag = body.tag || DEFAULT_TAG;
    // Last week's board comes off first — found by its alt-text title, so a
    // picture somebody pasted by hand is never touched.
    var removed = 0;
    sh.getImages().forEach(function (img) {
      if (img.getAltTextTitle() === tag) { img.remove(); removed++; }
    });

    var blob = Utilities.newBlob(Utilities.base64Decode(body.png_b64),
                                 'image/png', body.name || 'weekly_board.png');
    var img = sh.insertImage(blob, Number(body.col), Number(body.row));
    img.setAltTextTitle(tag);
    img.setAltTextDescription(body.name || '');
    if (body.width) {
      var ratio = Number(body.width) / img.getWidth();
      img.setWidth(Number(body.width));
      img.setHeight(Math.round(img.getHeight() * ratio));
    }
    return out_({ ok: true, removed: removed,
                  width: img.getWidth(), height: img.getHeight() });
  } catch (err) {
    return out_({ ok: false, error: String(err) });
  }
}

function out_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
      .setMimeType(ContentService.MimeType.JSON);
}
