"""ONE-TIME read-only probe (Carlos 2026-09-08): dump an office's saved
SMS/email templates from ApplicantStream — the texts sent to applicants before
the call-list call (e.g. the Await Call text). Default office: Raf (11280).

Strategy: switch to the office, then (1) dump every nav link on the console
whose text/href smells like templates/SMS/email/communication, (2) visit each
distinct p=NN candidate page and capture its text + any textarea/template rows.
Everything goes to the control-sheet tab 'AS Templates Probe' (plain rows).
Writes nothing anywhere else. `lucy rerun as_templates_probe [--office ID]`.
Delete module + config entry once read.
"""
from __future__ import annotations

import argparse
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.recruiting_report import fetch_office as fo
from automations.recruiting_report import fill as _fill
from automations.recruiter_retention.run import _rqst
from automations.shared.tableau_patchright import appstream_direct_session

CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
OUT_TAB = "AS Templates Probe"   # legacy single-office tab, left in place
OUT_TAB_PREFIX = "AS Templates"  # real tab is "AS Templates <office>"
HINT = re.compile(r"templat|sms|text|email|communicat|await|message", re.I)


def _emit(rows, line):
    print(line[:200], flush=True)
    for i in range(0, max(len(line), 1), 45000):
        rows.append([line[i:i + 45000]])


# The first read (Carlos 2026-09-08) only wanted the pre-call texts. The audit
# (Raf 2026-09-26) lints the whole library — a bad link in ANY activated
# template reaches every applicant it fires for — so --all walks every Edit
# link instead. Kept as the default so the original narrow run still works.
WANT_SECTIONS = ["Await Call", "Await Call AI", "1st Left Message",
                 "2nd Left Message", "3rd Left Message", "No Answer",
                 "First Interview Confirmation", "Friendly Reminder 1"]


def _dump_template_bodies(page, rqst, rows, want=None):
    """On the SMS Templates page (p=332), click Edit on each wanted section's
    templates and dump every textarea/text-input the edit view exposes."""
    url = f"https://applicantstream.com/index.cfm?rqst={rqst}&p=332"

    def _reload():
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)

    _reload()
    # map every Edit link to its section heading + template name
    links = page.evaluate(
        """() => {
          const out = [];
          const els = [...document.querySelectorAll('a,button')];
          const heads = [...document.querySelectorAll('b,strong,h1,h2,h3,h4,td,div,span')]
            .filter(e => /:$/.test((e.innerText||'').trim()) &&
                         (e.innerText||'').length < 60);
          els.forEach((a, i) => {
            if ((a.innerText||'').trim() !== 'Edit') return;
            let head = '', name = '';
            let n = a;
            // The template's own row: the nearest parent that shows an
            // on/off state, read up to that state ("Follow Up from Calendar
            // - No Answer 1  Activated Edit ..."). Walking further up hit
            // the whole table and returned the page's FIRST template name
            // for every Edit (11280, 2026-11-15: 31 of 43 bodies came back
            // as "1st Left Message - Call List Template #1").
            for (let hops = 0; hops < 12 && n; hops++) {
              n = n.parentElement;
              if (!n) break;
              const t = (n.innerText||'');
              const st = t.search(/\\b(Not Activated|Activated)\\b/);
              if (st > 0) {
                const lines = t.slice(0, st).split(/\\n/)
                  .map(x => x.trim()).filter(Boolean);
                name = lines.length ? lines[lines.length - 1] : '';
                break;
              }
            }
            let best = '', bestPos = -1;
            const pos = a.getBoundingClientRect().top + window.scrollY;
            heads.forEach(h => {
              const hp = h.getBoundingClientRect().top + window.scrollY;
              if (hp <= pos && hp > bestPos) { bestPos = hp; best = (h.innerText||'').trim(); }
            });
            out.push({i, head: best.replace(/:$/,''), name});
          });
          return out;
        }""")
    _emit(rows, f"=== phase 2: {len(links)} Edit links found ===")
    want = WANT_SECTIONS if want is None else want
    wanted = links if not want else [
        l for l in links
        if any(l["head"].startswith(w) or l["name"].startswith(w) for w in want)]
    for l in wanted:
        _emit(rows, f"opening Edit #{l['i']} — section {l['head']!r} "
                    f"template {l['name']!r}")
        try:
            page.evaluate(
                """(i) => { const es=[...document.querySelectorAll('a,button')]
                     .filter(a=>(a.innerText||'').trim()==='Edit');
                   if (es[0] !== undefined) {
                     const all=[...document.querySelectorAll('a,button')];
                     all[i].click(); } }""", l["i"])
            page.wait_for_timeout(3000)
            payload = page.evaluate(
                """() => ({
                  tas: [...document.querySelectorAll('textarea')]
                        .map(t => (t.value||'').trim()).filter(Boolean),
                  ins: [...document.querySelectorAll("input[type=text]")]
                        .map(t => (t.value||'').trim())
                        .filter(v => v && v.length > 15),
                  frames: []})""")
            for fr in page.frames:
                try:
                    extra = fr.evaluate(
                        """() => [...document.querySelectorAll('textarea')]
                              .map(t => (t.value||'').trim()).filter(Boolean)""")
                    for e in extra:
                        if e not in payload["tas"]:
                            payload["tas"].append(e)
                except Exception:  # noqa: BLE001
                    continue
            for k, ta in enumerate(payload["tas"]):
                _emit(rows, f"[{l['head']} / {l['name']}] textarea {k}:\n{ta[:4000]}")
            for k, v in enumerate(payload["ins"]):
                _emit(rows, f"[{l['head']} / {l['name']}] input {k}: {v[:1000]}")
            if not payload["tas"] and not payload["ins"]:
                body = page.evaluate(
                    "() => document.body ? document.body.innerText : ''") or ""
                _emit(rows, f"[{l['head']} / {l['name']}] no fields — page text:\n"
                            + body[:4000])
        except Exception as e:  # noqa: BLE001
            _emit(rows, f"[{l['head']}] edit failed: {e.__class__.__name__}: {e}")
        _reload()


def _dump_email_bodies(page, rqst, rows):
    """On the Email Templates page (p=325), open each SWITCHED-ON email's
    edit page (p=326&emailId=N, a plain GET) and dump its subject, sender
    and body text. Read-only: the row's other links (delete, deactivate,
    set default) are never followed, and nothing is saved (Megan
    2026-11-15: the emails "aren't showing what's being sent")."""
    base = "https://applicantstream.com/index.cfm?rqst={}".format(rqst)
    page.goto(base + "&p=325", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)
    found = page.evaluate(
        """() => {
          const heads = [...document.querySelectorAll('b,strong,h1,h2,h3,h4,td,div,span,label')]
            .filter(e => e.children.length === 0 &&
                         /:\\s*$/.test((e.innerText||'').trim()) &&
                         (e.innerText||'').length < 60);
          const out = [];
          document.querySelectorAll('a[href*="p=326"][href*="emailId="]').forEach(a => {
            const tr = a.closest('tr');
            if (!tr) return;
            const cells = [...tr.querySelectorAll('td')];
            const name = cells.length ? (cells[0].innerText||'').trim() : '';
            const on = /\\(Activated\\)/.test(tr.innerText||'');
            const id = (a.getAttribute('href').match(/emailId=(\\d+)/)||[])[1];
            const pos = tr.getBoundingClientRect().top + window.scrollY;
            let best = '', bestPos = -1;
            heads.forEach(h => {
              const hp = h.getBoundingClientRect().top + window.scrollY;
              if (hp <= pos && hp > bestPos) { bestPos = hp; best = (h.innerText||'').trim(); }
            });
            out.push({id, name, on, head: best.replace(/:\\s*$/, '')});
          });
          return out;
        }""")
    on = [f for f in found if f["on"] and f["id"]]
    _emit(rows, f"===== phase 3: {len(found)} emails, {len(on)} switched on =====")
    for f in on:
        try:
            page.goto(base + "&p=326&emailId=" + f["id"],
                      wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)
            got = page.evaluate(
                """() => {
                  const v = n => { const e = document.querySelector('[name="' + n + '"]');
                                   return e ? (e.value||'').trim() : ''; };
                  const ta = document.querySelector('textarea[name="emailBody"]');
                  const tmp = document.createElement('div');
                  tmp.innerHTML = ta ? ta.value : '';
                  tmp.querySelectorAll('br').forEach(b => b.replaceWith('\\n'));
                  tmp.querySelectorAll('p,div,tr,h1,h2,h3,li').forEach(b => b.append('\\n'));
                  const links = [...tmp.querySelectorAll('a[href]')].map(a => a.getAttribute('href'));
                  return {subject: v('emailSubject'), from: v('fromAddress'),
                          body: (tmp.textContent||'').replace(/\\u00a0/g, ' '), links};
                }""")
            tag = "[EMAIL {} / {}]".format(f["head"], f["name"])
            _emit(rows, "{} subject: {}".format(tag, got["subject"]))
            _emit(rows, "{} from: {}".format(tag, got["from"]))
            for ln in got["links"]:
                _emit(rows, "{} link: {}".format(tag, ln))
            body = re.sub(r"[ \t]+", " ", got["body"])
            body = re.sub(r"\n\s*\n+", "\n\n", body).strip()
            _emit(rows, "{} body:\n{}".format(tag, body[:8000]))
        except Exception as e:  # noqa: BLE001
            _emit(rows, "[EMAIL {} / {}] read failed: {}".format(
                f["head"], f["name"], e.__class__.__name__))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="as_templates_probe")
    ap.add_argument("--office", default="11280")
    ap.add_argument("--owner", default="Rafael Hidalgo")
    ap.add_argument("--all", action="store_true",
                    help="dump EVERY template body, not just the pre-call ones")
    args = ap.parse_args(argv)

    rows = []
    with appstream_direct_session(verbose=True) as page:
        page.wait_for_timeout(3000)
        page.wait_for_selector("#searchMC", timeout=20000)
        if not fo._switch_office(page, args.office, args.owner,
                                 confirm_denial=True):
            _emit(rows, f"FATAL: cannot reach office {args.office}")
        else:
            page.wait_for_timeout(1500)
            rqst = _rqst(page)
            _emit(rows, f"=== office {args.office} ({args.owner}) ===")

            links = page.evaluate(
                """() => [...document.querySelectorAll('a')].map(a => ({
                      t: (a.innerText||'').replace(/\\s+/g,' ').trim().slice(0,80),
                      h: a.getAttribute('href')||''}))
                   .filter(x => x.t || x.h)""")
            cands, seen = [], set()
            for l in links:
                if not (HINT.search(l["t"]) or HINT.search(l["h"])):
                    continue
                m = re.search(r"p=(\d+)", l["h"])
                key = m.group(1) if m else l["h"][:60]
                if key in seen:
                    continue
                seen.add(key)
                cands.append((l["t"], l["h"], m.group(1) if m else None))
            _emit(rows, f"--- {len(cands)} candidate template/SMS links ---")
            for t, h, p in cands:
                _emit(rows, f"LINK p={p} text={t!r} href={h[:120]!r}")

            for t, h, p in cands[:12]:
                if not p:
                    continue
                url = f"https://applicantstream.com/index.cfm?rqst={rqst}&p={p}"
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(2500)
                except Exception as e:  # noqa: BLE001
                    _emit(rows, f"PAGE p={p}: nav failed {e.__class__.__name__}")
                    continue
                body = page.evaluate(
                    "() => document.body ? document.body.innerText : ''") or ""
                body = re.sub(r"\n{3,}", "\n\n", body).strip()
                tas = page.evaluate(
                    """() => [...document.querySelectorAll('textarea')]
                          .map(t => (t.value||'').trim()).filter(Boolean)""")
                _emit(rows, f"##### PAGE p={p} ({t!r}) — {len(body)} chars, "
                            f"{len(tas)} textareas #####")
                _emit(rows, body[:40000])
                for k, ta in enumerate(tas):
                    _emit(rows, f"--- textarea {k} ---\n{ta[:8000]}")

            # ---- phase 2: open Edit on the pre-call templates and capture the
            # actual message bodies (p=332 lists names only).
            _dump_template_bodies(page, rqst, rows,
                                  want=[] if args.all else None)
            if args.all:
                _dump_email_bodies(page, rqst, rows)

    # One tab per office. Probing a second office used to clear the first
    # one's dump, which made a two-office comparison impossible to hold.
    tab = f"{OUT_TAB_PREFIX} {args.office}"
    sh = _fill._client().open_by_key(CONTROL_SHEET_ID)
    try:
        ws = sh.worksheet(tab)
    except Exception:  # noqa: BLE001
        ws = sh.add_worksheet(title=tab, rows=max(len(rows) + 10, 100), cols=1)
    ws.clear()
    if ws.row_count < len(rows) + 5:
        ws.resize(rows=len(rows) + 5, cols=1)
    ws.update(rows, "A1")
    print(f"wrote {len(rows)} rows -> '{tab}'", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
