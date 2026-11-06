"""Create an office's "Lucy ECO <Owner>" AppStream admin login — from a Lucy,
before the office enrolls (Megan 2026-11-06: "we need to make it so you can
make their AppStream login before enrollment / on the dry run").

WHAT A PERSON DID BY HAND, now done here:
  AppStream -> Settings -> Admins (p=311) -> "Add New Admin" -> fill the form
  -> tick the owner's office under "Offices Not Assigned" (right) -> Save
  Changes. The office then shows under "Offices Already Assigned" (left) and
  is the ONLY office that login can see.

THE FORMAT (Megan 2026-11-06, exactly — see appstream_provision.eco_login):
  First Name  Lucy ECO        Username  LucyECO<OwnerFirst>
  Last Name   <Owner Name>    Password  <OwnerFirst>123!

WHEN THE OWNER IS NOT IN THE OFFICE LIST (Megan): the login is STILL created,
and we get told — the owner has to be added to our call center before the
office can be assigned. Re-run the same command once AppStream has added them:
it finds the existing admin and only does the assignment.

RUNS ON A LUCY: the saved 'Lucy Reports' session (appstream_direct_session)
has to be an admin-manager on the Alphalete Marketing Call Center (account
23981). If it is not, exit 4 says so and nothing is touched.

    python -m automations.shared.appstream_admins "Nigel Marshall" --office-id 20034
    python -m automations.shared.appstream_admins "Nigel Marshall" --check      # read-only
    lucy provision_appstream "Nigel Marshall" --office-id 20034 --machine "Lucy 4"

FORM FACTS (read off the live page 2026-11-06): text inputs #firstname
#lastname #emailaddress #phone #username #password, checkbox sendLoginEmail,
hidden frmAdmId / frmAdmSuper / frmNewAccountIds / frmRmvAccountIds. The two
office grids are ExtJS 3 grids (.x-grid3-row / .x-grid3-cell-inner) with a
checkbox column (.x-grid3-row-checker); the right one is fed by
cc.cfc?method=accountsNotAssigned. The all-admins list on the far left is a
third grid with one cell per row.

EXIT CODES  0 admin exists + office assigned (+ login verified)
            3 admin exists, owner NOT in the call center's office list (told Megan)
            4 this session cannot manage admins (no "Add New Admin")
            5 the form / save / verification failed (details in the log)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

BASE = "https://applicantstream.com/index.cfm"
ADMINS_PAGE = 311
TOKRE = re.compile(r"rqst=([A-Za-z0-9\-]+)")
MEGAN = "U04G5HJBGFN"
LOGINS_TAB = "AppStream Logins"
LOGINS_HEAD = ["owner", "office_key", "username", "password", "office_id",
               "office_name", "assigned", "login_verified", "updated_at",
               "machine", "note"]


# --- names --------------------------------------------------------------------
def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


def is_eco_admin_for(admin_name: str, owner: str) -> bool:
    """'Lucy ECO Nigel Marshall' / 'LucyECO Nigel Marshall' / 'LucyEco ...'."""
    a, o = norm(admin_name), norm(owner)
    return bool(o) and a in ("lucy eco " + o, "lucyeco " + o)


def match_office(rows: List[Dict], owner: str,
                 office_id: Optional[str] = None) -> List[Dict]:
    """Rows of the 'Offices Not Assigned' grid that are this owner's.

    An office id wins outright. Otherwise the owner's full name, then (one
    owner, several offices like 'BEYMARK, INC. 2nd') every row whose owner
    starts with the first+last we were given. Returns [] when nobody matches
    and 2+ when it is ambiguous — the caller decides, never this."""
    if office_id:
        return [r for r in rows if str(r.get("id", "")).strip() == str(office_id).strip()]
    o = norm(owner)
    exact = [r for r in rows if norm(r.get("owner", "")) == o]
    if exact:
        return exact
    parts = o.split()
    if len(parts) >= 2:
        want = parts[0] + " " + parts[-1]
        return [r for r in rows
                if norm(r.get("owner", "")).startswith(parts[0] + " ")
                and parts[-1] in norm(r.get("owner", "")).split()
                or norm(r.get("owner", "")) == want]
    return []


# --- the page -----------------------------------------------------------------
_GRIDS_JS = """
() => {
  const grids = [...document.querySelectorAll('.x-grid3')];
  return grids.map(g => {
    const panel = g.closest('.x-panel');
    const hdr = panel ? panel.querySelector('.x-panel-header') : null;
    const title = hdr ? hdr.innerText : '';
    const rows = [...g.querySelectorAll('.x-grid3-row')].map((r, i) => {
      const cells = [...r.querySelectorAll('.x-grid3-cell-inner')]
        .map(c => (c.innerText || '').trim());
      return {i, cells, selected: r.classList.contains('x-grid3-row-selected')};
    });
    return {title: (title || '').replace(/\\s+/g, ' ').trim(), rows};
  });
}
"""


def _grids(page) -> List[Dict]:
    try:
        return page.evaluate(_GRIDS_JS) or []
    except Exception:  # noqa: BLE001
        return []


def _office_rows(grid: Dict) -> List[Dict]:
    out = []
    for r in grid.get("rows", []):
        cells = [c for c in r.get("cells", []) if c != ""]
        if len(cells) >= 3 and re.fullmatch(r"\d+", cells[0]):
            out.append({"id": cells[0], "owner": cells[1], "office": cells[2],
                        "i": r["i"], "selected": r.get("selected", False)})
    return out


def read_office_grids(page) -> Dict[str, List[Dict]]:
    """{'assigned': [...], 'not_assigned': [...]} off the open admin form."""
    assigned, not_assigned, unnamed = [], [], []
    for g in _grids(page):
        rows = _office_rows(g)
        t = g.get("title", "").lower()
        if "not assigned" in t:
            not_assigned = rows
        elif "already assigned" in t or "assigned" in t:
            assigned = rows
        else:
            unnamed.append((g, rows))
    if not not_assigned and not assigned and unnamed:
        # No panel headers found — fall back to DOM order: the all-admins list
        # (1-cell rows) first, then Already Assigned, then Not Assigned.
        office_grids = [(g, rows) for g, rows in unnamed
                        if rows or any(len(r.get("cells", [])) >= 3 for r in g.get("rows", []))]
        if len(office_grids) >= 2:
            assigned, not_assigned = office_grids[-2][1], office_grids[-1][1]
        elif office_grids:
            not_assigned = office_grids[-1][1]
    return {"assigned": assigned, "not_assigned": not_assigned}


def admin_names(page) -> List[str]:
    names = []
    for g in _grids(page):
        for r in g.get("rows", []):
            cells = [c for c in r.get("cells", []) if c]
            if len(cells) == 1 and not re.fullmatch(r"\d+", cells[0]):
                names.append(cells[0])
    return names


def _token(page) -> str:
    m = TOKRE.search(page.url or "") or TOKRE.search(page.content() or "")
    if not m:
        raise RuntimeError("no AppStream session token on the page")
    return m.group(1)


def open_admins(page, log=print) -> str:
    tok = _token(page)
    page.goto("%s?rqst=%s&p=%d" % (BASE, tok, ADMINS_PAGE), timeout=90_000)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(4_000)
    if page.locator("button:has-text('Add New Admin')").count() == 0:
        body = page.inner_text("body")[:300].replace("\n", " ")
        log("this session has NO 'Add New Admin' on Settings -> Admins; it is "
            "not an admin-manager here. Page said: %s" % body)
        raise PermissionError("cannot manage admins")
    return tok


def _wait_form(page, timeout_ms: int = 30_000) -> None:
    page.wait_for_selector("#firstname", timeout=timeout_ms)
    # the office grids come in by AJAX after the form — give them a moment
    for _ in range(20):
        if read_office_grids(page)["not_assigned"]:
            return
        page.wait_for_timeout(500)


def open_new_admin(page) -> None:
    page.locator("button:has-text('Add New Admin')").first.click()
    _wait_form(page)


def open_existing_admin(page, name: str) -> bool:
    cell = page.locator(".x-grid3-cell-inner", has_text=name)
    for i in range(cell.count()):
        c = cell.nth(i)
        if norm(c.inner_text()) == norm(name):
            c.click()
            _wait_form(page)
            return True
    return False


def _tick_not_assigned_row(page, office_id: str) -> bool:
    """Tick the checkbox of the Not-Assigned row for this office id."""
    js = """
    (oid) => {
      const grids = [...document.querySelectorAll('.x-grid3')];
      for (const g of grids) {
        const panel = g.closest('.x-panel');
        const hdr = panel ? (panel.querySelector('.x-panel-header') || {}).innerText || '' : '';
        if (!/not assigned/i.test(hdr) && grids.indexOf(g) !== grids.length - 1) continue;
        for (const r of g.querySelectorAll('.x-grid3-row')) {
          const cells = [...r.querySelectorAll('.x-grid3-cell-inner')].map(c => (c.innerText||'').trim());
          if (cells.some(c => c === String(oid))) {
            const chk = r.querySelector('.x-grid3-row-checker') || r.querySelector('.x-grid3-cell-inner');
            chk.scrollIntoView({block: 'center'});
            const b = chk.getBoundingClientRect();
            return {x: b.left + b.width / 2, y: b.top + b.height / 2};
          }
        }
      }
      return null;
    }
    """
    pt = page.evaluate(js, str(office_id))
    if not pt:
        return False
    page.mouse.click(pt["x"], pt["y"])
    page.wait_for_timeout(600)
    rows = read_office_grids(page)["not_assigned"]
    return any(r["id"] == str(office_id) and r["selected"] for r in rows)


def _fill(page, login: Dict) -> None:
    page.fill("#firstname", login["first_name"])
    page.fill("#lastname", login["last_name"])
    page.fill("#username", login["username"])
    page.fill("#password", login["password"])


def _save(page) -> None:
    page.locator("button:has-text('Save Changes')").first.click()
    page.wait_for_timeout(5_000)


def _record(owner: str, office_key: str, login: Dict, office: Optional[Dict],
            assigned: bool, verified: Optional[bool], note: str, log=print) -> None:
    """Upsert the 'AppStream Logins' tab of the Lucy Access App workbook."""
    try:
        from automations.recruiting_report.fill import open_by_key
        from automations.icd_alerts import post as P
        wb = open_by_key(P.RELAY_SPREADSHEET_ID)
        try:
            ws = wb.worksheet(LOGINS_TAB)
        except Exception:  # noqa: BLE001
            ws = wb.add_worksheet(LOGINS_TAB, rows=200, cols=len(LOGINS_HEAD))
            ws.update("A1", [LOGINS_HEAD])
        rows = ws.get_all_values()
        if not rows or [h.strip() for h in rows[0][:len(LOGINS_HEAD)]] != LOGINS_HEAD:
            ws.update("A1", [LOGINS_HEAD])
            rows = ws.get_all_values()
        try:
            import socket
            machine = socket.gethostname()
        except Exception:  # noqa: BLE001
            machine = ""
        row = [owner, office_key, login["username"], login["password"],
               (office or {}).get("id", ""), (office or {}).get("office", ""),
               "TRUE" if assigned else "FALSE",
               "" if verified is None else ("TRUE" if verified else "FALSE"),
               dt.datetime.now().strftime("%Y-%m-%d %H:%M"), machine, note]
        for i, r in enumerate(rows[1:], start=2):
            if r and norm(r[0]) == norm(owner):
                ws.update("A%d" % i, [row])
                break
        else:
            ws.append_row(row, value_input_option="RAW")
        log("recorded on '%s' (Lucy Access App)" % LOGINS_TAB)
    except Exception as e:  # noqa: BLE001 — the login exists; a missing row is not a failure
        log("could not record on '%s': %s" % (LOGINS_TAB, str(e)[:160]))


def _tell_megan(text: str, log=print) -> None:
    try:
        from automations.icd_alerts import post as P
        P._slack(MEGAN, text)
        log("told Megan")
    except Exception as e:  # noqa: BLE001
        log("could not DM Megan: %s" % str(e)[:160])


def verify_login(login: Dict, log=print, headed: bool = False) -> Optional[bool]:
    """Sign in as the NEW account in a scratch profile. True = the office
    console (#searchMC) or at least a signed-in page; False = login form
    again; None = could not tell (Chrome problem)."""
    import shutil
    from automations.shared.tableau_patchright import (
        appstream_direct_session, APPSTREAM_PROFILE_DIR)
    probe = APPSTREAM_PROFILE_DIR.parent / ".appstream_profile_provision"
    shutil.rmtree(probe, ignore_errors=True)
    try:
        with appstream_direct_session(headless=not headed, verbose=False,
                                      profile_dir=probe,
                                      username=login["username"],
                                      password=login["password"],
                                      allow_form_login=True,
                                      force_form_login=True) as page:
            if page.locator("#searchMC").count() > 0:
                log("login verified: office console open as %s" % login["username"])
                return True
            body = (page.inner_text("body") or "")[:600].lower()
            if "log out" in body and "password" not in body:
                log("login verified: signed in as %s (no office console yet)"
                    % login["username"])
                return True
            log("login NOT verified: still on the sign-in page")
            return False
    except Exception as e:  # noqa: BLE001
        log("login check could not run: %s" % str(e)[:200])
        return None
    finally:
        shutil.rmtree(probe, ignore_errors=True)


# --- the job --------------------------------------------------------------------
def provision(owner: str, office_id: Optional[str] = None, office_key: str = "",
              check_only: bool = False, verify: bool = True, headed: bool = False,
              log=print) -> int:
    from automations.shared.appstream_provision import eco_login
    from automations.shared.tableau_patchright import appstream_direct_session

    login = eco_login(owner)
    office_key = office_key or norm(owner).split()[0]
    log("owner       : %s" % owner)
    log("login       : %s / %s  (first '%s', last '%s')"
        % (login["username"], login["password"], login["first_name"], login["last_name"]))

    existing = None
    office: Optional[Dict] = None
    assigned = False
    created = False
    note = ""
    with appstream_direct_session(headless=not headed, verbose=False) as page:
        try:
            open_admins(page, log=log)
        except PermissionError:
            return 4
        names = admin_names(page)
        log("admins      : %d listed" % len(names))
        for n in names:
            if is_eco_admin_for(n, owner):
                existing = n
                break
        if existing:
            log("already there: '%s' — opening it" % existing)
            if not open_existing_admin(page, existing):
                log("could not open '%s'" % existing)
                return 5
            # keep whatever password the record carries, if the page shows it
            try:
                pw = page.input_value("#password")
                un = page.input_value("#username")
                if un:
                    login["username"] = un
                if pw:
                    login["password"] = pw
            except Exception:  # noqa: BLE001
                pass
        else:
            open_new_admin(page)
        grids = read_office_grids(page)
        log("offices     : %d already assigned, %d not assigned"
            % (len(grids["assigned"]), len(grids["not_assigned"])))
        have = match_office(grids["assigned"], owner, office_id)
        if have:
            office, assigned = have[0], True
            log("assigned    : %s %s (%s)" % (office["id"], office["owner"], office["office"]))
        cands = match_office(grids["not_assigned"], owner, office_id)
        if not have and len(cands) > 1:
            log("AMBIGUOUS — %s has several offices; pass --office-id: %s"
                % (owner, "; ".join("%s %s" % (c["id"], c["office"]) for c in cands)))
            return 5
        if not have and cands:
            office = cands[0]
            log("to assign   : %s %s (%s)" % (office["id"], office["owner"], office["office"]))
        if not have and not cands:
            note = ("%s is NOT in our call center's office list — ask AppStream to add "
                    "them (account 23981) then re-run this command to assign the office"
                    % owner)
            log("NOT LISTED  : " + note)
        if check_only:
            log("SUMMARY check-only · admin %s · office %s"
                % ("exists" if existing else "would be created",
                   "assigned" if assigned else (office["id"] if office else "NOT LISTED")))
            return 0 if (assigned or office) else 3

        if not existing:
            _fill(page, login)
        if office and not assigned:
            if not _tick_not_assigned_row(page, office["id"]):
                log("could not tick office %s in 'Offices Not Assigned'" % office["id"])
                if not existing:
                    log("NOT saving a login with no office ticked — fix the tick first")
                    return 5
        if not existing or (office and not assigned):
            _save(page)
            created = not existing
            # prove it: reload the list, open the admin, read the left grid
            open_admins(page, log=log)
            names = admin_names(page)
            mine = next((n for n in names if is_eco_admin_for(n, owner)), None)
            if not mine:
                log("after Save, '%s %s' is NOT in the admin list" % (login["first_name"], owner))
                return 5
            if not open_existing_admin(page, mine):
                log("saved, but could not reopen '%s' to check the office" % mine)
                return 5
            grids = read_office_grids(page)
            have = match_office(grids["assigned"], owner, office["id"] if office else None)
            if office and not have:
                log("saved, but office %s is NOT under 'Offices Already Assigned'" % office["id"])
                return 5
            if have:
                office, assigned = have[0], True
            log("saved       : admin '%s'%s" % (mine, " · office %s assigned" % office["id"] if assigned else ""))

    verified: Optional[bool] = None
    if verify and (created or not existing):
        verified = verify_login(login, log=log, headed=headed)
    _record(owner, office_key, login, office, assigned, verified, note, log=log)
    if not office:
        _tell_megan(
            ":warning: *AppStream login for %s* — created `%s` but could NOT assign an office: "
            "%s is not in our call center's office list. Get them added to Alphalete "
            "Marketing Call Center (23981) in AppStream, then run "
            "`lucy provision_appstream \"%s\" --machine \"Lucy 4\"` again to assign it."
            % (owner, login["username"], owner, owner), log=log)
    log("SUMMARY %s · %s · office %s%s"
        % ("created" if created else "exists", login["username"],
           ("%s assigned" % office["id"]) if assigned else "NOT LISTED (Megan told)",
           "" if verified is None else (" · login verified" if verified else " · LOGIN FAILED")))
    if not office:
        return 3
    if verified is False:
        return 5
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("owner", help="the owner's name, e.g. \"Nigel Marshall\"")
    ap.add_argument("--office-id", help="their AppStream/OwnerVille office id, "
                                        "when the name alone is ambiguous")
    ap.add_argument("--office-key", default="", help="their ECO key (defaults to first name)")
    ap.add_argument("--check", action="store_true", help="read-only: say what would happen")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip signing in as the new login afterwards")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args(argv)
    return provision(a.owner, office_id=a.office_id, office_key=a.office_key,
                     check_only=a.check, verify=not a.no_verify, headed=a.headed)


if __name__ == "__main__":
    sys.exit(main())
