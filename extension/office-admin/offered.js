// Who gets a background check: ApplicantStream calendar -> SECOND INTERVIEWS
// -> "Offer Position?" = Yes (Megan 2026-11-03). Same rules as the Python
// reader automations/office_admin/offered.py, which was proved on Omar's and
// Raf's real calendars 11/03-11/04:
//   * the dropdown is <select id="sOfferPosition" class="offerPosition"> --
//     an id, not a name; only rows that SHOWED have it
//   * columns by HEADER TEXT, rows only under the SECOND INTERVIEWS banner
//   * V2 calendar (p=1511): click the "2nd Interview" tab, one Name column
//   * can't find the section/dropdown = an ERROR, never "nobody offered"
/* exported LucyOffered */
var LucyOffered = (function () {
  'use strict';
  var norm = function (s) { return (s || '').replace(/\s+/g, ' ').trim(); };
  var OFFER_SEL = 'select[id="sOfferPosition"], select.offerPosition, select[name="sOfferPosition"]';
  var BANNER = /^([A-Z0-9 &]*?(INTERVIEWS?|ORIENTATIONS?|TRAINING))\b/;

  function isV2() {
    var t = document.body.innerText || '';
    return /Applicant Interview Calendar/i.test(t) && /2nd Interview/.test(t) && /First Day of Sales/.test(t);
  }

  function isCalendar() {
    var t = document.body.innerText || '';
    return isV2() || /SECOND INTERVIEWS|FIRST INTERVIEWS/.test(t) || /Calendars for \d/.test(t);
  }

  // The office the page is showing: V1 "Office ID: 24153", V2 picker "(#11280 - ...)".
  function officeId() {
    var t = document.body.innerText || '';
    var m = t.match(/Office ID:\s*(\d+)/) || t.match(/\(#(\d+)\s*-/);
    return m ? m[1] : '';
  }

  function readV1() {
    var rows = [], section = '', header = null, sawSection = false;
    var nodes = document.querySelectorAll('tr, td, th, div, span, h1, h2, h3, h4, b, strong');
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      if (n.tagName !== 'TR') {
        if (n.querySelector('tr')) continue;
        var m = norm(n.innerText).match(BANNER);
        if (m && m[1] !== section) {
          section = m[1]; header = null;
          if (section.indexOf('SECOND INTERVIEWS') === 0) sawSection = true;
        }
        continue;
      }
      if (n.querySelector('tr')) continue;
      var texts = Array.prototype.map.call(n.children, function (c) { return norm(c.innerText); });
      var low = texts.map(function (t) { return t.toLowerCase().replace(/[^a-z ]/g, '').trim(); });
      if (low.indexOf('first name') >= 0 && low.indexOf('email') >= 0) {
        if (header) section = '';
        header = {};
        ['first name', 'last name', 'phone', 'email'].forEach(function (k) {
          var j = low.indexOf(k); if (j >= 0) header[k] = j;
        });
        continue;
      }
      var sel = n.querySelector(OFFER_SEL);
      if (!sel || !header) continue;
      var opt = sel.options[sel.selectedIndex];
      var at = function (k) { return (k in header && header[k] < texts.length) ? texts[header[k]] : ''; };
      rows.push({first: at('first name'), last: at('last name'), phone: at('phone'),
                 email: at('email'), offer: opt ? norm(opt.text) : '', section: section});
    }
    if (!sawSection) throw new Error('No "SECOND INTERVIEWS" section on this calendar page.');
    return rows.filter(function (r) { return r.section.indexOf('SECOND INTERVIEWS') === 0; });
  }

  function clickV2Tab() {
    var els = document.querySelectorAll('a, button, li, div, span');
    for (var i = 0; i < els.length; i++) {
      if (/^\s*2nd Interview\b/.test(els[i].innerText || '') && els[i].children.length <= 3) {
        els[i].click(); return true;
      }
    }
    return false;
  }

  function showAllV2() {
    var sel = Array.prototype.find.call(document.querySelectorAll('select'), function (s) {
      return s.offsetParent && (/_length$/.test(s.name || '') ||
        /entries/i.test(((s.closest('label') || {}).innerText) || ''));
    });
    if (!sel) return;
    var best = null;
    Array.prototype.forEach.call(sel.options, function (o) {
      var v = parseInt(o.value, 10);
      if (v === -1 || !best || (parseInt(best.value, 10) !== -1 && v > parseInt(best.value, 10))) best = o;
    });
    if (best) { sel.value = best.value; sel.dispatchEvent(new Event('change', {bubbles: true})); }
  }

  function readV2Table() {
    var tables = Array.prototype.filter.call(document.querySelectorAll('table'), function (t) { return t.offsetParent; });
    for (var i = 0; i < tables.length; i++) {
      var hdr = tables[i].querySelector('thead tr') || tables[i].querySelector('tr');
      if (!hdr) continue;
      var low = Array.prototype.map.call(hdr.children, function (c) {
        return norm(c.innerText).toLowerCase().replace(/[^a-z ]/g, '').trim();
      });
      if (low.indexOf('name') < 0 || low.indexOf('email') < 0) continue;
      var col = {name: low.indexOf('name'), phone: low.indexOf('phone'), email: low.indexOf('email'),
                 show: low.indexOf('show up')};
      var rows = [];
      tables[i].querySelectorAll('tbody tr').forEach(function (tr) {
        var cells = tr.children;
        if (cells.length < 3) return;
        var text = function (j) { return (j >= 0 && j < cells.length) ? norm(cells[j].innerText) : ''; };
        var sels = Array.prototype.slice.call(tr.querySelectorAll('select'));
        var offerSel = sels.find(function (x) {
          return x.id === 'sOfferPosition' || x.name === 'sOfferPosition' || x.classList.contains('offerPosition');
        }) || sels.find(function (x) { return /offer position/i.test(norm((x.closest('td') || {}).innerText)); });
        var opt = offerSel ? offerSel.options[offerSel.selectedIndex] : null;
        var parts = text(col.name).split(' ');
        rows.push({first: parts[0] || '', last: parts.slice(1).join(' '), phone: text(col.phone),
                   email: text(col.email), show: text(col.show), offer: opt ? norm(opt.text) : '',
                   hasOffer: !!offerSel, section: 'SECOND INTERVIEWS'});
      });
      var showed = rows.filter(function (r) { return /show/i.test(r.show) && !/not/i.test(r.show); });
      if (showed.length && !rows.some(function (r) { return r.hasOffer; })) {
        throw new Error('People showed up but no "Offer Position" dropdown was found -- the page changed?');
      }
      return rows;
    }
    throw new Error('No Name/Email table on the 2nd Interview tab.');
  }

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  async function readV2() {
    if (!clickV2Tab()) throw new Error('Could not find the "2nd Interview" tab.');
    await sleep(2500);
    showAllV2();
    await sleep(2000);
    var all = readV2Table();
    // still paged? walk Next
    for (var guard = 0; guard < 40; guard++) {
      var info = norm((document.querySelector('.dataTables_info') || {}).innerText);
      var m = info.match(/Showing\s+([\d,]+)\s+to\s+([\d,]+)\s+of\s+([\d,]+)/i);
      if (!m || +m[2].replace(/,/g, '') >= +m[3].replace(/,/g, '')) break;
      var next = document.querySelector('.paginate_button.next:not(.disabled), a.next:not(.disabled)');
      if (!next) throw new Error('More rows than shown and no Next button.');
      next.click(); await sleep(1500);
      all = all.concat(readV2Table());
    }
    return all;
  }

  // -> [{first_name, last_name, email, phone}] of Offer Position = Yes, once each.
  async function read() {
    var rows = isV2() ? await readV2() : readV1();
    var seen = {}, out = [];
    rows.forEach(function (r) {
      if ((r.offer || '').toLowerCase() !== 'yes' || !r.first) return;
      var phone = (r.phone || '').replace(/\D/g, '').slice(-10);
      var key = r.first.toLowerCase() + '|' + r.last.toLowerCase() + '|' + phone;
      if (seen[key]) return;
      seen[key] = 1;
      out.push({first_name: r.first, last_name: r.last, email: r.email, phone: phone});
    });
    return out;
  }

  return {read: read, isCalendar: isCalendar, isV2: isV2, officeId: officeId};
})();
