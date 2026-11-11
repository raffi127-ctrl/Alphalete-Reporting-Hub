"""Split the finished Order Log .xlsx into three by rep name: A-F, G-M, N-Z.

Rafael 2026-10-31: reps read the Order Log in Slack's PHONE PREVIEW, never
downloading it, and the preview stops at ~1,000 rows and ~30 tabs. On 10/31
the log was 1,791 rows / 69 tabs, so it cut off at "Justin Carlos Avila" and
everyone from J down lost their personal tab. Split by letter, each file is
~500-750 rows and ~20-25 tabs — inside the preview again — and a rep opens
the file with their letter. (A picture-per-rep thread was tried the same day
and dropped: 134 posts was too many.)

Works on the workbook csv_to_xlsx already built, so the three files look
exactly like the one they came from: same Pay Period tab, the Cleaned Order
Log cut down to that letter's reps, and only those reps' tabs.

    python -m automations.uploaded.order_log_split "Order Log 10-31-2026.xlsx" --out output/ol_split
    python -m automations.uploaded.order_log_split x.xlsx --post-to D087ZGE2B0F   # TEST post (Eve's own DM only)

Python 3.9-safe (Lucy runtime). Cross-platform.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

LOG_TAB = "Cleaned Order Log"
NON_REP_TABS = {"Pay Period", LOG_TAB}
# (label, first letter, last letter) — fixed, so a rep always knows which file.
GROUPS = [("A-F", "A", "F"), ("G-M", "G", "M"), ("N-Z", "N", "Z")]
# Slack's phone preview shows ~1,000 rows per tab and ~30 tabs. Warn early.
ROW_WARN, TAB_WARN = 950, 28


def over_phone_limit(xlsx_path: Path) -> Tuple[bool, int, int]:
    """(too big?, rows in the log, rep tabs). Same early margin as the warning
    in split(): past this the phone preview can cut reps off the bottom."""
    from openpyxl import load_workbook
    wb = load_workbook(xlsx_path, read_only=True)
    tabs = sum(1 for n in wb.sheetnames if n not in NON_REP_TABS)
    rows = 0
    if LOG_TAB in wb.sheetnames:
        rows = sum(1 for r in wb[LOG_TAB].iter_rows(min_row=2, max_col=1, values_only=True)
                   if r[0] not in (None, ""))
    wb.close()
    return (rows > ROW_WARN or tabs > TAB_WARN), rows, tabs


def group_of(rep: str) -> str:
    first = (str(rep or "").strip()[:1] or "Z").upper()
    for label, lo, hi in GROUPS:
        if lo <= first <= hi:
            return label
    return GROUPS[-1][0]          # digits / symbols: last file


def _drop_rows(ws, keep: Sequence[bool]) -> None:
    """Delete data rows (row 2 on) whose keep flag is False, bottom-up in
    contiguous runs so it stays fast and the header is untouched."""
    r = len(keep) + 1                      # last data row
    while r >= 2:
        if keep[r - 2]:
            r -= 1
            continue
        end = r
        while r >= 2 and not keep[r - 2]:
            r -= 1
        ws.delete_rows(r + 1, end - r)


def _name_banner(ws, name: str) -> None:
    """Put the rep's name in a big black band on top of their tab.

    Eve 2026-10-31, on her phone: "estoy en la tab 25 pero no sé de quién es".
    Slack's preview never shows the tab NAME — the pages just scroll by — and
    the rep tab drops the Rep column, so nothing on the page said whose it
    was. openpyxl's insert_rows doesn't move merged ranges, so the week
    banners are unmerged, shifted down by hand, and merged again."""
    from openpyxl.styles import Alignment, Font, PatternFill
    # Already bannered (csv_to_xlsx does it for every office since 11/11, and
    # the split works on that same file): never stack a second band.
    if ws.cell(row=1, column=1).value == name.upper():
        return
    merges = [(m.min_row, m.min_col, m.max_row, m.max_col)
              for m in ws.merged_cells.ranges]
    for m in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(m))
    # insert_rows doesn't move row heights either (the 34pt header rows).
    heights = {r: d.height for r, d in ws.row_dimensions.items() if d.height}
    ws.insert_rows(1, 2)                   # name band + a spacer
    for r in list(ws.row_dimensions):
        ws.row_dimensions[r].height = None
    for r, h in heights.items():
        ws.row_dimensions[r + 2].height = h
    for r1, c1, r2, c2 in merges:
        ws.merge_cells(start_row=r1 + 2, start_column=c1,
                       end_row=r2 + 2, end_column=c2)
    ncol = max(ws.max_column, 1)
    cell = ws.cell(row=1, column=1, value=name.upper())
    # 8-digit ARGB: a 6-digit color is saved with alpha 00, which Slack's
    # preview draws as transparent — white text on no fill, i.e. invisible.
    cell.font = Font(name="Georgia", size=20, bold=True, color="FFFFFFFF")
    cell.fill = PatternFill("solid", fgColor="FF000000")
    cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)
    ws.row_dimensions[1].height = 36


def split(xlsx_path: Path, out_dir: Path) -> List[Tuple[str, Path]]:
    """[(label, path)] — one file per letter group that has any rep in it."""
    from openpyxl import load_workbook
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = xlsx_path.stem
    out: List[Tuple[str, Path]] = []
    for label, _lo, _hi in GROUPS:
        wb = load_workbook(xlsx_path)
        tabs = 0
        for name in list(wb.sheetnames):
            if name in NON_REP_TABS:
                continue
            if group_of(name) != label:
                del wb[name]
            else:
                _name_banner(wb[name], name)
                tabs += 1
        rows = 0
        if LOG_TAB in wb.sheetnames:
            ws = wb[LOG_TAB]
            keep = [group_of(row[0]) == label
                    for row in ws.iter_rows(min_row=2, max_col=1, values_only=True)]
            rows = sum(keep)
            _drop_rows(ws, keep)
        if not rows and not tabs:
            continue
        # Rep tabs BEFORE the long log: in Slack's phone preview every tab is
        # one page under the other, so a rep had to scroll ~500-750 log rows
        # before reaching any name (Raf 2026-10-31: "too much friction").
        if LOG_TAB in wb.sheetnames:
            wb.move_sheet(LOG_TAB, offset=len(wb.sheetnames) - 1 - wb.sheetnames.index(LOG_TAB))
        if rows > ROW_WARN or tabs > TAB_WARN:
            print(f"  ⚠ Order Log {label}: {rows} rows / {tabs} rep tabs — close "
                  f"to Slack's phone-preview limit (~1,000 rows / ~30 tabs)")
        path = out_dir / f"{stem} ({label}).xlsx"
        wb.save(path)
        print(f"  Order Log {label}: {rows} rows, {tabs} rep tabs -> {path.name}")
        out.append((label, path))
    return out


def rep_files(letter_xlsx: Path, out_dir: Path) -> List[Tuple[str, Path]]:
    """[(rep, path)] — one tiny .xlsx per rep tab of a letter file, holding
    only that rep's tab (name banner already on it). Posted as one thread
    reply per rep under the letter's post (Raf 2026-10-31, option 2:
    "separation by letters but then a post per rep for their activations")."""
    from openpyxl import load_workbook
    out_dir.mkdir(parents=True, exist_ok=True)
    reps = sorted((n for n in load_workbook(letter_xlsx, read_only=True).sheetnames
                   if n not in NON_REP_TABS), key=str.lower)
    out: List[Tuple[str, Path]] = []
    for rep in reps:
        wb = load_workbook(letter_xlsx)
        for name in list(wb.sheetnames):
            if name != rep:
                del wb[name]
        path = out_dir / f"{rep}.xlsx"
        wb.save(path)
        out.append((rep, path))
    return out


def post_threads(client, channel: str, parts: List[Tuple[str, Path]],
                 out_dir: Path, today_label: str) -> List[dict]:
    """One parent post per letter. In its thread, per rep: a text reply with
    their NAME, then their one-tab file right under it. The thread's FIRST
    reply is an INDEX: every name links to that rep's name message, so the
    phone jumps straight to it (Eve 2026-10-31: "queremos evitar que tengan
    que hacer scroll"), and the channel post links straight to the index.

    Why name messages and not file links: Slack hangs every linked FILE
    under the message as an attachment, unfurl flags or not, so a 24-name
    index turned into 24 files in a row. Message links don't do that.

    Returns every message / file it created ({"ts"} or {"file"}) so a test
    post can be cleaned up afterwards; also written to out_dir/posted.json."""
    import json
    import time
    created: List[dict] = []

    def _file_id(resp) -> str:
        f = resp.get("file") or (resp.get("files") or [{}])[0]
        return f.get("id", "")

    def _text(thread_ts, text):
        r = client.chat_postMessage(channel=channel, thread_ts=thread_ts,
                                    text=text, unfurl_links=False,
                                    unfurl_media=False)
        created.append({"channel": channel, "ts": r["ts"]})
        return r["ts"]

    def _upload(path, name) -> str:
        """Upload WITHOUT sharing; returns the file's permalink. A message
        carrying that link shows the file under it, so name + file are ONE
        reply whose ts we know (a shared upload's message ts isn't returned)."""
        for attempt in range(3):
            try:
                r = client.files_upload_v2(file=str(path), filename=name)
                f = r.get("file") or (r.get("files") or [{}])[0]
                created.append({"file": f.get("id", "")})
                return f.get("permalink", "")
            except Exception as e:  # noqa: BLE001  (rate limit -> wait)
                print(f"  retry {name}: {e}")
                time.sleep(20)
        return ""

    def _with_file(thread_ts, text, path, name) -> str:
        url = _upload(path, name)
        r = client.chat_postMessage(channel=channel, thread_ts=thread_ts,
                                    text=f"{text}\n<{url}|{name}>" if url else text)
        created.append({"channel": channel, "ts": r["ts"]})
        return r["ts"]

    def _link(msg_ts) -> str:
        return client.chat_getPermalink(channel=channel,
                                        message_ts=msg_ts)["permalink"]

    for label, path in parts:
        title = f"📋 *Order Log {today_label} — reps {label.replace('-', '–')}*"
        ts = _text(None, f"{title}\nOpen the thread 👇 and tap your name")
        # The index is the FIRST reply (Eve 2026-11-01). Its names link to messages
        # that do not exist yet, so it goes up as a placeholder and is filled at the end.
        index_ts = _text(ts, f"👉 *Tap your name:* (names loading...)")
        full_ts = _with_file(ts, f"*All reps {label.replace('-', '–')}* (one file)",
                             path, path.name)
        links = []
        for rep, rpath in rep_files(path, out_dir / "reps" / label):
            name_ts = _with_file(ts, f"*{rep}*", rpath,
                                 f"{rep} - Order Log {today_label}.xlsx")
            links.append((rep, _link(name_ts)))
            time.sleep(1)
        index = "\n".join(f"• <{url}|{rep}>" for rep, url in links)
        index_text = (f"👉 *Tap your name:*\n{index}\n\n"
                      f"<{_link(full_ts)}|All reps {label} in one file>")
        try:
            client.chat_update(channel=channel, ts=index_ts, text=index_text)
        except Exception as e:  # noqa: BLE001  (names still reach the thread)
            print(f"  ⚠ could not fill the {label} index, posting it as a new reply: {e}")
            index_ts = _text(ts, index_text)
        # Point the channel post straight at the index. Slack opens a thread
        # at a different spot depending on what's unread (Eve 2026-11-01:
        # channel landed on the first reply, DM on the last), so "open the
        # thread" can't promise the index is on screen; a link to the reply can.
        # If this fails the post still says "open the thread", which works.
        try:
            client.chat_update(channel=channel, ts=ts,
                               text=f"{title}\n👉 <{_link(index_ts)}|Find your name here>")
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ could not link the {label} post to its index: {e}")
        print(f"  ✓ posted thread {label} ({len(links)} reps, index = first reply)")
    (out_dir / f"posted_{channel}.json").write_text(json.dumps(created, indent=1),
                                         encoding="utf-8")
    return created


def comment_for(label: str) -> str:
    return f"📋 Order Log — reps *{label.replace('-', '–')}* (*NEW* - Track your paycheck)"


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("xlsx", type=Path)
    ap.add_argument("--out", type=Path, default=Path("output/ol_split"))
    ap.add_argument("--post-to", metavar="CHANNEL",
                    help="TEST: post the three files into this channel/DM id")
    ap.add_argument("--threads", action="store_true",
                    help="with --post-to: parent per letter + one reply per rep")
    a = ap.parse_args(argv)
    parts = split(a.xlsx, a.out)
    if a.post_to and a.threads:
        from automations.shared.slack_metrics_post import _client
        stamp = a.xlsx.stem.replace("Order Log", "").strip()
        post_threads(_client(), a.post_to, parts, a.out, stamp)
        return 0
    if a.post_to:
        from automations.shared.slack_metrics_post import _client
        client = _client()
        for label, path in parts:
            client.files_upload_v2(channel=a.post_to, file=str(path),
                                   filename=path.name,
                                   initial_comment=comment_for(label))
            print(f"  ✓ posted {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
