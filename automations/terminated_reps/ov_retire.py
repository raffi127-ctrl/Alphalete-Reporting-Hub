"""Retire terminated reps in OwnerVille (p=20 'Retire' button).

The hand recipe from 2026-10-09 ([[ownerville-retire-modal]]), scripted so it
runs off the machine's own OwnerVille session instead of a person's Chrome —
the login there asks for an email verification code, the automated one does
not.

    python -m automations.terminated_reps.ov_retire              # look only
    python -m automations.terminated_reps.ov_retire --apply      # retire

Look-only is the default: it prints, per pending name, what p=20 finds. --apply
retires ONLY names with exactly one live match; zero or several are listed for
a human (two 'Luis Ramirez' were live on 10/9 — picking one is not a script's
call). Ticks column E on 'Terminated Reps' only after p=20 stops returning the
rep, never before.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import time
from pathlib import Path

from automations.terminated_reps.deactivate import COL_OWNERVILLE, pending_for_week
from automations.terminated_reps.board import week_sunday
from automations.terminated_reps.tracker import COL_NAME, TAB, TRACKER_SHEET_ID, _open

V2 = "https://v2.ownerville.com/index.cfm"
# Own profile so a stray window on the shared one cannot block the run.
PROFILE_DIR = Path(__file__).resolve().parents[1] / "uploaded" / ".browser_profile_ov_retire"
_RQST = re.compile(r"rqst=([A-Za-z0-9_-]+)")
NOTE = "Terminated - week ending {sunday}"

# Strip the tracker's "(Wk 2)" suffix before searching OwnerVille.
_WK = re.compile(r"\s*\(wk\s*\d+\)\s*$", re.I)


def search_name(name: str) -> str:
    return _WK.sub("", name).strip()


_EMAIL_SEARCH_JS = """async (q) => {
  const t = $('#table-rep-user-list');
  await new Promise(res => { t.one('draw.dt', res); t.DataTable().search(q).draw(); });
  return t.find('button[data-action="terminateRep"]').map(function () { return this.id; }).get();
}"""


def roster(page, rqst: str, *, inactive: bool = True) -> list[dict]:
    """Every rep on p=20's live lists plus the retired list, with personpk.

    Read through the same getRepList endpoint the page's DataTable calls
    (mobrium_list.ownerville) -- typing a full name into the table's search box
    finds nobody, since it matches one column at a time."""
    from automations.mobrium_list.ownerville import (ENDPOINT, INACTIVE, PAGE_SIZE,
                                                     ROSTERS, _clean, _payload)
    out = []
    lists = list(ROSTERS.items()) + ([("inactive", INACTIVE)] if inactive else [])
    for roster_name, rep_type in lists:
        start = 0
        while True:
            # Own post with a long timeout: a 2000-row page of the retired
            # list takes longer than the default 30s.
            resp = page.request.post(
                ENDPOINT, data=_payload(rqst, rep_type, start, PAGE_SIZE),
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "X-Requested-With": "XMLHttpRequest"}, timeout=180000)
            data = json.loads(resp.text())
            chunk = data.get("data") or []
            for d in chunk:
                out.append({"pk": _clean(d.get("personpk")),
                            "name": f"{_clean(d.get('fname'))} {_clean(d.get('lname'))}",
                            "email": _clean(d.get("email")),
                            "start": _clean(d.get("fechabob")),
                            "retired": _clean(d.get("retireddate")),
                            "roster": roster_name})
            start += len(chunk)
            if not chunk or start >= int(data.get("recordsTotal") or 0):
                break
    return out


def matches(name: str, reps: list[dict]) -> list[dict]:
    """Exact folded name first; else same first name + one name's words a
    subset of the other's (middle names, second surnames)."""
    from automations.mobrium_list.ownerville import norm_name
    want = norm_name(search_name(name))
    exact = [r for r in reps if norm_name(r["name"]) == want]
    if exact:
        return exact
    w = want.split()
    out = []
    for r in reps:
        h = norm_name(r["name"]).split()
        if h and w and h[0] == w[0] and (set(w) <= set(h) or set(h) <= set(w)):
            out.append(r)
    return out


def retire(page, button_id: str, note: str) -> None:
    page.click("#" + button_id)
    page.wait_for_selector("#repModalDialog", state="visible", timeout=15000)
    page.select_option("#terminationReasonSelect", label="Terminated")
    page.wait_for_selector("#complianceReasonSelect", state="visible", timeout=10000)
    page.select_option("#complianceReasonSelect", label="Other")
    page.fill("#repModalDialog textarea", note)
    save = page.locator("#repModalDialog .modal-footer button.btn-primary, "
                        "#repModalDialog .modal-footer button:has-text('Save'), "
                        "#repModalDialog .modal-footer button:has-text('Retire')").first
    save.click()
    page.wait_for_selector("#repModalDialog", state="hidden", timeout=20000)


def tick_ownerville(done: dict[int, str]) -> None:
    """Tick E for {row: name}, re-reading each row's name first -- the tab can
    gain rows between the read and this write."""
    if not done:
        return
    _, ws = _open(TRACKER_SHEET_ID, TAB)
    for r, name in done.items():
        if ws.cell(r, COL_NAME).value.strip() != name.strip():
            print(f"  row {r} is no longer {name!r} -- not ticked", flush=True)
            continue
        ws.update_cell(r, COL_OWNERVILLE, True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", help="Sunday the week ends (YYYY-MM-DD); default last Sunday")
    ap.add_argument("--apply", action="store_true", help="actually retire")
    ap.add_argument("--relogin", action="store_true",
                    help="mint a fresh OwnerVille session first")
    a = ap.parse_args(argv)
    sunday = (dt.date.fromisoformat(a.week) if a.week
              else week_sunday(dt.date.today() - dt.timedelta(days=1)))
    todo = [p for p in pending_for_week(sunday) if p.ownerville and not p.ffp]
    print(f"week ending {sunday}: {len(todo)} still to retire in OwnerVille", flush=True)

    from automations.shared.tableau_patchright import ownerville_session
    if a.relogin:
        # Mint OUTSIDE ownerville_session: its own self-heal calls the sync
        # API from inside a running sync_playwright and dies on that.
        from automations.shared.appstream_autorenew import refresh_ownerville
        print("relogin:", refresh_ownerville(verbose=True), flush=True)
    report, done_rows = [], {}
    with ownerville_session(profile_dir=PROFILE_DIR) as page:
        # v2 pages need the rqst token the dashboard mints off the login
        # cookie; a bare ?p=20 bounces to the login page.
        page.goto(V2, wait_until="domcontentloaded")
        page.wait_for_timeout(6000)
        m = _RQST.search(page.url or "") or _RQST.search(page.evaluate(
            "() => { const a=[...document.querySelectorAll('a')]"
            ".find(x=>/rqst=/.test(x.getAttribute('href')||''));"
            " return a ? a.getAttribute('href') : ''; }") or "")
        if not m:
            raise RuntimeError("no rqst token on v2.ownerville.com")
        rqst = m.group(1)
        page.goto(f"{V2}?p=20&rqst={rqst}", wait_until="domcontentloaded")
        page.wait_for_selector("#table-rep-user-list", timeout=60000)
        time.sleep(3)
        reps = roster(page, rqst)
        print(f"ownerville roster: {len(reps)} records", flush=True)
        for p in todo:
            hits = matches(p.name, reps)
            live = [h for h in hits if h["roster"] != "inactive"]
            # Not found / several live people are left for a human: an empty
            # match is also what a spelling difference looks like, and two
            # live people with one name is not a script's call.
            if live:
                status = "ok" if len(live) == 1 else "several-live"
            else:
                status = "already-retired" if hits else "not-found"
            if a.apply and status == "ok":
                pk = live[0]["pk"]
                ids = page.evaluate(_EMAIL_SEARCH_JS, live[0]["email"] or live[0]["name"],
                                    isolated_context=False)
                if f"terminate_{pk}" not in ids:
                    status = "button-missing"
                else:
                    retire(page, f"terminate_{pk}",
                           NOTE.format(sunday=sunday.strftime("%m/%d")))
                    time.sleep(2)
                    still = [r for r in roster(page, rqst, inactive=False)
                             if r["pk"] == pk]
                    status = "RETIRED" if not still else "retire-failed"
            if status in ("RETIRED", "already-retired"):
                done_rows[p.row] = p.name
            report.append({"row": p.row, "name": p.name, "status": status, "hits": hits})
            print(f"  {status:15} {p.name:32} "
                  + "; ".join(f"{h['name']} <{h['email']}> {h['roster']} "
                              f"start {h['start']} retired {h['retired']}" for h in hits),
                  flush=True)

    if a.apply:
        tick_ownerville(done_rows)
        print(f"ticked E on {len(done_rows)} rows", flush=True)
    out = f"output/ov_retire_{dt.date.today()}{'' if a.apply else '_dryrun'}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print("log:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
