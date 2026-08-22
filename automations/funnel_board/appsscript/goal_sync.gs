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

function onEdit(e) {
  var sh = e.range.getSheet();
  if (sh.getName() !== 'Focus Report') return;
  if (e.range.getColumn() !== 2 || e.range.getNumRows() !== 1 ||
      e.range.getNumColumns() !== 1) return;
  var row = e.range.getRow();
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
