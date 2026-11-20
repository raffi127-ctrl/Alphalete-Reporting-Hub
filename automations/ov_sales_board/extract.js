/* Raw data for our own copy of OwnerVille's CEO Dashboard > Sales Board (Raf, 2026-11-20).

   Runs INSIDE OwnerVille's CEO Dashboard frame (index.cfm?p=9197), where OwnerVille's own
   knockReport.js / salesBoard.js are loaded. It calls THEIR functions so every count matches the
   original board exactly:
     knocks, talk-tos   KnockReport.load + KnockReport.dailyBoard (last status per address)
     INT/DTV/NL/Cx      callApi('getSalesBoard')
     teams, roles       callApi('getTeams')
     start/term/email   callApi('getSalesBoardPeople', POST)
   Nothing is computed here beyond per-rep-per-day counts; the artifact applies the sheet's formulas.

   Usage (page.evaluate or Chrome): (EXTRACT)(frameWindow, { officeId: '11280', weeks: 13 })
   Returns a JSON-able object (schema v1, see build at the bottom). */
async function extractSalesBoard(w, opts) {
    opts = opts || {};
    var oid = String(opts.officeId || '11280');
    var nWeeks = opts.weeks || 13;
    function pad(n) { return (n < 10 ? '0' : '') + n; }
    function isoOf(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
    function parseIso(s) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(s || '')); return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null; }
    function addIso(iso, n) { var d = parseIso(iso); d.setDate(d.getDate() + n); return isoOf(d); }
    var now = new Date(), t = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    var thisMon = addIso(isoOf(t), -((t.getDay() + 6) % 7));
    var firstMon = addIso(thisMon, -7 * (nWeeks - 1));      // oldest week the picker offers
    var knockFrom = addIso(firstMon, -14);                   // its last + prior week
    var salesFrom = addIso(firstMon, -42);                   // its six "recent weeks"
    var end = addIso(thisMon, 7);                            // exclusive
    var KR = w.KnockReport;
    // OwnerVille's server drops calls when the dashboard is busy ("Failed to fetch"); try each call 3 times.
    function retry(f) {
        return f().catch(function () { return new Promise(function (r) { setTimeout(r, 3000); }).then(f); })
                  .catch(function () { return new Promise(function (r) { setTimeout(r, 8000); }).then(f); });
    }
    function api(m, p, h) { return retry(function () { return w.callApi(m, p, h); }); }
    var errors = [];
    var ids = (w.RecruitingPipeline && w.RecruitingPipeline.linkedIds) ? await w.RecruitingPipeline.linkedIds(oid) : [oid];

    // Knocks: 3-week chunks (63 days in one call timed out for 11280, per OwnerVille's own note).
    var clients = [], clientIdx = {}, knocks = [], names = {};
    for (var from = knockFrom; from < end; from = addIso(from, 21)) {
        var to = addIso(from, 21) < end ? addIso(from, 21) : end;
        try {
            var data = await retry(function () { return KR.load(oid, from, to); });
            (data.errors || []).forEach(function (e) { errors.push('Knock report: ' + e); });
            KR.clientsIn(data, from, to).forEach(function (c) {
                if (clientIdx[c.name] == null) { clientIdx[c.name] = clients.length; clients.push(c.name); }
                for (var day = from; day < to; day = addIso(day, 1)) {
                    KR.dailyBoard(data, day, c.id).reps.forEach(function (r) {
                        if (r.name && !names[r.personFK]) names[r.personFK] = r.name;
                        if (r.knocks || r.talk) knocks.push([String(r.personFK), day, clientIdx[c.name], r.knocks || 0, r.talk || 0]);
                    });
                }
            });
        } catch (e) { errors.push('Knocks ' + from + ' did not load: ' + (e && e.message || e)); }
    }

    // AT&T sales: ~7-week chunks.
    var sales = [], saleNames = {};
    for (var id of ids) {
        for (var sf = salesFrom; sf < end; sf = addIso(sf, 49)) {
            var st = addIso(sf, 48) < addIso(end, -1) ? addIso(sf, 48) : addIso(end, -1);
            try {
                var env = await api('getSalesBoard', { officeId: id, dateFrom: sf, dateTo: st });
                ((env.meta && env.meta.errors) || []).forEach(function (e) { errors.push(e); });
                (env.cells || []).forEach(function (c) {
                    sales.push([String(c.pk), c.day, Number(c.int) || 0, Number(c.dtv) || 0, Number(c.nl) || 0, Number(c.cx) || 0]);
                });
                Object.keys(env.names || {}).forEach(function (pk) { saleNames[pk] = env.names[pk]; });
            } catch (e) { errors.push('Sales ' + sf + ' did not load: ' + (e && e.message || e)); }
        }
    }

    // Teams (only what the board reads).
    var teams = [];
    for (var tid of ids) {
        try {
            var te = await api('getTeams', { officeId: tid });
            (te.data || []).forEach(function (x) {
                teams.push({
                    name: String(x.name || '').trim() || 'Team',
                    leader: x.leader && x.leader.id ? { id: String(x.leader.id), role: x.leaderRole || 'Leader' } : null,
                    members: (x.members || []).map(function (m) { return { id: String(m.id), role: m.role || '' }; })
                });
            });
        } catch (e) { errors.push('Teams did not load: ' + (e && e.message || e)); }
    }

    // People, for every rep that shows up anywhere in the window.
    var pks = {};
    knocks.forEach(function (k) { pks[k[0]] = 1; });
    sales.forEach(function (s) { if (s[1] >= knockFrom) pks[s[0]] = 1; });
    var people = {}, list = Object.keys(pks);
    for (var pid of ids) {
        for (var i = 0; i < list.length; i += 150) {
            try {
                var pe = await api('getSalesBoardPeople', { officeId: pid, personIds: list.slice(i, i + 150).join(',') }, 'POST');
                (pe.people || []).forEach(function (p) {
                    people[String(p.pk)] = { name: p.name || '', start: p.startDate || '', term: p.retiredDate || '', email: p.email || '' };
                });
            } catch (e) { errors.push('Rep profiles did not load: ' + (e && e.message || e)); }
        }
    }

    return {
        v: 1, generatedAt: new Date().toISOString(), officeId: oid, officeLabel: opts.officeLabel || '',
        thisMon: thisMon, firstMon: firstMon, knockFrom: knockFrom, salesFrom: salesFrom,
        clients: clients,
        knocks: knocks,          // [pk, day, clientIdx, knocks, talkTos]
        sales: sales,            // [pk, day, int, dtv, nl, cx]
        names: names, saleNames: saleNames, people: people, teams: teams, errors: errors
    };
}
