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
from contextlib import contextmanager
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
      let cells = [...r.querySelectorAll('.x-grid3-cell-inner')]
        .map(c => (c.innerText || '').trim());
      // the all-admins list renders its one column without .x-grid3-cell-inner
      // (Lucy 3, 2026-11-06: 'admins: 0 listed' with 78 rows on screen)
      if (!cells.length) cells = [(r.innerText || '').replace(/\\s+/g, ' ').trim()];
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
    if not names:
        # belt and braces: the list is also plain text on the page, one name
        # per line between 'Admin Name' and the form
        try:
            body = page.inner_text("body")
            block = body.split("Admin Name", 1)[1] if "Admin Name" in body else ""
            for line in block.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith(("Add New Admin", "Show/Hide", "Admin Details")):
                    break
                names.append(line)
        except Exception:  # noqa: BLE001
            pass
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
    if page.locator("button:text-is('Add New Admin')").count() == 0:
        body = page.inner_text("body")[:300].replace("\n", " ")
        log("this session has NO 'Add New Admin' on Settings -> Admins; it is "
            "not an admin-manager here. Page said: %s" % body)
        raise PermissionError("cannot manage admins")
    return tok


_CAPTURED: Dict[str, list] = {"assigned": [], "not_assigned": []}


def _walk(obj, out: list) -> None:
    if isinstance(obj, dict):
        if any(isinstance(v, (str, int)) for v in obj.values()):
            out.append(obj)
        for v in obj.values():
            _walk(v, out)
    elif isinstance(obj, list):
        # a record can also be a plain list of values (ColdFusion query rows)
        if obj and all(isinstance(v, (str, int, float)) or v is None for v in obj):
            out.append({"c%d" % i: ("" if v is None else v) for i, v in enumerate(obj)})
            return
        for v in obj:
            _walk(v, out)


def _rows_from_json(text: str) -> List[Dict]:
    """The grid data call answers JSON; keep every record that carries an
    office id (a 3-6 digit number), as {'id','owner','office','raw'}."""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    found, out = [], []
    _walk(data, found)
    for d in found:
        vals = {k: str(v) for k, v in d.items() if isinstance(v, (str, int))}
        ids = [v for v in vals.values() if re.fullmatch(r"\d{3,6}", v)]
        texts = [v for v in vals.values() if v and not re.fullmatch(r"\d+", v)]
        # {"totalcount": "173"} is a count, not an office: a row has a name too
        if not ids or not texts:
            continue
        out.append({"id": ids[0], "owner": texts[0] if texts else "",
                    "office": texts[1] if len(texts) > 1 else "", "raw": vals})
    return out


def _hook_grid_calls(page) -> None:
    def _on_response(resp):
        try:
            url = resp.url or ""
            if "accountsNotAssigned" in url:
                _CAPTURED["not_assigned"] = _rows_from_json(resp.text())
            elif "accountsAssigned" in url:
                _CAPTURED["assigned"] = _rows_from_json(resp.text())
        except Exception:  # noqa: BLE001
            pass
    page.on("response", _on_response)


def _wait_form(page, timeout_ms: int = 30_000) -> None:
    page.wait_for_selector("#firstname", timeout=timeout_ms)
    # the office grids come in by AJAX after the form — give them a moment
    for _ in range(20):
        if read_office_grids(page)["not_assigned"]:
            break
        page.wait_for_timeout(500)
    page.wait_for_timeout(1_500)


def _grid_diag(page) -> str:
    try:
        return page.evaluate("""() => {
          const g = [...document.querySelectorAll('.x-grid3')];
          return g.map(x => {
            const p = x.closest('.x-panel');
            const t = p && p.querySelector('.x-panel-header') ? p.querySelector('.x-panel-header').innerText.replace(/\\s+/g,' ').trim() : '';
            const sc = x.querySelector('.x-grid3-scroller');
            return (t || 'untitled') + ': rows=' + x.querySelectorAll('.x-grid3-row').length
              + ' pager=' + (!!(p && p.querySelector('.x-tbar-page-next')))
              + ' scroll=' + (sc ? sc.scrollHeight + '/' + sc.clientHeight : '-');
          }).join(' | ');
        }""")
    except Exception as e:  # noqa: BLE001
        return "diag failed: %s" % str(e)[:80]


def _bring_row_on_screen(page, office_id: str, log=print) -> bool:
    """A long 'Not Assigned' list is not all in the DOM at once (Nigel 20034
    was in the data but not among the 173 rendered rows, 2026-11-06). Scroll
    the grid to the bottom in steps and page it if it has a pager, until the
    row with this office id exists."""
    def _present() -> bool:
        return any(r["id"] == str(office_id)
                   for r in read_office_grids(page)["not_assigned"])
    if _present():
        return True
    js_scroll = """(step) => {
      const grids = [...document.querySelectorAll('.x-grid3')];
      const g = grids[grids.length - 1];
      const sc = g && g.querySelector('.x-grid3-scroller');
      if (!sc) return -1;
      sc.scrollTop = Math.min(sc.scrollTop + step, sc.scrollHeight);
      sc.dispatchEvent(new Event('scroll'));
      return sc.scrollTop;
    }"""
    last = -2
    for _ in range(60):
        pos = page.evaluate(js_scroll, 600)
        page.wait_for_timeout(300)
        if _present():
            return True
        if pos == last or pos < 0:
            break
        last = pos
    # a pager toolbar?
    for _ in range(40):
        nxt = page.locator(".x-tbar-page-next:visible").last
        if nxt.count() == 0:
            break
        try:
            nxt.click()
        except Exception:  # noqa: BLE001
            break
        page.wait_for_timeout(800)
        if _present():
            return True
    log("could not bring office %s onto the screen (%s)" % (office_id, _grid_diag(page)))
    return False


def open_new_admin(page) -> None:
    page.locator("button:text-is('Add New Admin'):visible").first.click()
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


# THE REAL BUTTON IS THE EXTJS ONE. `button:has-text('Save Changes')` also
# matches a hidden Bootstrap modal button (#commonModalSave, 'Save changes')
# that sits in the page template — Lucy 3's first run (2026-11-06) resolved to
# that one and never saved. Exact text + the ExtJS classes, visible only.
_SAVE_SELECTOR = ("button.x-btn-text.icon-save:visible, "
                  "button.x-btn-text:text-is('Save Changes'):visible")


def _save(page) -> None:
    btn = page.locator(_SAVE_SELECTOR).first
    btn.wait_for(state="visible", timeout=15_000)
    btn.click()
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


# --- telling the ICD -----------------------------------------------------------
ENROLL_URL = "https://lucyeco.streamlit.app/join-lucy-eco"
_SLACK_IDS_MD = Path(__file__).resolve().parents[2] / "resources" / "owner-slack-ids.md"


def owner_slack_id(owner: str) -> str:
    """The ICD's Slack id: resources/owner-slack-ids.md first (the one place
    for who's who), then the ICD Signup tab's slack_user_id. '' when unknown —
    a DM to a guessed account is worse than no DM."""
    o = norm(owner).split()
    if len(o) < 2:
        return ""
    want_first, want_last = o[0], o[-1]
    try:
        for line in _SLACK_IDS_MD.read_text().splitlines():
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 3:
                continue
            name = norm(re.sub(r"\(.*?\)", "", cells[0])).split()
            ids = [c for c in cells if re.fullmatch(r"U[A-Z0-9]{8,12}", c)]
            if name and ids and name[0] == want_first and name[-1] == want_last:
                return ids[0]
    except OSError:
        pass
    try:
        from automations.recruiting_report.fill import open_by_key
        from automations.icd_alerts import post as P
        ws = open_by_key(P.RELAY_SPREADSHEET_ID).worksheet("ICD Signup")
        rows = ws.get_all_values()
        hdr = [h.strip().lower() for h in rows[0]]
        io, iu = hdr.index("owner"), hdr.index("slack_user_id")
        for r in rows[1:]:
            if len(r) > max(io, iu) and norm(r[io]) == norm(owner) and r[iu].strip():
                return r[iu].strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


PYTHON_URL = "https://www.python.org/downloads/"


def icd_message(owner: str, login: Dict) -> str:
    """Megan 2026-11-06: say what it is, that the enrollment form is done
    together on the Zoom call, give the Python download to do BEFORE the call
    (the installer's slow first step), and list what to have ready — OwnerVille
    login, the email the SaraPlus code goes to, the Sterling email login (the
    background-check links are rolling out), anything else the installer asks."""
    first = owner.strip().split()[0]
    return (
        "Hi %s! Lucy here :wave: I'm Alphalete's reporting assistant.\n\n"
        "*Your AppStream login for Lucy ECO is ready* (this is the login I use, "
        "not your own):\n"
        "• Username: `%s`\n"
        "• Password: `%s`\n\n"
        "We'll go through the enrollment form together on our Zoom call, so "
        "nothing to fill in yet.\n\n"
        "*One thing to do before the call* (it's the slow part): install Python "
        "on the computer Lucy will run on. Click, download, open it and hit "
        "Next until it's done:\n%s\n\n"
        "*Please have these ready for the call:*\n"
        "• Your OwnerVille username and password\n"
        "• The email login where your SaraPlus codes go (if you're in that program)\n"
        "• Your Sterling email login\n\n"
        "That keeps the call short. Reply here if anything's unclear. "
        "Here's the sign-up form we'll use on the call, for reference: %s"
        % (first, login["username"], login["password"], PYTHON_URL, ENROLL_URL))


def _dm_icd(owner: str, login: Dict, slack_id: str, log=print) -> bool:
    """Megan 2026-11-06: 'once this is created you should DM it and the lucyeco
    enrollment link to the ICD'. Only when the office is assigned — a login
    that sees no office is not ready to hand over."""
    sid = (slack_id or "").strip() or owner_slack_id(owner)
    if not sid:
        log("no Slack id known for %s — DM NOT sent (add them to "
            "resources/owner-slack-ids.md or pass --slack-id)" % owner)
        return False
    try:
        from automations.icd_alerts import post as P
        P._slack(sid, icd_message(owner, login))
        log("DM sent to %s (%s) with the login + %s" % (owner, sid, ENROLL_URL))
        return True
    except Exception as e:  # noqa: BLE001
        log("DM to %s (%s) failed: %s" % (owner, sid, str(e)[:160]))
        return False


# --- running it from YOUR login (Megan / Eve) -----------------------------------
# Megan 2026-11-06: the office list on the admin form depends on who is signed
# in. 'Lucy Reports' on a Lucy was offered 173 offices without Nigel's; Megan's
# own login offers every office. So the normal way to run this is on Megan's or
# Eve's Mac, signed in as themselves (--local). The profile keeps the session.
ADMIN_PROFILE = Path.home() / ".config" / "recruiting-report" / "appstream-admin-profile"
OPERATORS = {"megan": "U04G5HJBGFN", "eve": "U088E2KJEV8"}


def _signed_in(page) -> bool:
    try:
        if TOKRE.search(page.url or ""):
            return True
        return page.locator("a[href*='p=99']").count() > 0   # the Log Out link
    except Exception:  # noqa: BLE001
        return False


@contextmanager
def operator_session(headed: bool = True, log=print):
    """A page on AppStream as the PERSON running this. If the saved profile is
    not signed in, the window stays open and they sign in themselves (the
    security box clears by itself if it is left alone 20-30s)."""
    from patchright.sync_api import sync_playwright
    from automations.shared.tableau_patchright import _launch_persistent
    ADMIN_PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = _launch_persistent(p, ADMIN_PROFILE, headless=not headed,
                                 label="appstream_admin", verbose=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(BASE, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(4_000)
            if not _signed_in(page):
                log("Sign in to AppStream in the window that just opened, with YOUR "
                    "login. Leave the security box alone — it clears itself. "
                    "Waiting up to 5 minutes...")
                for _ in range(60):
                    page.wait_for_timeout(5_000)
                    if _signed_in(page):
                        break
                else:
                    raise RuntimeError("not signed in to AppStream after 5 minutes")
                page.wait_for_timeout(3_000)
            log("signed in as you")
            yield page
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass


def _tell_operator(text: str, log=print) -> None:
    """The person who ran it (MINI_BY on a Lucy, the Mac's user otherwise)."""
    try:
        from automations.shared.incident_thread import operator_name
        who = operator_name()
    except Exception:  # noqa: BLE001
        who = "Megan"
    sid = OPERATORS.get(who.lower(), MEGAN)
    try:
        from automations.icd_alerts import post as P
        P._slack(sid, text)
        log("told %s" % who)
    except Exception as e:  # noqa: BLE001
        log("could not DM %s: %s" % (who, str(e)[:160]))


# --- the job --------------------------------------------------------------------
def provision(owner: str, office_id: Optional[str] = None, office_key: str = "",
              check_only: bool = False, verify: bool = True, headed: bool = False,
              dump_offices: bool = False, force_verify: bool = False,
              slack_id: str = "", dm: bool = True, local: bool = False,
              log=print) -> int:
    from automations.shared.appstream_provision import eco_login
    from automations.shared.tableau_patchright import appstream_direct_session

    login = eco_login(owner)
    office_key = office_key or norm(owner).split()[0]
    log("owner       : %s" % owner)
    # the password is never printed: this log's tail lands in the queue's
    # Result cell, which `lucy status` puts on screen. The 'AppStream Logins'
    # tab holds it.
    log("login       : %s  (first '%s', last '%s')"
        % (login["username"], login["first_name"], login["last_name"]))

    existing = None
    office: Optional[Dict] = None
    assigned = False
    created = False
    note = ""
    session = (operator_session(headed=True, log=log) if local
               else appstream_direct_session(headless=not headed, verbose=False))
    with session as page:
        _hook_grid_calls(page)
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
        log("offices     : on screen %d already assigned, %d not assigned · data "
            "call %d assigned, %d not assigned · %s"
            % (len(grids["assigned"]), len(grids["not_assigned"]),
               len(_CAPTURED["assigned"]), len(_CAPTURED["not_assigned"]),
               _grid_diag(page)))
        if _CAPTURED["not_assigned"]:
            log("data sample : %s" % json.dumps(_CAPTURED["not_assigned"][0]["raw"])[:200])
        # the data call is the truth; the screen may hold only the first rows
        if len(_CAPTURED["not_assigned"]) > len(grids["not_assigned"]):
            grids["not_assigned"] = _CAPTURED["not_assigned"]
        if len(_CAPTURED["assigned"]) > len(grids["assigned"]):
            grids["assigned"] = _CAPTURED["assigned"]
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
            # THE LIST IS PER SIGNED-IN ADMIN (2026-11-06): Lucy Reports' session was
            # offered 173 offices without Nigel's 20034, while Megan's own session
            # offered it. So "not listed" means Lucy cannot tick it — a person whose
            # list has it (Megan) can, or Lucy Reports gets the office first.
            note = ("either %s isn't in our call center or your login doesn't have "
                    "access to that office — check, then assign it manually or "
                    "request access" % owner)
            log("NOT LISTED  : " + note)
        if check_only and dump_offices:
            allrows = grids["assigned"] + grids["not_assigned"]
            log("OFFICE LIST (%d): %s" % (len(allrows), "; ".join(
                "%s %s" % (r["id"], r["owner"]) for r in sorted(allrows, key=lambda r: norm(r["owner"])))))
        if check_only:
            log("SUMMARY check-only · admin %s · office %s"
                % ("exists" if existing else "would be created",
                   "assigned" if assigned else (office["id"] if office else "NOT LISTED")))
            return 0 if (assigned or office) else 3

        if not existing:
            _fill(page, login)
        if office and not assigned:
            if not _bring_row_on_screen(page, office["id"], log=log) \
                    or not _tick_not_assigned_row(page, office["id"]):
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
    if verify and (created or not existing or force_verify):
        verified = verify_login(login, log=log, headed=headed)
    dm_sent = False
    if dm and assigned and verified is not False:
        dm_sent = _dm_icd(owner, login, slack_id, log=log)
    if dm_sent:
        note = (note + " · " if note else "") + "DM'd the ICD"
    _record(owner, office_key, login, office, assigned, verified, note, log=log)
    # ONE DM, when the login is first made. From Lucy Reports' session the
    # Already Assigned grid also hides offices outside its own set, so an admin
    # Megan assigned by hand still reads 'NOT LISTED' here — the sign-in proof
    # (verify_login) is the real check for an existing admin, not another DM.
    if not office and created:
        _tell_operator(
            ":warning: *AppStream login for %s* — `%s` exists but the office could "
            "not be assigned: either %s isn't in our call center, or your login "
            "doesn't have access to it. Please check and assign it manually, or "
            "request access." % (owner, login["username"], owner), log=log)
    log("SUMMARY %s · %s · office %s%s%s"
        % ("created" if created else "exists", login["username"],
           ("%s assigned" % office["id"]) if assigned else "NOT LISTED (Megan told)",
           "" if verified is None else (" · login verified" if verified else " · LOGIN FAILED"),
           " · DM sent to the ICD" if dm_sent else (" · no DM (no Slack id)" if dm and assigned else "")))
    if verified is True:
        return 0
    if not office:
        return 3
    if verified is False:
        return 5
    return 0


def office_from_registry(key: str) -> Dict:
    """owner + office id for an ECO key, off office_metrics/onboarded_offices.json
    (the row the metrics dry run already needs). {} when the key is unknown."""
    reg = Path(__file__).resolve().parents[1] / "office_metrics" / "onboarded_offices.json"
    try:
        rows = json.loads(reg.read_text())
    except (OSError, ValueError):
        return {}
    for r in rows if isinstance(rows, list) else []:
        if str(r.get("key", "")).strip().lower() == key.strip().lower():
            return {"owner": str(r.get("owner") or "").strip(),
                    "office_id": str(r.get("ov_account") or "").strip()}
    return {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("owner", nargs="?", default="",
                    help="the owner's name, e.g. \"Nigel Marshall\" (or use --key)")
    ap.add_argument("--key", default="",
                    help="their ECO key, e.g. nigel — owner + office id come from "
                         "office_metrics/onboarded_offices.json (the dry-run row)")
    ap.add_argument("--office-id", help="their AppStream/OwnerVille office id, "
                                        "when the name alone is ambiguous")
    ap.add_argument("--office-key", default="", help="their ECO key (defaults to first name)")
    ap.add_argument("--check", action="store_true", help="read-only: say what would happen")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip signing in as the new login afterwards")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--dump-offices", action="store_true",
                    help="with --check: write every office the form offers to the log")
    ap.add_argument("--slack-id", default="", help="the ICD's Slack id for the DM "
                                                   "(else owner-slack-ids.md / ICD Signup)")
    ap.add_argument("--no-dm", action="store_true", help="do not DM the ICD")
    ap.add_argument("--local", action="store_true",
                    help="run on THIS Mac as YOUR AppStream login (a window opens; "
                         "sign in once, the profile keeps it)")
    ap.add_argument("--verify", action="store_true",
                    help="sign in as the login even when it already existed "
                         "(after somebody assigned the office by hand)")
    a = ap.parse_args(argv)
    if a.key:
        reg = office_from_registry(a.key)
        if not reg.get("owner"):
            print("no office with key %r in office_metrics/onboarded_offices.json — "
                  "wire the metrics row first, or pass the owner's name" % a.key)
            return 2
        a.owner = a.owner or reg["owner"]
        a.office_id = a.office_id or reg["office_id"]
        a.office_key = a.office_key or a.key
    if not a.owner:
        print("need the owner's name or --key <eco key>")
        return 2
    return provision(a.owner, office_id=a.office_id, office_key=a.office_key,
                     check_only=a.check, verify=not a.no_verify, headed=a.headed,
                     dump_offices=a.dump_offices, force_verify=a.verify,
                     slack_id=a.slack_id, dm=not a.no_dm, local=a.local)


if __name__ == "__main__":
    sys.exit(main())
