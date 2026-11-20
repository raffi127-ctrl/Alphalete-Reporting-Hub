"""Pull the OwnerVille data for our copy of the CEO Dashboard Sales Board, every morning (Eve 2026-11-20).

Opens OwnerVille's CEO Dashboard (p=9197) with this machine's OwnerVille session, finds the frame
where OwnerVille's own KnockReport / callApi live, and runs extract.js there -- the same code that
built the board's data.json by hand on 11/20, so the numbers stay OwnerVille's exactly.

The result (data.json, ~270 KB, has rep emails) goes into the bridge sheet in pieces: rows
`file | data.json.NN | <piece>` plus one `filemeta | data.json | {"at", "parts", "generatedAt"}`.
The daily claude.ai routine glues the pieces back together and republishes the board with them;
a Lucy cannot publish an artifact itself. Rows written by sheet_import.py (roll call etc.) are
left as they are.

    python -m automations.ov_sales_board.ov_pull             # pull + write the bridge sheet
    python -m automations.ov_sales_board.ov_pull --dry-run   # pull, save output/ov_sales_board/data.json only
"""
import argparse
import datetime as dt
import json
import os
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OFFICE_ID = "11280"
OFFICE_LABEL = "Alphalete Marketing, INC."
WEEKS = 13
PIECE = 45000            # a sheet cell holds 50,000 characters
OUT = Path("output/ov_sales_board/data.json")


def find_board_frame(page, wait_s=60):
    """The frame of the CEO Dashboard that has OwnerVille's callApi + KnockReport."""
    probe = "() => typeof window.callApi === 'function' && !!window.KnockReport"
    end = time.time() + wait_s
    while time.time() < end:
        for fr in page.frames:
            try:
                if fr.evaluate(probe):
                    return fr
            except Exception:
                pass
        time.sleep(2)
    raise RuntimeError("CEO Dashboard frame with KnockReport/callApi not found in %ds" % wait_s)


def pull(headless=True):
    from automations.b2b_dispositions.capture import capture_rqst
    from automations.shared.tableau_patchright import ownerville_session
    js = (HERE / "extract.js").read_text(encoding="utf-8")
    call = ("async () => { %s\n return await extractSalesBoard(window, %s); }"
            % (js, json.dumps({"officeId": OFFICE_ID, "weeks": WEEKS, "officeLabel": OFFICE_LABEL})))
    with ownerville_session(headless=headless) as page:
        rqst = capture_rqst(page)
        page.goto("https://v2.ownerville.com/index.cfm?p=9197&rqst=%s" % rqst, wait_until="domcontentloaded",
                  timeout=60000)
        frame = find_board_frame(page)
        data = frame.evaluate(call)
    if not data or not data.get("knocks") or not data.get("sales"):
        raise SystemExit("OwnerVille returned no knocks or no sales -- not replacing the board's data")
    return data


def write_bridge(text, generated_at):
    from automations.recruiting_report.fill import _client
    from automations.ov_sales_board.sheet_import import BRIDGE_SHEET_ID
    ws = _client().open_by_key(BRIDGE_SHEET_ID).sheet1
    keep = [r for r in ws.get_all_values()[1:] if r and r[0] not in ("file", "filemeta")]
    parts = [text[i:i + PIECE] for i in range(0, len(text), PIECE)]
    at = dt.datetime.now().strftime("%-m/%-d %H:%M") if os.name != "nt" else dt.datetime.now().strftime("%#m/%#d %H:%M")
    rows = [["collection", "doc_id", "json"]] + [r[:3] + [""] * (3 - len(r[:3])) for r in keep]
    rows.append(["filemeta", "data.json", json.dumps({"at": at, "parts": len(parts), "generatedAt": generated_at})])
    rows += [["file", "data.json.%02d" % i, p] for i, p in enumerate(parts)]
    ws.clear()
    ws.update(values=rows, range_name="A1", value_input_option="RAW")
    print("bridge sheet: data.json in %d pieces (%d characters), %d other rows kept" % (len(parts), len(text), len(keep)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="only save output/ov_sales_board/data.json")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()
    data = pull(headless=not a.headed)
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print("OwnerVille: %d knock rows, %d sale rows, %d people, %d teams, errors: %s"
          % (len(data["knocks"]), len(data["sales"]), len(data["people"]), len(data["teams"]),
             "; ".join(data.get("errors") or []) or "none"))
    if not a.dry_run:
        write_bridge(text, data.get("generatedAt", ""))


if __name__ == "__main__":
    main()
