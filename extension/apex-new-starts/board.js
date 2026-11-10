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

  const state = {office: '', week: '', weeks: [], people: [], showOff: false};

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
  function grouped(people) {
    const by = {};
    people.forEach(p => {
      const c = String(p['Classroom'] || '').trim() || UNASSIGNED;
      (by[c] = by[c] || []).push(p);
    });
    const named = Object.keys(by).filter(c => c !== UNASSIGNED).sort();
    if (by[UNASSIGNED]) named.push(UNASSIGNED);
    return named.map(c => ({
      classroom: c,
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

    html += '<button id="bd-print" class="bd-primary">Print the sheets</button>';
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
    if (el('bd-print')) el('bd-print').onclick = () => printSheets();
  }

  // One printed sheet per classroom, each outstanding step a box to tick.
  // Mirrors icd_onboarding.board.print_html so paper and screen agree.
  function printSheets() {
    const live = state.people.filter(p => !isOff(p));
    let html = '<!doctype html><meta charset="utf-8"><title>Onboarding</title>' +
      '<style>@page{margin:14mm}body{font:12pt/1.45 -apple-system,Helvetica,Arial,sans-serif}' +
      '.sheet{page-break-after:always}.sheet:last-child{page-break-after:auto}' +
      'h1{font-size:20pt;margin:0 0 2pt}.sub{color:#555;font-size:10pt;margin-bottom:12pt}' +
      '.who{border-left:4pt solid #ccc;padding:4pt 0 4pt 8pt;margin:0 0 12pt;page-break-inside:avoid}' +
      '.b-done{border-left-color:#1e6b34;background:#E6F4EA}' +
      '.b-close{border-left-color:#7a5a00;background:#FFF6DB}' +
      '.b-behind{border-left-color:#8a1c13;background:#FDECEA}' +
      '.nm{font-weight:700;font-size:13pt}.tag{font-size:9pt;font-weight:700;text-transform:uppercase;margin-left:6pt}' +
      'ul{list-style:none;margin:4pt 0 0;padding-left:4pt}li{padding:2.5pt 0}' +
      '.box{display:inline-block;width:11pt;height:11pt;border:1.2pt solid #333;' +
      'margin-right:8pt;vertical-align:-1pt;border-radius:2pt}</style>';
    grouped(live).forEach(g => {
      const out = g.people.reduce((n, p) => n + remaining(p).length, 0);
      html += '<div class="sheet"><h1>' + esc(g.classroom) + '</h1>' +
        '<div class="sub">Week of ' + esc(state.week) + ' · ' +
        (out ? out + ' still to do' : 'everything done') + '</div>';
      g.people.forEach(p => {
        const left = remaining(p);
        html += '<div class="who b-' + band(p) + '"><div class="nm">' + esc(who(p));
        if (!left.length) { html += ' <span class="tag">done</span></div></div>'; return; }
        html += ' <span class="tag">' + band(p) + '</span></div><ul>' +
          left.map(s => '<li><span class="box"></span>' + esc(s) + '</li>').join('') +
          '</ul></div>';
      });
      html += '</div>';
    });
    const w = window.open('', '_blank');
    w.document.write(html);
    w.document.close();
    w.focus();
    w.print();
  }

  window.LucyBoard = {load, render, state, remaining, band, grouped, counts};
})();
