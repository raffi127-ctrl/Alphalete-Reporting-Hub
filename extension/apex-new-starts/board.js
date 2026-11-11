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
                 'Blue Ink', 'Headshot Photo', 'UID Request', 'OV BG Status',
                 'Owner Submit', 'Added to APEX'];
  // What each step is CALLED on screen. The key is the sheet's column, which
  // every tick is looked up by; the label is what a person reads. Spelled out,
  // never abbreviated (Megan, 2026-11-09). Same wording as the printed sheet,
  // so the panel and the paper in the leader's hand say the same thing.
  const LABEL = {'UID Request': 'UID Requested', 'Added to APEX': 'Added to Apex'};
  const label = s => LABEL[s] || s;
  const UNASSIGNED = 'No classroom yet';
  // Our own last step, after the office has signed off. Named here so the
  // chart can single it out; it is the sheet's column, not the label.
  const APEX_STEP = 'Added to APEX';
  // WHY SOMEBODY CAME OFF THE BOARD (Megan, 2026-11-11: "when it's clicked we
  // make them have a reason why" -- Terminated / Failed BG / No Show / Left
  // Classroom). Four buttons, not a text box: four words everybody spells the
  // same beat fifty spellings of "quit" that nothing can count later. Kept in
  // step with icd_onboarding.board.REMOVAL_REASONS.
  const REASONS = ['Terminated', 'Failed BG', 'No Show',
                   'Did not show to day 1 Classroom', 'Left Classroom'];
  const WHY = 'Removed Because';

  // Exactly how Apex's own dropdown spells them, so what the panel saves is
  // what gets typed. Blank is a real choice and the default: nothing guesses a
  // gender, because the value lands on somebody's payroll record.
  const GENDERS = [{value: '', label: '— gender —'},
                   {value: 'Female', label: 'Female'},
                   {value: 'Male', label: 'Male'}];

  // WHAT A FILLED CELL SHOWS. A date or a TRUE is just "done", so it becomes a
  // tick; anything else is a word that matters (BG Status says Passed / Sent /
  // Taken - Pending) and is shown as written. The chart and the printed sheet
  // share this, so paper and screen never disagree about a cell.
  const cell = v => {
    const t = String(v == null ? '' : v).trim();
    if (!t) return '';
    const dated = t.length === 10 && t[2] === '/' && t[5] === '/';
    return (dated || t.toUpperCase() === 'TRUE') ? '\u2713' : t;
  };

  // BG STATUS IS A CODE AND A COLOUR (Megan, 2026-11-11: "P=Pending - column
  // is yellow / S=Sent - ... let's make it blue / R=in review should be orange
  // / PA=Passed - column is green / F=failed dark red / NA=not avail -should
  // be light red"). The column is one
  // cell wide, so the word does not fit -- the full status is on hover.
  //
  // The keys are the Sterling vocabulary exactly as bg_check_sync.parse writes
  // it into the sheet. Review and Complete are real statuses on the way
  // through, so they get their own letter and the in-progress yellow -- and
  // COMPLETE IS NOT A PASS: it is the plain "is complete" email with no score,
  // and calling it a pass is the thing Raf said must never happen.
  // BOTH background-check columns read the same way: Sterling's answer and
  // OwnerVille's answer, coloured identically so the eye can compare them
  // (Megan, 2026-11-11: "color code that column like the other BG status
  // column"). They disagree while OwnerVille catches up, and seeing that is
  // the point of having two columns.
  const BG_STEPS = ['BG Status', 'OV BG Status'];
  const BG = {
    'sent':            {code: 'S',  cls: 'bg-sent', name: 'Sent',
                        means: 'The check has gone out. They have not taken it yet.'},
    'taken - pending': {code: 'P',  cls: 'bg-pend', name: 'Taken - Pending',
                        means: 'They have taken it. The result is not back yet.'},
    'review':          {code: 'R',  cls: 'bg-rev',  name: 'Review',
                        means: 'The result is back and is being looked at. No verdict yet.'},
    'complete':        {code: 'C',  cls: 'bg-pend', name: 'Complete',
                        means: 'The check finished, but no pass or fail came with it. '
                             + 'This is NOT a pass \u2014 do not treat it as one.'},
    'passed':          {code: 'PA', cls: 'bg-pass', name: 'Passed',
                        means: 'Came back clean. Onboarding carries on.'},
    'failed':          {code: 'F',  cls: 'bg-fail', name: 'Failed', stop: true,
                        means: 'Came back failed. They do not continue.'},
    'unperformable':   {code: 'NA', cls: 'bg-na',   name: 'Unperformable', stop: true,
                        means: 'The check could not be run at all.'},
  };

  // The whole key, for hovering the column heading itself.
  function bgKey(st) {
    const what = st === 'OV BG Status'
      ? 'What OwnerVille says about the background check. It follows Sterling, '
        + 'just later -- and it is what un-greys the Owner Submit button.'
      : 'What Sterling says. This one is the truth: onboarding carries on '
        + 'from its Passed.';
    return '<b>' + esc(label(st)) + '</b>' + esc(what) + '<i>' +
      Object.keys(BG).map(k => esc(BG[k].code + ' = ' + BG[k].name))
            .join('  ·  ') +
      '</i>';
  }

  // OUR OWN TOOLTIP, not the browser's. A native title waits about a second
  // before it shows and often never shows at all, so the two-letter codes
  // stayed unexplained in practice. This one appears the moment the pointer
  // lands on the cell.
  let tipEl = null;
  function tipFor(root) {
    if (!tipEl) {
      tipEl = document.createElement('div');
      tipEl.className = 'bd-tip';
      tipEl.hidden = true;
      document.body.appendChild(tipEl);
    }
    const show = el => {
      tipEl.innerHTML = el.getAttribute('data-tip');
      tipEl.hidden = false;
      const r = el.getBoundingClientRect(), t = tipEl.getBoundingClientRect();
      // Above the cell, or below it when there is no room up there.
      let top = r.top - t.height - 8;
      if (top < 4) top = r.bottom + 8;
      let left = r.left + r.width / 2 - t.width / 2;
      left = Math.max(6, Math.min(left, window.innerWidth - t.width - 6));
      tipEl.style.top = top + 'px';
      tipEl.style.left = left + 'px';
    };
    root.querySelectorAll('[data-tip]').forEach(el => {
      el.onmouseenter = () => show(el);
      el.onmouseleave = () => { tipEl.hidden = true; };
    });
  }

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

  // THE CHART. Megan, 2026-11-11: "The extension should show me the OBCL like
  // Raf's ... We want a chart that we can have a Week of drop down to select so
  // we can see all names." So the panel IS the board: a row per person, a
  // column per step, the whole week on one screen -- not a stack of cards you
  // scroll through, and not something you have to print to see as a grid.
  //
  // Classroom and Gender are columns like any other, except a person fills
  // them: typed and picked straight in the chart, saved on change. Rows are
  // ordered by classroom (same grouping as the printout) so a room reads as a
  // block even though every name is on the one chart.
  function render(root) {
    const c = counts();
    const live = state.people.filter(p => !isOff(p));
    const gone = state.showOff ? state.people.filter(isOff) : [];
    const shown = live.concat(gone);
    const weekPicker = '<select id="bd-week">' + state.weeks.map(w =>
      '<option' + (w === state.week ? ' selected' : '') + '>' + esc(w) + '</option>'
    ).join('') + '</select>';

    let html = '<div class="bd-top">' +
      '<label class="bd-wk">Week of ' + weekPicker + '</label>' +
      '<div class="bd-sum">' + c.live + ' on the board · ' + c.outstanding +
      ' still to do · ' + c.done + ' finished</div>' +
      (c.off ? '<label class="bd-showoff"><input type="checkbox" id="bd-off"' +
               (state.showOff ? ' checked' : '') + '> show ' + c.off +
               ' removed</label>' : '') +
      '</div>';

    if (!shown.length) {
      html += '<p class="bd-none">Nobody on the board for that week yet.</p>';
    } else {
      // Step headings stand on end so all nine fit beside the names without
      // being shortened -- the words stay the words (Megan, 2026-11-09:
      // spelled out, never abbreviated), and they match the printed sheet.
      html += '<div class="bd-wrap"><table class="bd-grid"><thead><tr>' +
        // Numbered down the left, like Raf's OBCL. The number is the
        // POSITION on this chart, not anything stored -- it is there so two
        // people on the phone can say "number 7" and mean the same row.
        '<th class="h-no">#</th>' +
        '<th class="h-nm">Name</th>' +
        '<th class="h-cls">Classroom</th>' +
        '<th class="h-loc">Location</th>' +
        '<th class="h-gen">Gender</th>' +
        STEPS.map(s => '<th class="h-st"' +
          (BG_STEPS.indexOf(s) >= 0 ? ' data-tip="' + esc(bgKey(s)) + '"' : '') +
          '><span>' + esc(label(s)) + '</span></th>').join('') +
        // Labelled like the rest: an unlabelled column is one every ICD has
        // to click to find out what it does (Megan, 2026-11-11: "what is the
        // last unlabeled column?" / "let's call it 'Remove from onboarding'").
        '<th class="h-st h-off" title="Remove from onboarding">' +
        '<span>Remove from onboarding</span></th>' +
        '</tr></thead><tbody>';

      const rowFor = (p, no) => {
          let out = '';
          const left = remaining(p), b = band(p), name = who(p);
          // OWNER SUBMITTED -> THE WHOLE LINE GOES GREEN (Megan, 2026-11-11:
          // "once owner submitted their whole line should go green"). Owner
          // Submit is the attestation that every check passed, so the line is
          // settled at a glance -- it does not wait for Added to Apex, which
          // is our own step afterwards, not the office's.
          // A FAILED CHECK NEVER READS AS A GOOD LINE. Owner Submit is an
          // attestation that the checks passed, so a row carrying Failed or
          // Unperformable is not green however that box came to be ticked --
          // it is a stop, and it has to look like one. Without this, a
          // background check that came back Failed sits inside a green "all
          // good" line, which is the one way this board could do real harm.
          const stopped = BG_STEPS.some(st => {
            const g = BG[String(p[st] || '').trim().toLowerCase()];
            return !!g && g.stop;
          });
          const sub = !stopped && !!String(p['Owner Submit'] || '').trim();
          out += '<tr class="b-' + b + (sub ? ' b-sub' : '') +
            (stopped ? ' b-stop' : '') + (isOff(p) ? ' b-gone' : '') +
            '" data-who="' + esc(name) + '">' +
            // Numbered: the week's register runs 1..n, and each removal
            // group counts from 1 again (Megan, 2026-11-11: "in the removals-
            // they should also be numbered"). Restarting per group is what
            // makes the heading's own count readable -- "No Show (2)" with a
            // 1 and a 2 under it, rather than a 18 and a 19 that mean nothing.
            '<td class="no">' + (no == null ? '' : no) + '</td>' +
            '<td class="nm" title="' + esc(name) + '">' + esc(name) +
            // The WORD as well as the colour -- a stripe nobody can name is
            // not a status. Same wording as the printed sheet: "done" when
            // there is nothing left, otherwise how far through they are.
            (isOff(p) ? '' : '<span class="cnt">' + (b === 'done' ? 'done'
              : (STEPS.length - left.length) + '/' + STEPS.length) + '</span>') +
            '</td>' +
            (isOff(p)
              // Classroom, Location and Gender are things you fill in for
              // somebody who is coming. For somebody who is not, that space
              // is where the answer belongs: when they came off, and why.
              ? '<td class="gonewhy" colspan="3">Removed ' +
                esc(String(p['Terminated'] || '').trim()) + ' \u00b7 <b>' +
                esc(String(p[WHY] || '').trim() || 'no reason recorded') +
                '</b></td>'
              : '<td class="cls"><input class="bd-cls" data-who="' + esc(name) +
            '" placeholder="—" value="' + esc(p['Classroom'] || '') + '"></td>' +
            // Where they are working from. Typed, like the classroom:
            // nothing we read holds an office's locations (Megan, 2026-11-11).
            '<td class="loc"><input class="bd-loc" data-who="' + esc(name) +
            '" placeholder="—" value="' + esc(p['Location'] || '') + '"></td>' +
            '<td class="gen"><select class="bd-gen" data-who="' + esc(name) + '">' +
            GENDERS.map(x => '<option value="' + esc(x.value) + '"' +
              (String(p['Gender'] || '').trim() === x.value ? ' selected' : '') +
              '>' + esc(x.label) + '</option>').join('') + '</select></td>') +
            STEPS.map(st => {
              const raw = String(p[st] == null ? '' : p[st]).trim();
              let txt = cell(raw);
              let k = txt === '✓' ? 'on' : (txt ? 'on val' : '');
              // HOVERING A CODE SAYS WHAT IT MEANS (Megan, 2026-11-11: "when I
              // hover over a BG status it should say what it means"). Two
              // letters are only readable to somebody who already knows the
              // list, and the list is the thing a new ICD does not have.
              let tip = label(st) + (raw ? ': ' + raw : ' \u2014 not yet');
              if (BG_STEPS.indexOf(st) >= 0) {
                const g = raw ? BG[raw.toLowerCase()] : null;
                if (g) {
                  txt = g.code; k = 'bg ' + g.cls;
                  tip = '<b>' + esc(g.code) + ' = ' + esc(g.name) +
                        '</b>' + esc(g.means);
                } else if (raw) {
                  // An unknown status keeps its own words and gets no colour.
                  // Guessing which band a status nobody has seen belongs to is
                  // how a Failed check ends up looking like progress.
                  txt = raw; k = 'bg bg-unknown';
                  tip = '<b>' + esc(raw) + '</b>Not a status we recognise ' +
                        '\u2014 shown exactly as the sheet has it.';
                } else {
                  tip = '<b>' + esc(label(st)) + ' \u2014 blank</b>' +
                    (st === 'OV BG Status'
                      ? 'OwnerVille has not relayed a result yet. It '
                        + 'follows Sterling, just later.'
                      : 'Nothing has been sent yet.');
                }
              }
              // THE ONE THING LEFT ON A GREEN LINE (Megan, 2026-11-11: "when
              // the whole line is green because they were ownersubmitted then
              // the apex column should still be yellow if not done and go
              // green when done"). Owner Submit is the office's last step;
              // Added to Apex is OURS, afterwards. Greening the whole line
              // would hide it, so it stands out amber until it is in.
              if (sub && !raw && st === APEX_STEP) k = 'todo';
              // A BG cell uses OUR tooltip (data-tip); every other cell
              // keeps the browser's plain title.
              if (BG_STEPS.indexOf(st) >= 0) {
                return '<td class="' + k + '" data-tip="' + esc(tip) +
                       '">' + esc(txt) + '</td>';
              }
              return '<td class="' + k + '" title="' + esc(tip) + '">' +
                     esc(txt) + '</td>';
            }).join('') +
            '<td class="off"><button class="' +
            (isOff(p) ? 'bd-back' : 'bd-ask') + '" data-who="' + esc(name) +
            '" title="' + (isOff(p)
              ? 'Put ' + esc(name) + ' back on onboarding'
              : 'Remove ' + esc(name) + ' from onboarding') +
            '">' + (isOff(p) ? '↩' : '×') + '</button></td>' +
            '</tr>';
        // THE REASON PICKER, under the person it is about. Hidden until the
        // remove button is pressed. Four buttons and a way out -- no typing,
        // nothing to spell, and the name is in the question so nobody removes
        // the wrong person from a row of near-identical buttons.
        if (!isOff(p)) {
          out += '<tr class="whyrow" data-for="' + esc(name) + '" hidden>' +
            '<td colspan="' + (STEPS.length + 6) + '">' +
            '<span class="whyq">Remove <b>' + esc(name) +
            '</b> from onboarding \u2014 why?</span>' +
            '<span class="whypick">' +
            REASONS.map(r => '<button class="bd-why" data-who="' + esc(name) +
              '" data-why="' + esc(r) + '">' + esc(r) + '</button>').join('') +
            // OTHER, for the reason nobody thought of (Megan, 2026-11-11).
            // Last, after the five that cover most weeks, so it is the way
            // out rather than the easy first click -- a typed reason is one
            // nothing can count later.
            '<button class="bd-other" data-who="' + esc(name) +
            '">Other\u2026</button>' +
            '</span>' +
            '<span class="whytype" hidden>' +
            '<input class="bd-whytext" data-who="' + esc(name) +
            '" placeholder="Why are they coming off?" maxlength="60">' +
            '<button class="bd-whysave" data-who="' + esc(name) + '">Save</button>' +
            '</span>' +
            '<button class="bd-nvm" data-who="' + esc(name) + '">Cancel</button>' +
            '</td></tr>';
        }
        return out;
      };

      // Live first, grouped the way they print. Anyone removed goes at the
      // BOTTOM behind their own heading (Megan, 2026-11-11: "in the 'show
      // terminiated' it should populate them at the bottom and have a reason
      // why") -- they are not part of the week's work any more, and mixed in
      // among it they just make the register look longer than it is.
      let n = 0;
      grouped(live).forEach(g => { g.people.forEach(p => { html += rowFor(p, ++n); }); });
      // Removed people GROUPED BY REASON (Megan, 2026-11-11: "same reasons
      // should be grouped together"). Four No Shows under one No Show heading
      // is a fact about the week; the same four scattered through a list is
      // something you have to count by hand. Reason order is the pick list's,
      // so the headings do not shuffle about week to week, and anything with
      // no reason on it sits last where it is obvious.
      if (gone.length) {
        const byWhy = {};
        gone.forEach(p => {
          const w = String(p[WHY] || '').trim() || 'No reason recorded';
          (byWhy[w] = byWhy[w] || []).push(p);
        });
        const order = REASONS.filter(r => byWhy[r])
          .concat(Object.keys(byWhy).filter(w => REASONS.indexOf(w) < 0).sort());
        order.forEach(w => {
          html += '<tr class="sep sep-off"><td colspan="' + (STEPS.length + 6) +
            '">Removed \u00b7 ' + esc(w) + ' (' + byWhy[w].length + ')</td></tr>';
          let m = 0;
          byWhy[w].sort((a, z) => who(a).localeCompare(who(z)))
                  .forEach(p => { html += rowFor(p, ++m); });
        });
      }
      html += '</tbody></table></div>';
    }

    // Print ONE classroom at a time (Megan, 2026-11-09: "a print option where
    // I can just pick a classroom to print - one at a time if I want"). The
    // leader running Tuesday AM wants Tuesday AM, not the whole week's stack
    // with theirs somewhere in it. "All classrooms" is still there for the
    // ICD who prints the lot on a Sunday night.
    const rooms = grouped(live).map(g => g.classroom);
    html += '<div class="bd-print"><select id="bd-which">' +
      '<option value="">All classrooms</option>' +
      rooms.map(r => '<option' + (r === state.printRoom ? ' selected' : '') +
                     ' value="' + esc(r) + '">' + esc(r) + '</option>').join('') +
      '</select><button id="bd-print" class="bd-primary">Print</button></div>';
    root.innerHTML = html;
    wire(root);
    tipFor(root);
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
    // Remove is TWO steps on purpose: press x, then say why. It is a small
    // button in a column of small buttons, and a mis-click would take somebody
    // off the register the classroom leader prints. The second press is both
    // the confirmation and the reason, so it is one extra click, not two.
    const shut = () => root.querySelectorAll('.whyrow')
      .forEach(r => { r.hidden = true; });
    root.querySelectorAll('.bd-ask').forEach(b => {
      b.onclick = () => {
        const open = root.querySelector('.whyrow[data-for="' +
          (b.dataset.who || '').replace(/"/g, '\\"') + '"]');
        const was = open && !open.hidden;
        shut();                       // only ever one question on screen
        if (open) open.hidden = was;
      };
    });
    const mark = async (who, action, reason) => {
      await ask('board_mark', {office: state.office, week: state.week,
                               names: [who], action: action, reason: reason || ''});
      await load(state.office, state.week);
      render(root);
    };
    root.querySelectorAll('.bd-nvm').forEach(b => { b.onclick = shut; });
    // "Other" swaps the pick list for a box. The question stays on screen, so
    // it is still obvious who is being removed while they type.
    root.querySelectorAll('.bd-other').forEach(b => {
      b.onclick = () => {
        const row = b.closest('tr');
        row.querySelector('.whypick').hidden = true;
        const box = row.querySelector('.whytype');
        box.hidden = false;
        box.querySelector('.bd-whytext').focus();
      };
    });
    const typed = async i => {
      const why = i.value.trim();
      // A blank "Other" is not a reason. Saying nothing would record a
      // removal nobody can explain later, which is the whole point of asking.
      if (!why) { i.focus(); return; }
      i.disabled = true;
      await mark(i.dataset.who, 'terminate', why);
    };
    root.querySelectorAll('.bd-whytext').forEach(i => {
      i.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); typed(i); } };
    });
    root.querySelectorAll('.bd-whysave').forEach(b => {
      b.onclick = () => typed(b.closest('tr').querySelector('.bd-whytext'));
    });
    root.querySelectorAll('.bd-why').forEach(b => {
      b.onclick = async () => {
        b.disabled = true;
        await mark(b.dataset.who, 'terminate', b.dataset.why);
      };
    });
    root.querySelectorAll('.bd-back').forEach(b => {
      // Putting somebody back asks nothing: it undoes a removal, and the
      // reason is cleared with it.
      b.onclick = async () => { b.disabled = true; await mark(b.dataset.who, 'restore'); };
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
    root.querySelectorAll('.bd-loc').forEach(i => {
      i.onchange = async () => {
        const a = {}; a[i.dataset.who] = i.value.trim();
        await ask('board_location', {office: state.office, week: state.week,
                                     assignments: a});
        await load(state.office, state.week);
        render(root);
      };
    });
    root.querySelectorAll('.bd-gen').forEach(i => {
      i.onchange = async () => {
        const a = {}; a[i.dataset.who] = i.value;
        await ask('board_gender', {office: state.office, week: state.week,
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
                      BG, REASONS,
                      printSheets};
})();
