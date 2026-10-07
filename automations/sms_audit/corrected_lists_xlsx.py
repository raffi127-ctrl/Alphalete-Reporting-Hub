# -*- coding: utf-8 -*-
"""The never-reached lists, corrected once Email Tracking was pulled.

Megan 2026-09-28. The first version of these lists went to four teams
saying 208 people could not be reached. Email Tracking (p=792) then showed
128 of them WERE emailed and 89 OPENED the email. Only 15 had no contact of
any kind. A list that sends a team after 190 people who were already
reached buries the 15 who were not.

Two tabs per office, because they are two different jobs:
  Chase These        no text, no email, not on the call list. Real gaps.
  Bad Number         reached by email or phone, but every text failed.
                     Fix the number on the record; do not chase the person.
"""
from __future__ import annotations

import collections
import io
import json

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from automations.sms_audit.never_reached_xlsx import (
    OFFICES, OUTPUT, call_status, collect)

INK = Font(name="Georgia", size=12, bold=True, color="000000")
HEAD = Font(name="Georgia", size=12, bold=True, color="FFFFFF")
NOTE = Font(name="Georgia", size=10, italic=True, color="555555")
RED = PatternFill("solid", fgColor="8C3B2E")
BLUE = PatternFill("solid", fgColor="2F5D57")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
E = Side(style="thin", color="BFBDB6")
BOX = Border(left=E, right=E, top=E, bottom=E)
COLS = ["Applicant", "Phone", "Call List Status", "Emailed?", "Opened It?",
        "Texts Tried", "Why Texts Failed"]
W = [24, 15, 18, 12, 12, 11, 26]


def emails_by_phone():
    out = {}
    for office in OFFICES:
        book = collections.defaultdict(list)
        path = OUTPUT / "email_tracking_{}.json".format(office)
        if path.exists():
            for r in json.loads(path.read_text(encoding="utf-8")):
                digits = "".join(c for c in (r.get("phone") or "")
                                 if c.isdigit())[-10:]
                if digits:
                    book[digits].append(r)
        out[office] = book
    return out


def _sheet(wb, title, heading, blurb, rows, fill):
    ws = wb.create_sheet(title[:31])
    ws["A1"] = heading
    ws["A1"].font = Font(name="Georgia", size=14, bold=True)
    ws["A2"] = blurb
    ws["A2"].font = NOTE
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=2, start_column=1, end_row=3,
                   end_column=len(COLS))
    ws["A5"] = "{} {}".format(len(rows),
                              "person" if len(rows) == 1 else "people")
    ws["A5"].font = Font(name="Georgia", size=12, bold=True)
    for i, h in enumerate(COLS, 1):
        c = ws.cell(row=6, column=i, value=h)
        c.font, c.fill, c.alignment, c.border = HEAD, fill, CENTER, BOX
        ws.column_dimensions[get_column_letter(i)].width = W[i - 1]
    for r, row in enumerate(rows, start=7):
        for i, v in enumerate(row, 1):
            c = ws.cell(row=r, column=i, value=v)
            c.font, c.alignment, c.border = INK, CENTER, BOX
    ws.freeze_panes = "A7"
    ws.row_dimensions[2].height = 30
    return ws


def build():
    mail = emails_by_phone()
    data, _dropped = collect(call_status())
    made, tally = [], collections.OrderedDict()
    for office, label in OFFICES.items():
        chase, badnum = [], []
        for r in data[office]:
            hits = mail[office].get(r["phone"][-10:], [])
            opened = any((h.get("status") or "").lower().startswith("opened")
                         or (h.get("opened") or "").strip() for h in hits)
            status = r["status"] or "not on the call list"
            called = status.startswith("Left Message") or status in (
                "OPEN", "On Hold", "No Answer")
            row = [r["name"], r["phone"], status,
                   "Yes" if hits else "No", "Yes" if opened else "No",
                   r["att"], r["why"]]
            (badnum if (hits or called) else chase).append(row)
        tally[office] = (len(chase), len(badnum))
        wb = Workbook()
        wb.remove(wb.active)
        _sheet(wb, "Chase These",
               "No Contact At All — {}".format(label),
               "No text ever got through, no email was sent, and they are "
               "not on the call list. Nobody has reached these people and "
               "nobody is scheduled to. This is the list to work.",
               chase, RED)
        _sheet(wb, "Bad Number",
               "Reached Another Way — {}".format(label),
               "Every text to these people failed, BUT they were emailed or "
               "called. They are not lost — the phone number on their "
               "record is wrong. Fix the number; do not chase the person.",
               badnum, BLUE)
        path = OUTPUT / "corrected-{}.xlsx".format(office)
        wb.save(str(path))
        made.append(path)
        print("{:<26} chase {:>3} · bad number {:>3} -> {}".format(
            label, len(chase), len(badnum), path.name))
    return made, tally


if __name__ == "__main__":
    build()
