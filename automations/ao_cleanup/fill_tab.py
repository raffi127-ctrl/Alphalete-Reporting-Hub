"""Write the 'AO Workspace Cleanup' tab: one row per person PER channel.

Inputs, all already on disk by the time this runs:
  * output/ao_channel_members.json  — who is in each of the 5 channels
    (automations.ao_cleanup.channel_members)
  * output/ao_slack_users.json      — id -> name / email (automations.ao_cleanup.names)
  * the 'Terminated Reps' tab       — cross-reference only: it does NOT decide
    who is listed, it only flags "this person was let go on <date> and is still
    sitting in the channel".

Rafael's two checkboxes stay exactly where Eve put them (C and D) and column B
keeps her dropdown, so the values written there are the dropdown's own strings.

    python -m automations.ao_cleanup.fill_tab --dry-run
    python -m automations.ao_cleanup.fill_tab --tab "AO Cleanup SANDBOX"
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Dict, List

from automations.ao_cleanup import names as names_mod
from automations.ao_cleanup.build_cleanup_tab import (
    WORKBOOK_KEY, TARGET_TAB, _norm_name, read_terminated)
from automations.ao_cleanup.channel_members import CACHE_PATH as MEMBERS_PATH
from automations.brand_audit.sheets import client

HEADERS = [
    "Rep Name", "Channel", "Remove from channel", "Remove from AO", "Notes",
    "Email (Slack)", "Usuario Slack", "Baja registrada", "Fecha de baja",
    "Entro al canal", "Escribio alguna vez", "Slack ID",
]
FIRST_DATA_ROW = 2
# Channel order = the dropdown's order, so the tab reads like the dropdown.
from automations.ao_cleanup.channel_members import CHANNELS  # noqa: E402
CHANNEL_ORDER = [n for n, _ in CHANNELS]


def _key(name):
    """Loose name key for the Terminated Reps cross-reference."""
    return re.sub(r"[^a-z ]", "", _norm_name(name).lower()).strip()


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


def _duplicate_names(members, users):
    """Real names carried by more than ONE Slack account across the 5 channels.

    This is the "se coló con otro email u otro nickname" case Eve is hunting:
    same person, second account, so a removal that only touches one of them
    leaves the other sitting in the channel.
    """
    import collections
    seen = collections.defaultdict(set)
    for info in members.get("channels", {}).values():
        for uid in info.get("members_api", []) or []:
            name = ((users.get(uid) or {}).get("name") or "").strip().lower()
            if name:
                seen[name].add(uid)
    return {n: ids for n, ids in seen.items() if len(ids) > 1}


def build_rows(members, users, terminated, today):
    # type: (dict, dict, dict, dt.date) -> List[list]
    dupes = _duplicate_names(members, users)
    rows = []
    for chan in CHANNEL_ORDER:
        info = members.get("channels", {}).get(chan)
        if not info:
            continue
        joined = info.get("joined", {})
        # `members_api` is conversations.members — the real list. The
        # join/leave replay under `members` is only a fallback for a channel
        # that has not been re-pulled since the read token existed; it
        # overcounts badly (it cannot see leaves it never recorded).
        roster = info.get("members_api")
        if roster is None:
            roster = list(info.get("members", [])) + list(info.get("no_join_event", []))
        people = []
        for uid in roster:
            u = users.get(uid) or {}
            people.append((u.get("name") or "", uid, uid in joined, u))
        # unresolved names sort last so Rafael isn't reading ids first
        people.sort(key=lambda p: (p[0] == "", p[0].lower(), p[1]))

        for name, uid, has_join, u in people:
            term = terminated.get(_key(name)) if name else None
            notes = []
            if u.get("deleted"):
                notes.append("cuenta ya desactivada en Slack")
            if u.get("bot"):
                notes.append("BOT / app")
            if u.get("restricted"):
                notes.append("invitado (guest de canal)")
            dup = dupes.get((name or "").strip().lower())
            if dup:
                notes.append("OJO: %d cuentas de Slack con este mismo nombre"
                             % len(dup))
            if u.get("external"):
                # Slack Connect: they belong to ANOTHER workspace, so "Remove
                # from AO" is meaningless for them — only the channel applies.
                notes.append("EXTERNO: es de otro workspace, no de AO")
            if not name:
                notes.append("nombre sin resolver - falta permiso users:read")
            if term:
                notes.append("baja el %s (%s)" % (
                    term["term"].strftime("%m/%d/%Y") if term["term"]
                    else term["term_raw"] or "sin fecha", term["lead"] or "?"))
            ts = joined.get(uid)
            rows.append([
                name or uid,
                chan,
                False,
                False,
                " | ".join(notes),
                u.get("email", ""),
                u.get("username", ""),
                "SI" if term else "",
                (term["term"].strftime("%m/%d/%Y") if term and term["term"]
                 else (term["term_raw"] if term else "")),
                (dt.datetime.fromtimestamp(float(ts)).strftime("%m/%d/%Y")
                 if ts else ""),
                "SI" if uid in set(members.get("channels", {})
                                   .get(chan, {}).get("spoke", [])) else "",
                uid,
            ])
    return rows


def _requests(sheet_id, last_row):
    """Checkboxes on C:D and the channel dropdown on B, for every data row."""
    rng = {"sheetId": sheet_id, "startRowIndex": FIRST_DATA_ROW - 1,
           "endRowIndex": last_row}
    return [
        {"setDataValidation": {
            "range": dict(rng, startColumnIndex=1, endColumnIndex=2),
            "rule": {"condition": {
                "type": "ONE_OF_LIST",
                "values": [{"userEnteredValue": c} for c in CHANNEL_ORDER]},
                "showCustomUi": True, "strict": False}}},
        {"setDataValidation": {
            "range": dict(rng, startColumnIndex=2, endColumnIndex=4),
            "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}}},
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id,
                           "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount"}},
    ]


def write_tab(sh, tab, rows):
    ws = sh.worksheet(tab)
    needed = FIRST_DATA_ROW + len(rows) - 1
    if ws.row_count < needed:
        ws.add_rows(needed - ws.row_count)
    end = chr(ord("A") + len(HEADERS) - 1)
    ws.update(values=[HEADERS], range_name="A1:%s1" % end,
              value_input_option="USER_ENTERED")
    ws.update(values=rows, range_name="A%d:%s%d" % (FIRST_DATA_ROW, end, needed),
              value_input_option="USER_ENTERED")
    if ws.row_count > needed:
        ws.batch_clear(["A%d:%s%d" % (needed + 1, end, ws.row_count)])
    sh.batch_update({"requests": _requests(ws.id, needed)})
    return needed


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fill the AO cleanup tab")
    ap.add_argument("--tab", default=TARGET_TAB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--channel", action="append", default=[],
                    help="only these channels (repeatable) - used while the "
                         "name cache only covers part of the workspace")
    args = ap.parse_args(argv)

    if not MEMBERS_PATH.exists():
        print("Falta %s — corre primero:\n"
              "    python -m automations.ao_cleanup.channel_members"
              % MEMBERS_PATH, file=sys.stderr)
        return 2
    members = json.loads(MEMBERS_PATH.read_text(encoding="utf-8"))
    users = names_mod.load()

    sh = client().open_by_key(WORKBOOK_KEY)
    terminated = _terminated_index(sh)
    rows = build_rows(members, users, terminated, dt.date.today())
    if args.channel:
        want = {c.lstrip("#").lower() for c in args.channel}
        rows = [r for r in rows if r[1].lower() in want]

    unresolved = sum(1 for r in rows if not r[5] and r[0] == r[11])
    flagged = sum(1 for r in rows if r[7] == "SI")
    print("filas            : %d" % len(rows))
    print("sin nombre       : %d" % unresolved)
    print("con baja marcada : %d" % flagged)
    for chan in CHANNEL_ORDER:
        print("  %-30s %4d" % (chan, sum(1 for r in rows if r[1] == chan)))
    if args.dry_run:
        print("\n-- dry run --")
        for r in rows[:8]:
            print(r)
        return 0
    last = write_tab(sh, args.tab, rows)
    print("\nescrito A1:L%d en '%s'" % (last, args.tab))
    return 0


if __name__ == "__main__":
    sys.exit(main())
