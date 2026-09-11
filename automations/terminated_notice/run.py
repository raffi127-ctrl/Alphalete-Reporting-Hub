"""Someone new on the Terminated ICDs tab -> a removal checklist in Slack.

WHY: logging a shut-down ICD is easy (one row on the 'Terminated ICDs' tab of
the AUTOMATION MASTER, which anyone can add from the browser). Knowing where
that person is still wired in is not — it was eleven places for Eric Martinez
on 2026-09-10, spread over three workbooks and eight repo files, and Megan and
Eve had no way to see that list without someone going and looking. So: when a
NAME APPEARS on that tab that this watcher hasn't announced yet, it goes and
looks, and posts what it found to #claudecorrections-and-requests.

WHAT IT IS NOT: it does not remove anything. The terminated list flags, it never
deletes (see terminated_icds' POLICY) — every line of the checklist is for a
person, and the post says plainly what was already handled and what is being
left alone on purpose.

ONE POST PER NAME, EVER. State lives in output/terminated_notice/announced.json.
A name posts the day it appears and never again, because the second copy of a
to-do list is how a channel stops being read. `--again <name>` re-posts one on
purpose.

CHEAP WHEN THERE'S NOTHING NEW: the common pass is ONE Sheet read of the
terminated tab. The workbook scan (which is slow — a few minutes) only happens
when there is actually a new name to scan for.

WHERE IT RUNS: the mini, like everything else that speaks in that channel — the
post has to come from Lucy. From a laptop it prints the checklist and refuses to
post, the same guard knocks_access_watch uses.

  python -m automations.terminated_notice.run --dry-run     # show, post nothing
  python -m automations.terminated_notice.run --post        # the scheduled pass
  python -m automations.terminated_notice.run --again "Eric Martinez"
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import platform
import sys
from pathlib import Path
from typing import Dict, List, Optional

from automations.terminated_notice import surfaces as S

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "terminated_notice"
STATE_PATH = OUT_DIR / "announced.json"

CHANNEL = "C0BK5PRG259"          # #claudecorrections-and-requests


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------

def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — no file = nothing announced yet
        return {}


def save_state(state: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1, sort_keys=True),
                          encoding="utf-8")


def _key(name: str) -> str:
    return " ".join((name or "").strip().lower().split())


# --------------------------------------------------------------------------
# name variants
# --------------------------------------------------------------------------

def name_candidates(name: str) -> List[str]:
    """The spellings to look for: the logged name plus every alias that
    resolves to it. A tab can be titled 'Kim Rodriguez' while the termination
    was logged as 'Kimberly Rodriguez' — miss that and the checklist quietly
    comes back short, which is worse than not running at all.

    CASE VARIANTS ARE KEPT, not folded away: the code scan lowercases both
    sides, but a Sheets `findall` is an exact match, so 'KIMBERLY RODRIGUEZ'
    and 'Kimberly Rodriguez' are two different searches. Dedupe is therefore
    exact, not case-insensitive.

    Best-effort: if the alias sheet won't load we still search the one name."""
    out = [name]
    try:
        from automations.focus_office_att import aliases as al
        raw = al.load_aliases()
        for cand in al.get_search_candidates(name, raw):
            if cand not in out:
                out.append(cand)
    except Exception as e:  # noqa: BLE001 — a wider search is a bonus, not a need
        print(f"  (alias lookup skipped: {type(e).__name__})", flush=True)
    return out


# --------------------------------------------------------------------------
# scanning
# --------------------------------------------------------------------------

def strip_comments(text: str) -> str:
    """Drop `#` comments from a Python source line, leaving code.

    WHY THIS EXISTS: taking someone off a roster leaves a comment BEHIND that
    names them — 'Kimberly Rodriguez (kimberlyatt458@gmail.com) sacada el
    2026-09-09: su oficina cerró'. That note is the whole reason nobody re-adds
    her, so it must stay; but a plain substring search then reads the file as
    if she were still listed and nags forever about work already done.

    Only a `#` with an even number of quote characters before it starts a
    comment, so a name on a line like `"Rashad Reed",  # Elevate…` survives
    while `"#alphalete-sales"` isn't truncated."""
    out = []
    for line in text.splitlines():
        cut = None
        for i, ch in enumerate(line):
            if ch == "#" and (line[:i].count('"') % 2 == 0
                              and line[:i].count("'") % 2 == 0):
                cut = i
                break
        out.append(line if cut is None else line[:cut])
    return "\n".join(out)


def scan_code(cands: List[str]) -> List[dict]:
    """Which repo rosters still mention any of `cands`. Plain substring search,
    case-insensitive — these are literal name lists, not structured data, and a
    parser per file format would be five parsers that each rot separately.

    Two things stop it crying wolf: comments are stripped from .py files (see
    strip_comments), and a surface can declare its own `resolved` check for
    files where 'already handled' doesn't mean 'the name is gone'."""
    hits = []
    needles = [_key(c) for c in cands if c.strip()]
    for surf in S.code_surfaces():
        p = REPO_ROOT / surf.path
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — a moved file is not a reason to fail
            continue
        body = (strip_comments(raw) if p.suffix == ".py" else raw).lower()
        if not any(c and c in body for c in needles):
            continue
        if surf.resolved is not None:
            try:
                if surf.resolved(raw, cands):
                    continue
            except Exception:  # noqa: BLE001 — a broken check means "still to do"
                pass
        hits.append({"label": surf.label, "path": surf.path, "fix": surf.fix})
    return hits


def scan_sheets(cands: List[str], logfn=print) -> List[dict]:
    """Which workbooks still carry the ICD — a tab of their own, or rows inside
    a shared tab. Slow (a few API calls per workbook), which is exactly why the
    caller only runs it for a name it has never announced."""
    from automations.recruiting_report import fill as rfill

    hits: List[dict] = []
    keys = {_key(c) for c in cands if c.strip()}
    try:
        client = rfill._client()
    except Exception as e:  # noqa: BLE001
        logfn(f"  ! Sheets unavailable, skipping the workbook scan ({e})")
        return hits

    for surf in S.sheet_surfaces():
        try:
            sh = client.open_by_key(surf.workbook_id)
        except Exception as e:  # noqa: BLE001 — one unreadable book, keep going
            logfn(f"  ! {surf.label}: {type(e).__name__} — skipped")
            hits.append({"label": surf.label, "where": "could not be read",
                         "fix": "check this one by hand", "unchecked": True})
            continue

        if isinstance(surf, S.SheetTab):
            # An ALREADY-HIDDEN tab is the finished state, not an open item.
            open_tabs = [ws for ws in sh.worksheets()
                         if _key(ws.title) in keys
                         and not ws._properties.get("hidden")]
            if not open_tabs:
                continue
            # DO IT, don't ask (Megan, 2026-09-10: "do all of these that you
            # safely can"). Hiding is reversible and never loses a cell — the
            # rows stay exactly where they are and stay readable; it is only
            # the report's signal to skip the tab. Asking a person to click
            # 'hide' on a tab we already found is the kind of item that made
            # the first checklists too long to act on.
            titles = [ws.title for ws in open_tabs]
            try:
                sh.batch_update({"requests": [
                    {"updateSheetProperties": {
                        "properties": {"sheetId": ws.id, "hidden": True},
                        "fields": "hidden"}}
                    for ws in open_tabs]})
                hits.append({"label": surf.label, "done": True,
                             "where": "tab " + ", ".join(f"'{x}'" for x in titles),
                             "fix": "hidden (rows untouched)",
                             "note": surf.hiding_is_not_enough})
                logfn(f"  hid {len(titles)} tab(s) in {surf.label}")
            except Exception as e:  # noqa: BLE001 — report it, never crash
                hits.append({"label": surf.label,
                             "where": "tab " + ", ".join(f"'{x}'" for x in titles),
                             "fix": "hide the tab (don't delete — the data "
                                    "stays); the automatic hide failed here",
                             "note": surf.hiding_is_not_enough})
                logfn(f"  ! could not hide in {surf.label}: {e}")
            continue

        # SheetCells — search the LIVE tabs only.
        where, kept = [], []
        for ws in sh.worksheets():
            if surf.tabs and ws.title not in surf.tabs:
                continue
            cells = []
            for cand in cands:
                try:
                    cells += list(ws.findall(cand))
                except Exception:  # noqa: BLE001
                    pass
            if cells and ws.title in surf.hidden_row_is_done:
                hidden = _hidden_rows(sh, ws.title, {c.row for c in cells})
                cells = [c for c in cells if c.row not in hidden]
            if cells and ws.title in surf.keep_while_paid:
                paid = _paid_rows(sh, ws.title, {c.row for c in cells})
                if paid is None:        # couldn't read it -> a person checks
                    found = sorted({c.address for c in cells})
                    where.append(f"'{ws.title}' {', '.join(found[:8])} (only "
                                 "once their row is at $0)")
                    continue
                for c in cells:
                    if c.row in paid:
                        kept.append(f"'{ws.title}' {c.address} ({paid[c.row]})")
                cells = [c for c in cells if c.row not in paid]
            found = [c.address for c in cells]
            if found:
                where.append(f"'{ws.title}' {', '.join(sorted(set(found))[:8])}")
        if where:
            hits.append({"label": surf.label, "where": " · ".join(where),
                         "fix": surf.fix})
        if kept:
            hits.append({"label": surf.label, "kept": True,
                         "where": " · ".join(sorted(set(kept))),
                         "fix": "stays while it still shows revenue — take it "
                                "off once it's at $0"})
    return hits


def _money(text: str) -> Optional[float]:
    """'$1,175' -> 1175.0, '-$20' -> -20.0; anything not a $ amount -> None."""
    t = str(text or "").strip().replace(",", "").replace(" ", "")
    neg = t.startswith("-") or (t.startswith("(") and t.endswith(")"))
    t = t.strip("-()")
    if not t.startswith("$"):
        return None
    try:
        v = float(t[1:])
    except ValueError:
        return None
    return -v if neg else v


def _paid_rows(sh, title: str, rows) -> Optional[dict]:
    """{row: '$1,175'} for the rows of `title` with any non-zero $ cell.

    No column is assumed — every $ cell on the row counts, so a template that
    moves its money column still reads right. None on a read failure: the
    caller then lists the row as work with the $0 rule spelled out, rather
    than guess either way."""
    rows = sorted(rows)
    try:
        resp = sh.values_batch_get([f"'{title}'!A{r}:AZ{r}" for r in rows])
    except Exception:  # noqa: BLE001
        return None
    out = {}
    for r, vr in zip(rows, resp.get("valueRanges", [])):
        vals = (vr.get("values") or [[]])[0]
        amounts = [m for m in (_money(v) for v in vals) if m]
        if amounts:
            top = max(amounts, key=abs)
            out[r] = f"${top:,.0f}"
    return out


def _hidden_rows(sh, title: str, rows) -> set:
    """1-based rows of `title` that are hidden (by hand or by a filter).

    Any failure returns an EMPTY set, so every cell stays on the list: 'I
    couldn't tell' has to read as 'still to do', never as done."""
    rows = sorted(rows)
    if not rows:
        return set()
    try:
        meta = sh.fetch_sheet_metadata(params={
            "ranges": [f"'{title}'!A{r}:A{r}" for r in rows],
            "includeGridData": True,
            "fields": "sheets(properties(title),data(startRow,"
                      "rowMetadata(hiddenByUser,hiddenByFilter)))"})
    except Exception:  # noqa: BLE001
        return set()
    out = set()
    for s in meta.get("sheets", []):
        if s.get("properties", {}).get("title") != title:
            continue
        for d in s.get("data", []):
            start = int(d.get("startRow") or 0)
            for i, m in enumerate(d.get("rowMetadata", [])):
                if m.get("hiddenByUser") or m.get("hiddenByFilter"):
                    out.add(start + i + 1)
    return out


def _letters(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalpha())


def scan_contacts(cands: List[str], logfn=print) -> Optional[dict]:
    """Is the ICD's contact card still in a contact group? READ-ONLY.

    A card matches on its display name, or — because some cards have no name
    at all (Melik El Jaiez's is just melikeljaiez@yahoo.com) — on an address
    whose local part spells the full name. Only USER groups count; 'My
    Contacts' / 'Starred' mail nobody.

    Returns a hit shaped like the sheet hits, or None when it can't tell (no
    token, API error, no card matched). None keeps the generic Contacts line
    in the post."""
    try:
        from googleapiclient.discovery import build
        from automations.shared import contacts_auth as ca
        svc = build("people", "v1", credentials=ca.load_credentials(),
                    cache_discovery=False)
        groups, tok = {}, None
        while True:
            r = svc.contactGroups().list(pageSize=200, pageToken=tok).execute()
            for g in r.get("contactGroups", []) or []:
                if g.get("groupType") == "USER_CONTACT_GROUP":
                    groups[g["resourceName"]] = (g.get("formattedName")
                                                 or g.get("name") or "")
            tok = r.get("nextPageToken")
            if not tok:
                break
        people, tok = [], None
        while True:
            r = svc.people().connections().list(
                resourceName="people/me", pageSize=1000, pageToken=tok,
                personFields="names,emailAddresses,memberships").execute()
            people += r.get("connections", []) or []
            tok = r.get("nextPageToken")
            if not tok:
                break
    except Exception as e:  # noqa: BLE001 — can't tell -> generic line stays
        logfn(f"  ! Contacts check skipped ({type(e).__name__})")
        return None

    names = {_key(c) for c in cands if c.strip()}
    spelled = {_letters(c) for c in cands if len(_letters(c)) >= 8}
    cards, in_groups = 0, []
    for p in people:
        shown = {_key(n.get("displayName")) for n in p.get("names", []) or []}
        locals_ = {_letters((e.get("value") or "").split("@")[0])
                   for e in p.get("emailAddresses", []) or []}
        if not (shown & names or any(s in l for s in spelled for l in locals_)):
            continue
        cards += 1
        for m in p.get("memberships", []) or []:
            rn = (m.get("contactGroupMembership") or {}).get(
                "contactGroupResourceName")
            if rn in groups and groups[rn] not in in_groups:
                in_groups.append(groups[rn])
    logfn(f"  contacts: {cards} card(s), groups: {in_groups or 'none'}")
    if not cards:
        return None
    if not in_groups:
        return {"label": "Google Contacts", "done": True,
                "where": "their card", "fix": "is in no contact group"}
    return {"label": "Google Contacts",
            "where": ", ".join(f"'{g}'" for g in in_groups),
            "fix": "take them out of the group (keep the card)"}


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def render(entry: dict, code_hits: List[dict], sheet_hits: List[dict]) -> str:
    """A checklist: ticked lines are finished, empty boxes are the work.

    Megan 2026-09-10: "exactly what was done/needs done in a checklist format
    to make it super simple". Every box is one concrete action in the place it
    happens — a workbook and a cell, a contact group — never a file path and
    never a sentence explaining why."""
    name = entry["name"]
    head = f":octagonal_sign: *{name} — terminated*"
    if entry.get("date"):
        head += f" {entry['date']}"
    lines = [head]

    done = [h for h in sheet_hits if h.get("done")]
    kept = [h for h in sheet_hits if h.get("kept")]
    todo = [h for h in sheet_hits if not h.get("done") and not h.get("kept")]

    ticked = [f":white_check_mark: {h['label']} — {h['where']} {h['fix']}"
              for h in done]
    if code_hits:
        ticked.append(":white_check_mark: Code rosters — cleared ("
                      + ", ".join(h["label"] for h in code_hits) + ")")
    if ticked:
        lines += ["", "*Done*"] + ticked

    boxes = [f":black_square_button: *{h['label']}* — {h['where']}: {h['fix']}"
             + (f" ({h['note']})" if h.get("note") else "")
             for h in todo]
    # An Always line gives way to a real answer for the same surface.
    checked = {h["label"] for h in sheet_hits}
    boxes += [f":black_square_button: *{a.label}* — {a.fix}"
              for a in S.always_surfaces() if a.label not in checked]
    lines += ["", "*To do*"] + boxes

    for la in S.LEAVE_ALONE:
        lines += ["", f"_Leave alone: {la.label} — {la.why}_"]
    for h in kept:
        lines += ["", f"_Leave alone: {h['label']} — {h['where']} "
                      f"{h['fix']}_"]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# posting
# --------------------------------------------------------------------------

def post(text: str, *, dry_run: bool, logfn=print) -> bool:
    """Post to the corrections channel. Refuses from Windows for the reason
    knocks_access_watch documents: that machine's Slack token is a person's
    account, and everything in this channel has to read as Lucy. It also
    refuses when the token on THIS machine isn't Lucy — a checklist signed by
    Megan looks like Megan asking someone else to do it."""
    if dry_run:
        logfn("\n--- would post to #claudecorrections-and-requests ----")
        logfn(text)
        logfn("-----------------------------------------------------")
        return True
    if platform.system() == "Windows":
        logfn("\n! not posting from Windows (the token here is a person, not "
              "Lucy). Run it on the mini:")
        logfn("  lucy rerun terminated_notice --machine \"Lucy 1\"")
        logfn(text)
        return False
    from automations.shared import slack_metrics_post as smp
    who = ""
    try:
        who = smp._client().auth_test().get("user", "")
    except Exception:  # noqa: BLE001
        pass
    if who and "lucy" not in who.lower():
        logfn(f"\n! this machine posts as {who}, not Lucy — not posting. "
              "Queue it on the mini:")
        logfn("  lucy rerun terminated_notice --machine \"Lucy 1\"")
        logfn(text)
        return False
    smp._client().chat_postMessage(channel=CHANNEL, text=text)
    logfn("  ✓ posted to #claudecorrections-and-requests")
    return True


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def announce(entry: dict, *, dry_run: bool, logfn=print) -> Optional[str]:
    """Scan for one ICD and post their checklist. Returns the text posted, or
    None if the post didn't go out."""
    name = entry["name"]
    logfn(f"\n{name} — looking for where they're still wired in")
    cands = name_candidates(name)
    if len(cands) > 1:
        logfn("  also searching: " + ", ".join(cands[1:]))
    code_hits = scan_code(cands)
    logfn(f"  code rosters: {len(code_hits)}")
    sheet_hits = scan_sheets(cands, logfn=logfn)
    logfn(f"  workbooks: {len(sheet_hits)}")
    if any(a.check == "contacts" for a in S.always_surfaces()):
        contact = scan_contacts(cands, logfn=logfn)
        if contact:
            sheet_hits.append(contact)
    text = render(entry, code_hits, sheet_hits)
    return text if post(text, dry_run=dry_run, logfn=logfn) else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--post", action="store_true",
                    help="post to Slack (the scheduled pass)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the checklist, post nothing, save no state")
    ap.add_argument("--again", metavar="NAME",
                    help="re-post one ICD's checklist even though it already "
                         "went out")
    a = ap.parse_args(argv)
    dry = a.dry_run or not a.post

    from automations.shared import terminated_icds as ti
    try:
        logged = ti.load_terminated()
    except Exception as e:  # noqa: BLE001
        print(f"couldn't read the Terminated ICDs tab: {e}")
        return 1
    print(f"{len(logged)} ICD(s) on the terminated list")

    state = load_state()
    if a.again:
        want = _key(a.again)
        todo = [e for e in logged if _key(e["name"]) == want]
        if not todo:
            print(f"'{a.again}' isn't on the terminated list — nothing to "
                  "re-post. Names on it: "
                  + ", ".join(e["name"] for e in logged))
            return 1
    else:
        todo = [e for e in logged if _key(e["name"]) not in state]
        # FIRST RUN IS A NO-OP, ON PURPOSE. Without this, standing up the
        # watcher would post a checklist for every ICD terminated months ago —
        # seven of them on 2026-09-10, all long since cleaned up. The list is
        # recorded as already-announced instead, so the next NEW name is the
        # first one anyone hears about.
        if not state and todo:
            print(f"first run — recording the {len(todo)} name(s) already on "
                  "the list as announced, posting nothing")
            if not dry:
                stamp = dt.datetime.now().isoformat(timespec="seconds")
                save_state({_key(e["name"]): {"name": e["name"],
                                              "announced_at": stamp,
                                              "posted": False,
                                              "reason": "already on the list "
                                                        "when the watcher "
                                                        "started"}
                            for e in logged})
            return 0

    if not todo:
        print("nothing new — no post")
        return 0

    for entry in todo:
        text = announce(entry, dry_run=dry)
        if dry or text is None:
            continue
        state[_key(entry["name"])] = {
            "name": entry["name"],
            "announced_at": dt.datetime.now().isoformat(timespec="seconds"),
            "posted": True,
        }
        save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
