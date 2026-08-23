/**
 * Two-way goal mirror (Carlos, 2026-08-22).
 * Focus Report column B shows each metric's goal via VLOOKUP into Goals.
 * Editing an AMBER goal cell on Focus Report writes the value into the
 * picked manager's row on Goals, then restores the VLOOKUP — so the two
 * tabs always mirror. Grey (computed) cells are left alone: any edit there
 * is simply reverted to the formula.
 *
 * Install once: Extensions -> Apps Script -> paste this file -> Save.
 * No triggers to configure — onEdit(e) is automatic for human edits.
 */
var GOAL_MAP = {
  'Sent to Call List':            { col: 'F', idx: 5,  pct: false },
  'Removal %':                    { col: 'E', idx: 4,  pct: true  },
  'Retention to Call List':       { col: 'G', idx: 6,  pct: true  },
  '1st Show %':                   { col: 'J', idx: 9,  pct: true  },
  '2nd Booked % of 1st showed':   { col: 'K', idx: 10, pct: true  },
  '2nd Show %':                   { col: 'N', idx: 13, pct: true  },
  'Offer % of 2nd showed':        { col: 'O', idx: 14, pct: true  },
  'BOB Conversion':               { col: 'R', idx: 17, pct: true  },
  'New Start Show %':             { col: 'U', idx: 20, pct: true  }
};

// ---- campaign zone (2026-08-23): rows CAMP_Z0..CAMP_Z0+CAMP_SLOTS-1 are the
// per-campaign sales block, backed by the hidden 'Campaign Log' tab. Typed
// goals (col B) and manual TEAM numbers (WK columns) are written THERE and the
// lookup formula restored — the hourly rebuild only redraws formulas, so the
// typed numbers live on. These two constants mirror
// automations/org_campaign_metrics/layout.py (ZONE_START / N_SLOTS); build.py
// asserts on drift.
var CAMP_Z0 = 30;
var CAMP_SLOTS = 44;

function onEdit(e) {
  var sh = e.range.getSheet();
  if (sh.getName() !== 'Focus Report') return;
  if (e.range.getNumRows() !== 1 || e.range.getNumColumns() !== 1) return;
  var row0 = e.range.getRow();
  if (row0 >= CAMP_Z0 && row0 < CAMP_Z0 + CAMP_SLOTS) {
    campaignEdit(e, sh, row0, e.range.getColumn());
    return;
  }
  if (e.range.getColumn() !== 2) return;
  var row = row0;
  if (row < 4) return;                                   // pickers/headers
  var label = String(sh.getRange(row, 1).getValue()).trim();
  var restore = function (idx) {
    e.range.setFormula(
      '=IFERROR(VLOOKUP($A$1,Goals!$B:$U,' + idx + ',FALSE),"")');
  };
  var m = GOAL_MAP[label];
  if (!m) {                                              // grey = computed
    // put the formula back if we know which one; otherwise leave untouched
    return;
  }
  var v = e.value;
  if (v === undefined || v === null || v === '') { restore(m.idx); return; }
  v = parseFloat(String(v).replace('%', ''));
  if (isNaN(v)) { restore(m.idx); return; }
  if (m.pct && v > 1.5) v = v / 100;                     // "15" means 15%
  var manager = String(sh.getRange('A1').getValue()).trim();
  var goals = e.source.getSheetByName('Goals');
  var names = goals.getRange('B1:B60').getValues();
  for (var i = 0; i < names.length; i++) {
    if (String(names[i][0]).trim() === manager) {
      goals.getRange(m.col + (i + 1)).setValue(v);
      restore(m.idx);
      e.source.toast(label + ' -> ' + v + ' saved to Goals for ' + manager);
      return;
    }
  }
  restore(m.idx);
  e.source.toast('Could not find "' + manager + '" on Goals — nothing saved');
}

// ---------------------------------------------------------------- campaign

function _colLetter(c) {
  var s = '';
  while (c > 0) { var r = (c - 1) % 26; s = String.fromCharCode(65 + r) + s;
                  c = Math.floor((c - 1) / 26); }
  return s;
}

function _campValueFormula(colL, slot) {
  return '=IFERROR(INDEX(\'Campaign Log\'!$N:$N,MATCH($A$1&"|"&TEXT(' + colL +
         '$2,"yyyy-mm-dd")&"|"&' + slot +
         ',\'Campaign Log\'!$J:$J,0)),"")';
}

function _campGoalFormula(slot) {
  return '=IFERROR(INDEX(\'Campaign Log\'!$R:$R,MATCH($A$1&"|"&' + slot +
         ',\'Campaign Log\'!$P:$P,0)),"")';
}

function _upsert(clSheet, keyColA1, key, rowValues, width) {
  // find the key in the key column; overwrite its row or append below the
  // last used key. rowValues[0] must be the key itself.
  var keys = clSheet.getRange(keyColA1 + '2:' + keyColA1 + '20000').getValues();
  var hit = -1, last = 0;
  for (var i = 0; i < keys.length; i++) {
    if (String(keys[i][0]) === key) { hit = i; break; }
    if (String(keys[i][0]) !== '') last = i + 1;
  }
  var r = (hit >= 0 ? hit : last) + 2;
  var colStart = clSheet.getRange(keyColA1 + '1').getColumn();
  var rng = clSheet.getRange(r, colStart, 1, width);
  rng.setNumberFormat('@');                       // keep "79%"/"6.4" as text
  rng.setValues([rowValues]);
}

function campaignEdit(e, sh, row, col) {
  var cl = e.source.getSheetByName('Campaign Log');
  if (!cl) return;
  var manager = String(sh.getRange('A1').getValue()).trim();
  var slot = row - CAMP_Z0 + 1;
  // manager -> campaign, then campaign|slot -> kind
  var map = cl.getRange('A2:B60').getValues();
  var campaign = '';
  for (var i = 0; i < map.length; i++) {
    if (String(map[i][0]).trim() === manager) { campaign = String(map[i][1]).trim(); break; }
  }
  var kind = '';
  if (campaign) {
    var lay = cl.getRange('D2:G400').getValues();
    var want = campaign + '|' + slot;
    for (var j = 0; j < lay.length; j++) {
      if (String(lay[j][0]) === want) { kind = String(lay[j][3]).trim(); break; }
    }
  }
  var colL = _colLetter(col);
  var isWk = String(sh.getRange(3, col).getValue()).indexOf('WK ') === 0;
  var v = (e.value === undefined || e.value === null) ? '' : String(e.value).trim();

  if (col === 1) return;                    // labels: the hourly rebuild fixes
  if (col === 2) {                                            // goal cell
    if (kind === 'mg' || kind === 'g') {
      if (v !== '') {
        _upsert(cl, 'P', manager + '|' + slot, [manager + '|' + slot, manager, v], 3);
        e.source.toast(v + ' saved as the goal');
      } else {
        _upsert(cl, 'P', manager + '|' + slot, [manager + '|' + slot, manager, ''], 3);
      }
    } else if (v !== '' && kind !== '') {
      e.source.toast('No goal lives on this row');
    }
    e.range.setFormula(_campGoalFormula(slot));
    return;
  }
  if (!isWk) {                              // day cells carry no data yet
    if (v !== '') e.source.toast('Type into the WK column — day cells are not tracked here');
    e.range.setValue('');
    return;
  }
  var week = sh.getRange(2, col).getValue();                  // WK column
  var weekIso = '';
  try {
    weekIso = Utilities.formatDate(new Date(week),
                                   e.source.getSpreadsheetTimeZone(),
                                   'yyyy-MM-dd');
  } catch (err) { /* no date header — fall through to restore */ }
  if (weekIso && (kind === 'mm' || kind === 'mg')) {
    var key = manager + '|' + weekIso + '|' + slot;
    _upsert(cl, 'J', key, [key, manager, weekIso, String(slot), v], 5);
    e.source.toast(v === '' ? 'Cleared' : (v + ' saved'));
  } else if (v !== '' && (kind === 'm' || kind === 'g')) {
    e.source.toast('This row is automated — the stamper refreshes it');
  }
  e.range.setFormula(_campValueFormula(colL, slot));
}
