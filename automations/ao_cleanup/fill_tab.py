"""Write the 'AO Workspace Cleanup' tab: one row per person PER channel.

Inputs, all on disk by the time this runs:
  * output/ao_channel_members.json  — who is in each channel
    (automations.ao_cleanup.channel_members)
  * output/ao_slack_users.json      — id -> name / email (automations.ao_cleanup.names)
  * the 'Terminated Reps' tab       — cross-reference only: it does NOT decide
    who is listed, it only flags "this person was let go on <date> and is still
    sitting in the channel".

THE TAB'S LAYOUT IS EVE'S, NOT OURS. She reorders and renames columns, colours
the Channel column and edits the dropdown by hand (she added
`alphaletesocialmedia` on 2026-09-10). So:

  * columns are found BY HEADER LABEL and written one range at a time — a
    column we don't recognise is never touched;
  * the header row is left exactly as she typed it;
  * no background colour, banding or column width is ever written, so her
    formatting survives a rebuild;
  * the Channel dropdown is READ from the sheet (for the channel order) and
    NEVER written back. Its per-value chip colours are hers and the Sheets API
    does not return them, so any setDataValidation on that column wipes them.

Notes are written in ENGLISH (Eve, 2026-09-10) because Rafael reads them.

    python -m automations.ao_cleanup.fill_tab --dry-run
    python -m automations.ao_cleanup.fill_tab --tab "AO Cleanup SANDBOX"
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import argparse
import collections
import datetime as dt
import json
import re
import sys
import unicodedata
from typing import Dict, List

from automations.ao_cleanup import names as names_mod
from automations.ao_cleanup.build_cleanup_tab import (
    WORKBOOK_KEY, TARGET_TAB, _norm_name, read_terminated)
from automations.ao_cleanup.channel_members import CACHE_PATH as MEMBERS_PATH
from automations.ao_cleanup.channel_members import CHANNELS
from automations.brand_audit.sheets import client
from automations.terminated_reps import board as sales_board

FIRST_DATA_ROW = 2

# Header label -> the key build_rows() puts in each person dict. Anything on the
# tab that isn't listed here (or in CHECKBOX_LABELS) is left untouched.
COLUMNS = [
    ("Rep Name", "name"),
    ("Channel", "channel"),
    ("Notes", "notes"),
    ("Email (Slack)", "email"),
    ("Slack User", "username"),
    ("Slack ID", "uid"),
    ("Active in Slack", "active"),      # Yes = account not deactivated
    ("Joined Channel", "joined"),       # from the history replay; blank if unseen
]
CHECKBOX_LABELS = ("Remove from channel", "Remove from AO")
CHANNEL_LABEL = "Channel"


def _col_letter(idx0):
    """0 -> A. The tab is nowhere near column Z, but be correct anyway."""
    s, n = "", idx0 + 1
    while n:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def _key(name):
    """Loose name key for the Terminated Reps cross-reference."""
    return re.sub(r"[^a-z ]", "", _norm_name(name).lower()).strip()


ACTIVE_PREFIX = "ACTIVE on "      # + the week tab: "ACTIVE on Sales Board WE 9.20"


def _fold(name):
    """Name key for the Sales Board match: the board's '(Wk 2)' and nickname
    parentheses dropped, accents folded, letters only."""
    s = unicodedata.normalize("NFKD", sales_board.base_name(name))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z ]", " ", s).split())


def active_index(names):
    """Sales Board names -> (full keys, (first, last) pairs).

    The pair catches the middle names one side carries and the other doesn't:
    'Justin G Carlos Avila' in Slack is 'Justin Avila' on the board.
    """
    full, ends = set(), set()
    for n in names:
        k = _fold(n)
        if not k:
            continue
        full.add(k)
        p = k.split()
        if len(p) >= 2:
            ends.add((p[0], p[-1]))
    return full, ends


def is_active(name, index):
    full, ends = index
    k = _fold(name)
    if not k:
        return False
    p = k.split()
    return k in full or (len(p) >= 2 and (p[0], p[-1]) in ends)


def read_active(logfn=print):
    """(index, week tab title) of who the CURRENT Sales Board week says is
    working — no Termination Date, no T mark (terminated_reps.board). A board
    that can't be read costs the note, never the tab: -> (None, "")."""
    try:
        m = sales_board.marked_names(dt.date.today(), logfn=lambda *_: None)
    except Exception as exc:                      # noqa: BLE001
        logfn("aviso: sin Sales Board (%s: %s) - no sale la nota ACTIVE"
              % (type(exc).__name__, str(exc)[:90]))
        return None, ""
    return active_index(m.active), m.title


def _terminated_index(sh):
    # type: (...) -> Dict[str, dict]
    out = {}
    for r in read_terminated(sh):
        k = _key(r["name"])
        if not k:
            continue
        prev = out.get(k)
        if prev is None or (r["term"] and (not prev["term"] or r["term"] > prev["term"])):
            out[k] = r
    return out


def _duplicate_names(members, users, channels):
    """Real names carried by more than ONE Slack account.

    This is the "snuck in under another email or nickname" case: same person,
    second account, so removing one leaves the other in the channel.
    """
    seen = collections.defaultdict(set)
    for chan in channels:
        info = members.get("channels", {}).get(chan) or {}
        for uid in info.get("members_api", []) or []:
            name = ((users.get(uid) or {}).get("name") or "").strip().lower()
            if name:
                seen[name].add(uid)
    return {n: ids for n, ids in seen.items() if len(ids) > 1}


def build_rows(members, users, terminated, channel_order, active=None,
               active_tab=""):
    # type: (dict, dict, dict, List[str], object, str) -> List[dict]
    dupes = _duplicate_names(members, users, channel_order)
    rows = []
    for chan in channel_order:
        info = members.get("channels", {}).get(chan)
        if not info:
            continue                       # channel not scanned yet
        joined = info.get("joined", {})
        spoke = set(info.get("spoke", []) or [])
        # `members_api` is conversations.members — the real list. The join/leave
        # replay under `members` is only a fallback: it overcounts badly,
        # because Slack stopped recording joins in the busiest channel.
        roster = info.get("members_api")
        if roster is None:
            roster = list(info.get("members", [])) + list(info.get("no_join_event", []))

        people = []
        for uid in roster:
            u = users.get(uid) or {}
            people.append(((u.get("name") or "").lower(), u.get("name") or "", uid, u))
        people.sort(key=lambda p: (p[1] == "", p[0], p[2]))

        for _, name, uid, u in people:
            term = terminated.get(_key(name)) if name else None
            notes = []
            # FIRST, so the whole block can be filtered out in one go: someone
            # still selling this week is not a removal (Eve, 2026-09-15).
            if active and name and is_active(name, active):
                notes.append(ACTIVE_PREFIX + active_tab)
            if term:
                notes.append("Terminated %s (%s)" % (
                    term["term"].strftime("%m/%d/%Y") if term["term"]
                    else term["term_raw"] or "no date", term["lead"] or "?"))
            dup = dupes.get(name.strip().lower())
            if dup:
                notes.append("%d Slack accounts under this name" % len(dup))
            if u.get("external"):
                # Slack Connect: they belong to ANOTHER workspace, so "Remove
                # from AO" means nothing for them — only the channel applies.
                notes.append("EXTERNAL - another workspace, not in AO")
            if u.get("deleted"):
                notes.append("Slack account already deactivated")
            if u.get("bot"):
                notes.append("Bot / app")
            if u.get("restricted"):
                notes.append("Guest account")
            if uid not in spoke:
                notes.append("Never posted here")
            ts = joined.get(uid)
            joined_on = (dt.datetime.fromtimestamp(float(ts)).strftime("%m/%d/%Y")
                         if ts else "")
            if joined_on:
                notes.append("Joined %s" % joined_on)
            if not name:
                notes.append("Name unresolved")
            rows.append({
                "name": name or uid,
                "channel": chan,
                "notes": " | ".join(notes),
                "email": u.get("email", ""),
                "username": u.get("username", ""),
                "uid": uid,
                # blank, not "Yes", when Slack never told us about the account
                "active": ("No" if u.get("deleted") else "Yes") if u else "",
                "joined": joined_on,
            })
    return rows


def existing_ticks(ws, index):
    """{(slack id, channel): [remove_from_channel, remove_from_AO]} as the tab
    stands right now.

    A monthly rebuild must NOT throw away Rafael's decisions. Rows are matched
    on the Slack ID, not the name: a person can be renamed, and two people can
    share a name (11 of them do). Somebody who has left every channel since the
    last run simply has no row to carry the tick to — that is fine, the tick
    was about a person who is already gone.
    """
    if "Slack ID" not in index or "Channel" not in index:
        return {}
    last = _col_letter(max(index.values()))
    out = {}
    for row in ws.get_values("A%d:%s%d" % (FIRST_DATA_ROW, last, ws.row_count)):
        def cell(label):
            i = index.get(label)
            return row[i].strip() if i is not None and i < len(row) else ""
        uid, chan = cell("Slack ID"), cell("Channel")
        if not uid or not chan:
            continue
        out[(uid, chan)] = [cell(CHECKBOX_LABELS[0]).upper() == "TRUE",
                            cell(CHECKBOX_LABELS[1]).upper() == "TRUE"]
    return out


def read_layout(ws):
    """-> (header row, {label: 0-based column}). The tab describes itself."""
    header = ws.row_values(1)
    index = {}
    for i, label in enumerate(header):
        label = (label or "").strip()
        if label and label not in index:
            index[label] = i
    return header, index


def read_channel_rule(gc, sh, ws):
    """The Channel dropdown exactly as Eve left it — including any value she
    added by hand. None if the column has no dropdown."""
    resp = gc.http_client.request(
        "get", "https://sheets.googleapis.com/v4/spreadsheets/%s" % sh.id,
        params={"ranges": "%s!A%d:Z%d" % (ws.title, FIRST_DATA_ROW, FIRST_DATA_ROW),
                "fields": "sheets(data(rowData(values(dataValidation))))"}).json()
    try:
        values = resp["sheets"][0]["data"][0]["rowData"][0]["values"]
    except (KeyError, IndexError):
        return None
    for cell in values:
        dv = cell.get("dataValidation") or {}
        if (dv.get("condition") or {}).get("type") == "ONE_OF_LIST":
            return dv
    return None


def dropdown_extent(gc, sh, ws, col_idx):
    """Last row that already carries the Channel dropdown (0 if none).

    Rows at or above it inherit Eve's chips for free — we write a value into
    the cell and the chip stays. Only rows PAST it would come out bare.
    """
    col = _col_letter(col_idx)
    resp = gc.http_client.request(
        "get", "https://sheets.googleapis.com/v4/spreadsheets/%s" % sh.id,
        params={"ranges": "%s!%s1:%s%d" % (ws.title, col, col, ws.row_count),
                "fields": "sheets(data(rowData(values("
                          "dataValidation(condition(type))))))"}).json()
    try:
        rows = resp["sheets"][0]["data"][0].get("rowData", [])
    except (KeyError, IndexError):
        return 0
    last = 0
    for i, row in enumerate(rows, 1):
        vals = row.get("values") or []
        if vals and ((vals[0].get("dataValidation") or {})
                     .get("condition", {}).get("type") == "ONE_OF_LIST"):
            last = i
    return last


def extend_dropdown(sh, ws, col_idx, have_row, need_row):
    """Carry the dropdown down to `need_row` by COPYING a cell that has it.

    copyPaste with PASTE_DATA_VALIDATION duplicates the cell's rule as the
    server holds it, chips and all. setDataValidation cannot: the colours never
    come back from the API, so re-writing the rule wipes them
    (see the note in write_tab). Only called when the sheet actually runs out
    of dropdown — with ~1.700 spare rows as of 2026-09-10, that is years away.
    """
    return {"copyPaste": {
        "source": {"sheetId": ws.id, "startRowIndex": FIRST_DATA_ROW - 1,
                   "endRowIndex": FIRST_DATA_ROW,
                   "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
        "destination": {"sheetId": ws.id, "startRowIndex": have_row,
                        "endRowIndex": need_row,
                        "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
        "pasteType": "PASTE_DATA_VALIDATION"}}


def channel_order(rule, fallback):
    """Dropdown order = tab order, so the sheet reads like the dropdown."""
    if not rule:
        return list(fallback)
    vals = [v.get("userEnteredValue", "")
            for v in (rule.get("condition") or {}).get("values", [])]
    return [v for v in vals if v] or list(fallback)


def write_tab(gc, sh, ws, rows, index, rule, ticks=None):  # noqa: C901
    """Write only the columns we recognise, one range each. Never row 1, never
    a format, never a colour."""
    ticks = ticks or {}
    needed = FIRST_DATA_ROW + len(rows) - 1
    if ws.row_count < needed:
        ws.add_rows(needed - ws.row_count)

    data = []
    for label, key in COLUMNS:
        if label not in index:
            continue
        col = _col_letter(index[label])
        data.append({"range": "%s!%s%d:%s%d" % (ws.title, col, FIRST_DATA_ROW,
                                                col, needed),
                     "values": [[r[key]] for r in rows]})
    for n, label in enumerate(CHECKBOX_LABELS):
        if label not in index:
            continue
        col = _col_letter(index[label])
        data.append({"range": "%s!%s%d:%s%d" % (ws.title, col, FIRST_DATA_ROW,
                                                col, needed),
                     "values": [[ticks.get((r["uid"], r["channel"]),
                                           (False, False))[n]] for r in rows]})
    sh.values_batch_update({"valueInputOption": "USER_ENTERED", "data": data})

    # Clear leftovers below, VALUES only — formatting and banding stay put.
    if ws.row_count > needed:
        last = _col_letter(max(index.values()))
        ws.batch_clear(["A%d:%s%d" % (needed + 1, last, ws.row_count)])

    requests = []
    for label in CHECKBOX_LABELS:
        if label not in index:
            continue
        requests.append({"setDataValidation": {
            "range": {"sheetId": ws.id, "startRowIndex": FIRST_DATA_ROW - 1,
                      "endRowIndex": needed,
                      "startColumnIndex": index[label],
                      "endColumnIndex": index[label] + 1},
            "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}}})
    # NEVER setDataValidation on the Channel column. Eve gave each dropdown
    # value its own chip colour, and those colours are NOT in what the Sheets
    # v4 API hands back (no conditionalFormats, nothing in dataValidation) — so
    # re-applying the rule we just read silently resets every chip to grey. It
    # cost her the colours twice on 2026-09-10. Rows that already have the
    # dropdown keep it when we write a value into them, so the normal monthly
    # rerun touches nothing. Only if the list outgrows the dropdown do we
    # extend it, and then by COPYING a cell that has it.
    if CHANNEL_LABEL in index:
        col = index[CHANNEL_LABEL]
        have = dropdown_extent(gc, sh, ws, col)
        if have < needed:
            print("desplegable llegaba a la fila %d, hace falta hasta la %d "
                  "-> se copia (no se re-escribe)" % (have, needed))
            requests.append(extend_dropdown(sh, ws, col, max(have, FIRST_DATA_ROW),
                                            needed))
    if requests:
        sh.batch_update({"requests": requests})
    return needed


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fill the AO cleanup tab")
    ap.add_argument("--tab", default=TARGET_TAB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--channel", action="append", default=[],
                    help="only these channels (repeatable)")
    args = ap.parse_args(argv)

    if not MEMBERS_PATH.exists():
        print("Falta %s — corre primero:\n"
              "    python -m automations.ao_cleanup.channel_members"
              % MEMBERS_PATH, file=sys.stderr)
        return 2
    members = json.loads(MEMBERS_PATH.read_text(encoding="utf-8"))
    users = names_mod.load()

    gc = client()
    sh = gc.open_by_key(WORKBOOK_KEY)
    ws = sh.worksheet(args.tab)
    header, index = read_layout(ws)
    rule = read_channel_rule(gc, sh, ws)
    order = channel_order(rule, [n for n, _ in CHANNELS])

    missing = [c for c in order if c not in members.get("channels", {})]
    terminated = _terminated_index(sh)
    active, active_tab = read_active()
    rows = build_rows(members, users, terminated, order, active, active_tab)
    if args.channel:
        want = {c.lstrip("#").lower() for c in args.channel}
        rows = [r for r in rows if r["channel"].lower() in want]

    print("columnas de la tab : %s" % ", ".join(h for h in header if h))
    print("desplegable        : %s" % ", ".join(order))
    if missing:
        print("SIN ESCANEAR       : %s  (corre channel_members)" % ", ".join(missing))
    print("filas              : %d" % len(rows))
    print("con baja           : %d" % sum(1 for r in rows if "Terminated" in r["notes"]))
    print("activos Sales Board: %d  (%s)" % (
        sum(1 for r in rows if r["notes"].startswith(ACTIVE_PREFIX)),
        active_tab or "sin leer"))
    for chan in order:
        print("  %-30s %4d" % (chan, sum(1 for r in rows if r["channel"] == chan)))
    if args.dry_run:
        print("\n-- dry run --")
        for r in rows[:6]:
            print(r)
        return 0
    ticks = existing_ticks(ws, index)
    kept = sum(1 for r in rows if any(ticks.get((r["uid"], r["channel"]), (0, 0))))
    print("tildes de Rafael conservadas: %d" % kept)
    last = write_tab(gc, sh, ws, rows, index, rule, ticks)
    print("\nescrito hasta la fila %d en '%s'" % (last, ws.title))
    return 0


if __name__ == "__main__":
    sys.exit(main())
