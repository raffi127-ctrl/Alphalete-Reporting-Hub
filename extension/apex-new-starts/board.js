// The onboarding board, inside the icon.
//
// Megan, 2026-11-08: "a little drop down that happens. We see the progress
// board, the roadmap of onboarding ... and then they're able to terminate from
// there. So click them off, and then we should have a show or hide terminated
// reps for this week. They should be able to pick the week that they are
// seeing." And: "They just don't need to go to that sheet. They just want the
// preview of the board."
//
// Everything here is a view of the office's own Onboarding tab. The relay
// reads and writes it; this never holds the board, so two people looking at
// once see the same thing.
(function () {
  'use strict';

  const ask = (call, extra) => new Promise(r =>
    chrome.runtime.sendMessage({type: 'relay', call, extra}, r));
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c =>
    ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

  // The nine steps, in the order somebody works through them. Kept in step
  // with automations/icd_onboarding/board.py — if they drift, the board shows
  // the wrong thing rather than erroring, so they are listed once here.
  const STEPS = ['Contact Added', 'BG Status', 'Digi Docs', 'Onboarding Quizzes',
                 'Blue Ink', 'Headshot Photo', 'UID Request', 'Owner Submit',
                 'Added to APEX'];
  // What each step is CALLED on screen. The key is the sheet's column, which
  // every tick is looked up by; the label is what a person reads. Spelled out,
  // never abbreviated (Megan, 2026-11-09). Same wording as the printed sheet,
  // so the panel and the paper in the leader's hand say the same thing.
  const LABEL = {'UID Request': 'UID Requested', 'Added to APEX': 'Added to Apex'};
  const label = s => LABEL[s] || s;
  const UNASSIGNED = 'No classroom yet';

  const who = p => ((p['Name'] || '') + ' ' + (p['Last Name'] || '')).trim();
  const isOff = p => !!String(p['Terminated'] || '').trim();
  const remaining = p => STEPS.filter(s => !String(p[s] || '').trim());

  // done / close / behind — the same bands the printout uses, and the word is
  // always there as well as the colour.
  function band(p) {
    const left = remaining(p).length;
    return left === 0 ? 'done' : left <= 2 ? 'close' : 'behind';
  }

  const state = {office: '', week: '', weeks: [], people: [], showOff: false,
                 printRoom: ''};

  async function load(office, week) {
    state.office = office;
    const got = await ask('board_week', {office, week: week || ''});
    if (!got || !got.ok) return got || {ok: false, error: 'No answer from Lucy.'};
    state.week = got.week;
    state.weeks = got.weeks || [];
    state.people = got.people || [];
    return got;
  }

  function counts() {
    const live = state.people.filter(p => !isOff(p));
    return {
      live: live.length,
      off: state.people.length - live.length,
      outstanding: live.reduce((n, p) => n + remaining(p).length, 0),
      done: live.filter(p => !remaining(p).length).length,
    };
  }

  // Grouped the way it prints: a sheet per classroom, no-classroom last.
  // What makes two typed classrooms the SAME ROOM. Free typing means one room
  // is typed several ways in a week — "Tuesday AM", "tuesday am",
  // " Tuesday  AM " — and grouping on the raw string prints a separate sheet
  // for each, every one holding part of the register. Case and spacing are
  // ignored for grouping; the spelling is NOT changed, because the ICD's own
  // wording is the heading the leader recognises. Same rule as
  // icd_onboarding.board.room_key — if one changes, change both.
  const roomKey = s => String(s == null ? '' : s).trim().replace(/\s+/g, ' ').toLowerCase();

  function grouped(people) {
    const by = {}, shown = {};
    people.forEach(p => {
      const c = String(p['Classroom'] || '').trim() || UNASSIGNED;
      const k = roomKey(c);
      if (!(k in shown)) shown[k] = c;
      (by[k] = by[k] || []).push(p);
    });
    const nokey = roomKey(UNASSIGNED);
    const named = Object.keys(by).filter(k => k !== nokey)
      .sort((a, b) => shown[a].toLowerCase().localeCompare(shown[b].toLowerCase()));
    if (by[nokey]) named.push(nokey);
    return named.map(c => ({
      classroom: shown[c],
      people: by[c].sort((a, b) => remaining(b).length - remaining(a).length
                                   || who(a).localeCompare(who(b))),
    }));
  }

  function render(root) {
    const c = counts();
    const shown = state.showOff ? state.people : state.people.filter(p => !isOff(p));
    const weekPicker = '<select id="bd-week">' + state.weeks.map(w =>
      '<option' + (w === state.week ? ' selected' : '') + '>' + esc(w) + '</option>'
    ).join('') + '</select>';

    let html = '<div class="bd-top">' +
      '<label>Week of ' + weekPicker + '</label>' +
      '<div class="bd-sum">' + c.live + ' on the board · ' + c.outstanding +
      ' still to do · ' + c.done + ' finished</div>' +
      (c.off ? '<label class="bd-showoff"><input type="checkbox" id="bd-off"' +
               (state.showOff ? ' checked' : '') + '> show ' + c.off +
               ' marked off</label>' : '') +
      '</div>';

    if (!shown.length) {
      html += '<p class="bd-none">Nobody on the board for that week yet.</p>';
    }

    grouped(shown).forEach(g => {
      html += '<div class="bd-class"><h3>' + esc(g.classroom) + '</h3>';
      g.people.forEach(p => {
        const left = remaining(p), b = band(p), name = who(p);
        html += '<div class="bd-row bd-' + b + (isOff(p) ? ' bd-gone' : '') + '">' +
          '<div class="bd-nm">' + esc(name) +
          '<span class="bd-tag">' + (isOff(p) ? 'marked off' : b) + '</span>' +
          '<span class="bd-cnt">' + (STEPS.length - left.length) + '/' + STEPS.length +
          '</span></div>' +
          '<div class="bd-steps">' + STEPS.map(s =>
            '<span class="bd-step' + (String(p[s] || '').trim() ? ' bd-ok' : '') +
            '" title="' + esc(label(s)) + '">' + esc(label(s)) + '</span>').join('') + '</div>' +
          '<div class="bd-acts">' +
          '<input class="bd-cls" data-who="' + esc(name) + '" placeholder="classroom" value="' +
          esc(p['Classroom'] || '') + '">' +
          '<button class="bd-mark" data-who="' + esc(name) + '" data-off="' +
          (isOff(p) ? '1' : '0') + '">' +
          (isOff(p) ? 'Put back' : 'Mark off') + '</button>' +
          '</div></div>';
      });
      html += '</div>';
    });

    // Print ONE classroom at a time (Megan, 2026-11-09: "a print option where
    // I can just pick a classroom to print - one at a time if I want"). The
    // leader running Tuesday AM wants Tuesday AM, not the whole week's stack
    // with theirs somewhere in it. "All classrooms" is still there for the
    // ICD who prints the lot on a Sunday night.
    const rooms = grouped(shown).map(g => g.classroom);
    html += '<div class="bd-print"><select id="bd-which">' +
      '<option value="">All classrooms</option>' +
      rooms.map(r => '<option' + (r === state.printRoom ? ' selected' : '') +
                     ' value="' + esc(r) + '">' + esc(r) + '</option>').join('') +
      '</select><button id="bd-print" class="bd-primary">Print</button></div>';
    root.innerHTML = html;
    wire(root);
  }

  function wire(root) {
    const el = id => root.querySelector('#' + id);
    if (el('bd-week')) el('bd-week').onchange = async e => {
      await load(state.office, e.target.value);
      render(root);
    };
    if (el('bd-off')) el('bd-off').onchange = e => {
      state.showOff = e.target.checked;
      render(root);
    };
    root.querySelectorAll('.bd-mark').forEach(b => {
      b.onclick = async () => {
        b.disabled = true;
        await ask('board_mark', {office: state.office, week: state.week,
                                 names: [b.dataset.who],
                                 action: b.dataset.off === '1' ? 'restore' : 'terminate'});
        await load(state.office, state.week);
        render(root);
      };
    });
    root.querySelectorAll('.bd-cls').forEach(i => {
      i.onchange = async () => {
        const a = {}; a[i.dataset.who] = i.value.trim();
        await ask('board_classroom', {office: state.office, week: state.week,
                                      assignments: a});
        await load(state.office, state.week);
        render(root);
      };
    });
    if (el('bd-which')) el('bd-which').onchange = e => { state.printRoom = e.target.value; };
    if (el('bd-print')) el('bd-print').onclick = () => printSheets(state.printRoom);
  }

  // One printed sheet per classroom, laid out like Raf's OBCL: a row per
  // person, a column per step, ticks shaded and blanks left open for the
  // leader's pen. Mirrors icd_onboarding.board.print_html so paper and screen
  // agree -- if one changes, change both.
  //
  // `room` prints that classroom alone; empty prints them all.
  function printSheets(room) {
    const live = state.people.filter(p => !isOff(p));
    const pages = grouped(live).filter(g => !room || g.classroom === room);
    if (!pages.length) { alert('Nothing to print for that classroom.'); return; }
    const cell = v => {
      const t = String(v || '').trim();
      if (!t) return '';
      const dated = t.length === 10 && t[2] === '/' && t[5] === '/';
      return (dated || t.toUpperCase() === 'TRUE') ? '\u2713' : t;
    };
    let html = '<!doctype html><meta charset="utf-8"><title>Onboarding</title>' +
      '<style>@page{margin:10mm;size:landscape}' +
      'body{font:10pt/1.3 -apple-system,Helvetica,Arial,sans-serif;color:#111}' +
      '.sheet{page-break-after:always}.sheet:last-child{page-break-after:auto}' +
      'h1{font-size:18pt;margin:0 0 2pt}.sub{color:#555;font-size:9.5pt;margin-bottom:9pt}' +
      'table{border-collapse:collapse;width:100%}th,td{border:.8pt solid #999;padding:4pt 5pt}' +
      'thead th{background:#0f5c4d;color:#fff;font-size:8.5pt;text-align:center;vertical-align:bottom}' +
      'thead th.nm{text-align:left;width:22%}' +
      'tbody td{height:20pt;text-align:center;font-size:10pt}' +
      'tbody td.nm{text-align:left;font-weight:600;white-space:nowrap}' +
      'tbody tr:nth-child(even) td{background:#FAFAFA}' +
      'td.on{background:#E6F4EA!important;color:#1e6b34;font-weight:700}' +
      'td.val{font-size:8.5pt}' +
      'td.nm span{font-weight:400;font-size:8pt;text-transform:uppercase;margin-left:5pt}' +
      '.b-done td.nm{border-left:4pt solid #1e6b34}' +
      '.b-close td.nm{border-left:4pt solid #7a5a00}' +
      '.b-behind td.nm{border-left:4pt solid #8a1c13}' +
      '.key{font-size:8.5pt;color:#555;margin-top:8pt}</style>';
    pages.forEach(g => {
      const out = g.people.reduce((n, p) => n + remaining(p).length, 0);
      html += '<div class="sheet"><h1>' + esc(g.classroom) + '</h1>' +
        '<div class="sub">Week of ' + esc(state.week) + ' · ' + g.people.length +
        ' people · ' + (out ? out + ' still to do' : 'everything done') + '</div>' +
        '<table><thead><tr><th class="nm">Name</th>' +
        STEPS.map(c => '<th>' + esc(label(c)) + '</th>').join('') +
        '</tr></thead><tbody>';
      g.people.forEach(p => {
        const b = band(p), left = remaining(p);
        html += '<tr class="b-' + b + '"><td class="nm">' + esc(who(p)) +
          '<span>' + (b === 'done' ? 'done'
                      : (STEPS.length - left.length) + '/' + STEPS.length) +
          '</span></td>' +
          STEPS.map(c => {
            const t = cell(p[c]);
            const k = t === '\u2713' ? 'on' : (t ? 'on val' : '');
            return '<td class="' + k + '">' + esc(t) + '</td>';
          }).join('') + '</tr>';
      });
      html += '</tbody></table><div class="key">A blank cell is one to tick off ' +
        'here.</div></div>';
    });
    const w = window.open('', '_blank');
    w.document.write(html);
    w.document.close();
    w.focus();
    w.print();
  }

  window.LucyBoard = {load, render, state, remaining, band, grouped, counts,
                      printSheets};
})();
