// Reading the week off the clipboard.
//
// The Hub's "Get this week's setup" puts the bookmarklet's setup text there:
// one long line of JavaScript with the week's people embedded in it. The
// extension already HAS the code (engine.js), so it wants only the facts out
// of that text -- the week, the build stamp, the notice, the start date and
// the people.
//
// It is parsed, never run. Running clipboard text as code is what the
// bookmarklet did, and it is why a stale copy could quietly run last month's
// engine against this month's list.
//
// A plain JSON payload is accepted too, so the Hub can switch to one later
// without the extension needing a change.
(function () {
  'use strict';

  // A balanced JSON value starting at i (array, object, string, null, number).
  function jsonAt(text, i) {
    let depth = 0, inStr = false, esc = false;
    const start = i;
    for (; i < text.length; i++) {
      const c = text[i];
      if (inStr) {
        if (esc) { esc = false; continue; }
        if (c === '\\') { esc = true; continue; }
        if (c === '"') inStr = false;
        continue;
      }
      if (c === '"') { inStr = true; continue; }
      if (c === '[' || c === '{') depth++;
      else if (c === ']' || c === '}') { depth--; if (depth === 0) return text.slice(start, i + 1); }
      else if (depth === 0 && (c === ';' || c === ',')) return text.slice(start, i).trim();
    }
    return null;
  }

  // The contents of a single-quoted JS string whose opening quote is at i.
  function sqAt(text, i) {
    let raw = '', esc = false, j = i + 1;
    for (; j < text.length; j++) {
      const c = text[j];
      if (esc) { raw += '\\' + c; esc = false; continue; }
      if (c === '\\') { esc = true; continue; }
      if (c === "'") break;
      raw += c;
    }
    if (j >= text.length) return null;
    try {
      return JSON.parse('"' + raw.replace(/\\'/g, "'").replace(/"/g, '\\"') + '"');
    } catch (e) {
      return raw;
    }
  }

  function after(text, marker) {
    const i = text.indexOf(marker);
    return i < 0 ? -1 : i + marker.length;
  }

  function parse(text) {
    text = String(text || '').trim();
    if (!text) return {ok: false, error: 'Nothing on the clipboard.'};

    // Already JSON? Then it says what it is.
    if (text[0] === '{') {
      try {
        const got = JSON.parse(text);
        if (Array.isArray(got.people) && got.people.length) {
          return {ok: true, week: got.week || '', build: got.build || '',
                  built_at: got.built_at || Date.now(), notice: got.notice || null,
                  start: got.start || '', data: got.people};
        }
      } catch (e) { /* fall through to the setup-text reader */ }
    }

    if (text.indexOf('apexNewStarts.') < 0) {
      return {ok: false,
              error: 'That is not this week\'s setup. On the Hub press ' +
                     '"Get this week\'s setup", then click here again without ' +
                     'copying anything in between.'};
    }

    const di = after(text, 'var D=');
    const raw = di < 0 ? null : jsonAt(text, di);
    let people = null;
    try { people = raw ? JSON.parse(raw) : null; } catch (e) { people = null; }
    if (!Array.isArray(people) || !people.length) {
      return {ok: false,
              error: 'The setup on the clipboard has nobody in it. Press ' +
                     '"Get this week\'s setup" on the Hub again.'};
    }

    const wq = text.indexOf("'apexNewStarts.");
    const week = wq < 0 ? '' : (sqAt(text, wq) || '').replace(/^apexNewStarts\./, '');
    const bi = text.indexOf("var BUILD='");
    const si = text.indexOf("var START='");
    const ni = after(text, 'var NOTICE=');
    const ti = text.match(/BUILT_AT=(\d+)/);

    let notice = null;
    if (ni >= 0) {
      const nraw = jsonAt(text, ni);
      if (nraw && nraw !== 'null') { try { notice = JSON.parse(nraw); } catch (e) { notice = null; } }
    }

    return {
      ok: true,
      week: week,
      build: bi < 0 ? '' : (sqAt(text, bi + 'var BUILD='.length) || ''),
      built_at: ti ? Number(ti[1]) : Date.now(),
      notice: notice,
      start: si < 0 ? '' : (sqAt(text, si + 'var START='.length) || ''),
      data: people
    };
  }

  window.ApexSetup = {parse: parse};
})();
