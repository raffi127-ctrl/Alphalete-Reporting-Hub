"""Create (or refresh) the Captain Ship Ad View tab.

WHAT IT IS. A second copy of Manager View — B1 picks a name, A4 is an INDIRECT
that pulls that person's Indeed ad tracker tab — but its dropdown lists Carlos's
captainship instead of the org's 17 managers. Manager View's own list (0Config
column A) has never included Noah Dubale, Jamis Garay or Jackie LeRoy, so before
this there was no way to look at their ads in this workbook at all.

WHY IT IS NOT PART OF build.py. Nothing here is derived from the pull. The
manager tabs are IMPORTRANGE mirrors that Google refreshes on its own, so the
view is pure plumbing that only changes when the captainship changes. Rebuilding
it hourly would just be a way to lose a hand edit at 3am. Run it by hand:

    .venv/bin/python -m automations.funnel_board.ad_view

Idempotent: it duplicates Manager View the first time (which is how the tab
inherits the exact formatting), and afterwards only rewrites the name list and
the dropdown. Names come from roster.AD_TABS and must match tab names EXACTLY —
INDIRECT does a literal string match, and a tab named with a trailing space
breaks the view while looking perfectly fine in the tab bar.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from automations.funnel_board.auth import session as _auth_session  # noqa: E402
from automations.funnel_board.roster import AD_TABS, AD_VIEW_TITLE  # noqa: E402

SSID = os.environ.get("FUNNEL_SSID", "1nOuJ5kGtEf25XIgKE-_iu8-tUHA8kZ6hyDaJnaJNmVo")
API = "https://sheets.googleapis.com/v4/spreadsheets/" + SSID
SOURCE = "Manager View"
LIST_COL = "E"          # 0Config column A is Manager View's list; E is ours
S = _auth_session(verbose=True)


def call(path, payload, method="post"):
    r = getattr(S, method)(API + path, json=payload)
    if r.status_code != 200:
        raise SystemExit("%s %s -> %s\n%s" % (method.upper(), path, r.status_code,
                                              r.text[:1500]))
    return r.json()


def main():
    meta = S.get(API, params={"fields": "sheets.properties(sheetId,title,index)"}).json()
    sid = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}

    missing = [t for t in AD_TABS if t not in sid]
    if missing:
        # Not fatal: a name with no tab yet simply shows #REF until the tab
        # lands. Say so, because a silent #REF reads as a broken view.
        print("no ad tracker tab (yet) for: %s" % ", ".join(missing))

    if AD_VIEW_TITLE not in sid:
        if SOURCE not in sid:
            raise SystemExit("'%s' is missing — nothing to copy the layout from" % SOURCE)
        res = call(":batchUpdate", {"requests": [{"duplicateSheet": {
            "sourceSheetId": sid[SOURCE],
            "insertSheetIndex": len(meta["sheets"]),
            "newSheetName": AD_VIEW_TITLE}}]})
        sid[AD_VIEW_TITLE] = res["replies"][0]["duplicateSheet"]["properties"]["sheetId"]
        print("created '%s' from '%s'" % (AD_VIEW_TITLE, SOURCE))
    else:
        print("'%s' already exists — refreshing its list" % AD_VIEW_TITLE)

    last = len(AD_TABS)
    call("/values:batchUpdate", {"valueInputOption": "USER_ENTERED", "data": [
        {"range": "'0Config'!%s1" % LIST_COL, "values": [[n] for n in AD_TABS]},
        # G1 on Manager View is its own table-capacity note, about a different
        # table. Carried over by the duplicate and meaningless here.
        {"range": "'%s'!G1" % AD_VIEW_TITLE, "values": [[""]]},
        {"range": "'%s'!B1" % AD_VIEW_TITLE, "values": [[AD_TABS[0]]]},
    ]})
    # Clear anything below the list, in case the captainship shrank.
    call("/values/'0Config'!%s%d:%s100:clear" % (LIST_COL, last + 1, LIST_COL), {})

    call(":batchUpdate", {"requests": [{"setDataValidation": {
        "range": {"sheetId": sid[AD_VIEW_TITLE], "startRowIndex": 0, "endRowIndex": 1,
                  "startColumnIndex": 1, "endColumnIndex": 2},
        "rule": {"condition": {"type": "ONE_OF_RANGE", "values": [
            {"userEnteredValue": "='0Config'!$%s$1:$%s$%d" % (LIST_COL, LIST_COL, last)}]},
            "showCustomUi": True, "strict": True}}}]})
    print("dropdown lists %d name(s): %s" % (last, ", ".join(AD_TABS)))
    print("done -> https://docs.google.com/spreadsheets/d/%s/edit#gid=%s"
          % (SSID, sid[AD_VIEW_TITLE]))


if __name__ == "__main__":
    main()
