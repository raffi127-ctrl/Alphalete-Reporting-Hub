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
OUT_TAB = "AS Templates Probe"
HINT = re.compile(r"templat|sms|text|email|communicat|await|message", re.I)


def _emit(rows, line):
    print(line[:200], flush=True)
    for i in range(0, max(len(line), 1), 45000):
        rows.append([line[i:i + 45000]])


def main(argv=None):
    ap = argparse.ArgumentParser(prog="as_templates_probe")
    ap.add_argument("--office", default="11280")
    ap.add_argument("--owner", default="Rafael Hidalgo")
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

    sh = _fill._client().open_by_key(CONTROL_SHEET_ID)
    try:
        ws = sh.worksheet(OUT_TAB)
    except Exception:  # noqa: BLE001
        ws = sh.add_worksheet(title=OUT_TAB, rows=max(len(rows) + 10, 100),
                              cols=1)
    ws.clear()
    if ws.row_count < len(rows) + 5:
        ws.resize(rows=len(rows) + 5, cols=1)
    ws.update(rows, "A1")
    print(f"wrote {len(rows)} rows -> '{OUT_TAB}'", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
