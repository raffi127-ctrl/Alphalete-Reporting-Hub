"""NDS T&C confirmation check (Carlos 2026-11-05).

Every evening 8:30 + 9:30pm, and 7:30am for the day before: log on to the
NDS dealer's SaraPlus (alphaletegp), Analytics -> Detail Reports -> Sales
Order History for the ONE day, open every row's View Customer card, and
read the 'T&C Sent Via' / 'Confirmation Date' pair. A sale with no
confirmation DATE gets a Slack call-out tagging Carlos + Sebastian:
"Hey, customer <first name> (rep: <rep>) — TNC has not been completed."
Carlos: "The sale will get canceled if we don't do that."

    lucy rerun nds_tnc_check                      # today, DRY RUN (logs only)
    lucy rerun nds_tnc_check --yesterday          # the morning pass
    lucy rerun nds_tnc_check --date 2026-11-04
    lucy rerun nds_tnc_check --probe --limit 2    # dump headers + card text
    lucy rerun nds_tnc_check --post               # the only flag that posts

Reuses rc_contact_sync.sara (login + passcode clearing, Telerik dates,
submit) and fiber_metrics.sara_pull._open_soh_panel (dealer-agnostic tab
opener) exactly as nds_metrics does. Python 3.9-safe.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.nds_tnc_check import config as C


def _log(msg: str) -> None:
    print("[tnc] " + msg, flush=True)


# ---------------------------------------------------------------- pure -----

_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", (s or "")).strip()


def _label_re(label: str) -> str:
    """'T&C Sent Via:' -> a pattern tolerant of 'T & C', 'T&amp;C', a
    missing colon and any whitespace."""
    out = []
    for ch in label:
        if ch == "&":
            out.append(r"\s*(?:&|&amp;|and)\s*")
        elif ch == " ":
            out.append(r"\s+")
        elif ch == ":":
            out.append(r"\s*:?")
        else:
            out.append(re.escape(ch))
    return "".join(out)


def parse_card_text(text: str) -> Dict[str, str]:
    """{label: value} for every CARD_LABELS found in the card's innerText.
    A value runs from its label to the NEXT label of the list, whichever
    comes first, so a wrapped 'Email to\\n<address>' stays one value."""
    flat = _norm(text)
    any_label = "|".join("(?:%s)" % _label_re(l)
                         for l in C.CARD_LABELS + C.STOP_LABELS)
    out: Dict[str, str] = {}
    for label in C.CARD_LABELS:
        m = re.search(r"(?i)(?<![A-Za-z])" + _label_re(label)
                      + r"\s*(.*?)\s*(?=(?:" + any_label + r")|$)", flat)
        if m:
            out[label] = m.group(1).strip()
    return out


_DATE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")


def has_confirmation_date(card: Dict[str, str]) -> bool:
    """A DATE under 'Confirmation Date:' -- a sent status alone is not it."""
    return bool(_DATE.search(card.get(C.LABEL_CONFIRMED, "") or ""))


def first_name(customer: str) -> str:
    c = _norm(customer)
    if "," in c:                       # "Gamez, Abby"
        c = c.split(",", 1)[1].strip()
    return c.split(" ")[0] if c else ""


def map_columns(headers: List[str]) -> Dict[str, int]:
    """{'order_id'|'rep'|'customer': column index} by header LABEL; raises
    naming the headers seen when one is missing."""
    heads = [_norm(h).lower() for h in headers]
    out: Dict[str, int] = {}
    for key, cands in (("order_id", C.COL_ORDER_ID), ("rep", C.COL_REP),
                       ("customer", C.COL_CUSTOMER)):
        for cand in cands:
            if cand.lower() in heads:
                out[key] = heads.index(cand.lower())
                break
        else:
            raise RuntimeError(
                "the grid has none of %s. Columns seen: %s"
                % (cands, ", ".join(h for h in headers if h)[:500]))
    for cand in C.COL_SALESPERSON:          # optional, logged only
        if cand.lower() in heads:
            out["salesperson"] = heads.index(cand.lower())
            break
    return out


# ------------------------------------------------------------- browser -----

def _read_grid_raw(page) -> Tuple[List[str], List[List[str]]]:
    from automations.rc_contact_sync import config as RC
    raw = page.evaluate(
        """(ids) => {
             const hdr = document.getElementById(ids.header);
             const data = document.getElementById(ids.data);
             if (!hdr || !data) return {headers: [], rows: [], missing: true};
             const headRow = hdr.querySelector('tr');
             const headers = headRow
               ? [...headRow.querySelectorAll('th,td')]
                   .map(c => (c.innerText || '').replace(/[ \\t\\n\\r]+/g, ' ').trim())
               : [];
             const rows = [...data.querySelectorAll('tbody > tr')]
               .map(r => [...r.querySelectorAll('td')]
                 .map(c => (c.innerText || '').replace(/[ \\t\\n\\r]+/g, ' ').trim()));
             return {headers: headers, rows: rows, missing: false};
           }""", {"header": RC.GRID_HEADER, "data": RC.GRID_DATA})
    if raw.get("missing"):
        raise RuntimeError("the Sales Order History grid is not on the page "
                           "(url=%s title=%r)" % (page.url, page.title()))
    return raw["headers"], raw["rows"]


def frame_is_this_card(txt: str, order_id: str, customer: str,
                       prev_text: str) -> bool:
    """Is this frame THIS order's card? The RadWindow keeps the previous
    customer's iframe around after Close, so 'a frame with a Confirmation
    Date on it' read the FIRST card for every order (dry run 2026-11-05:
    four customers, one email). The card must name this order -- its id,
    or failing that the customer's surname -- and must not be the text we
    just read."""
    if not re.search(r"(?i)confirmation\s+date", txt or ""):
        return False
    if prev_text and _norm(txt) == _norm(prev_text):
        return False
    if order_id and order_id in txt:
        return True
    words = [w for w in _norm(customer).split() if len(w) > 2]
    if words and re.search(r"(?i)\b" + re.escape(words[-1]) + r"\b", txt):
        return True
    return False


def _card_frame_text(page, order_id: str, customer: str, prev_text: str,
                     timeout_ms: int, log=_log) -> Tuple[str, str]:
    """(url, innerText) of THIS order's View Customer card once it carries
    the T&C block; ('', '') if it never shows. The frame read is blanked
    afterwards so it can never be mistaken for the next order's card."""
    deadline = dt.datetime.now() + dt.timedelta(milliseconds=timeout_ms)
    seen_other = ""
    while dt.datetime.now() < deadline:
        for fr in page.frames:
            if fr == page.main_frame:
                continue
            try:
                txt = fr.evaluate("() => (document.body.innerText || '')") or ""
            except Exception:  # noqa: BLE001
                continue
            if frame_is_this_card(txt, order_id, customer, prev_text):
                url = fr.url or ""
                try:
                    fr.evaluate("() => { document.body.innerHTML = ''; }")
                except Exception:  # noqa: BLE001
                    pass
                return url, txt
            if re.search(r"(?i)confirmation\s+date", txt):
                seen_other = txt
        page.wait_for_timeout(700)
    if seen_other:
        log("  %s: a card is open but it does not name this order/customer "
            "(%r) -- not trusted" % (order_id, _norm(seen_other)[:120]))
    return "", ""


def _close_card(page) -> bool:
    try:
        return bool(page.evaluate(
            """() => {
                 const els = [...document.querySelectorAll('a')];
                 const b = els.find(e => /rwCloseButton|CloseButton/i.test(e.className || ''))
                        || els.find(e => /^close$/i.test((e.textContent || '').trim()));
                 if (b) { b.click(); return true; }
                 return false;
               }"""))
    except Exception:  # noqa: BLE001
        return False


def _open_card(page, order_id: str, row_ix: int) -> str:
    """Click the row's View Customer link (by order id text, else by row
    position on this page). Returns 'clicked' or why not."""
    from automations.rc_contact_sync import config as RC
    return page.evaluate(
        """(cfg) => {
             const data = document.getElementById(cfg.gid);
             if (!data) return 'no grid';
             const rows = [...data.querySelectorAll('tbody > tr')];
             let row = cfg.oid
               ? rows.find(r => (r.innerText || '').includes(cfg.oid))
               : null;
             if (!row) row = rows[cfg.ix];
             if (!row) return 'row not found';
             const e = [...row.querySelectorAll('a')]
               .find(x => /view\\s*customer/i.test(x.innerText || ''))
               || [...row.querySelectorAll('a')].find(x => /view/i.test(x.innerText || ''));
             if (!e) return 'no View Customer link on the row';
             e.click();
             return 'clicked';
           }""", {"gid": RC.GRID_DATA, "oid": order_id, "ix": row_ix})


def _next_page(page) -> bool:
    """Click the RadGrid pager's Next if it is enabled. False = last page."""
    try:
        res = page.evaluate(
            """() => {
                 const n = document.querySelector('.rgPageNext');
                 if (!n) return 'no pager';
                 if (n.disabled || /rgDisabled|disabled/i.test(n.className || '')
                     || n.getAttribute('onclick') === 'return false;') return 'last';
                 n.click();
                 return 'clicked';
               }""")
    except Exception:  # noqa: BLE001
        return False
    if res != "clicked":
        return False
    try:
        page.wait_for_load_state("networkidle", timeout=C.NAV_TIMEOUT_MS)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(1500)
    return True


def _probe_dump(label: str, lines: List[str], log=_log) -> None:
    """Rich output -> the control sheet tab 'TNC Probe' (logtail truncates),
    best-effort; the log keeps a capped copy either way."""
    for ln in lines[:80]:
        log("   | " + ln[:200])
    if len(lines) > 80:
        log("   | ... (%d more lines, full dump on the 'TNC Probe' tab)"
            % (len(lines) - 80))
    try:
        from automations.recruiting_report import fill as _fill
        sh = _fill.open_by_key("1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw")
        try:
            ws = sh.worksheet("TNC Probe")
        except Exception:  # noqa: BLE001
            ws = sh.add_worksheet("TNC Probe", rows=400, cols=2)
        existing = ws.get_all_values()
        start = len(existing) + 1
        stamp = dt.datetime.now().isoformat(timespec="seconds")
        ws.update("A%d" % start,
                  [[stamp, "== " + label + " =="]] + [[stamp, l[:4000]] for l in lines])
        log("probe dump -> 'TNC Probe' tab rows %d-%d" % (start, start + len(lines)))
    except Exception as e:  # noqa: BLE001
        log("(sheet dump failed: %s: %s)" % (type(e).__name__, str(e)[:120]))


def scan(day: dt.date, *, limit: Optional[int] = None, probe: bool = False,
         headless: bool = True, log=_log) -> List[Dict[str, str]]:
    """Every order on the day's Sales Order History with its card's T&C
    fields. [{'order_id','rep','customer','sent_via','confirmed',
    'card_read': 'yes'|'no'}]"""
    from patchright.sync_api import sync_playwright
    from automations.fiber_metrics.sara_pull import _open_soh_panel
    from automations.rc_contact_sync import config as RC
    from automations.rc_contact_sync import sara
    from automations.vantura_nds_sara import config as NDS_CFG

    cr = json.loads(C.NDS_SARA_CREDS.read_text())
    C.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    out: List[Dict[str, str]] = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(C.PROFILE_DIR), headless=headless, args=["--disable-sync"],
            viewport={"width": 1600, "height": 1000})
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            log(NDS_CFG.code_inbox_status())
            base = sara.login(page, cr["email"], cr["password"], log=log,
                              code_inbox=NDS_CFG.code_inbox())
            log("saraplus (nds dealer): logged in as %s" % cr["email"])
            page.goto(base + RC.HUB_PATH, wait_until="networkidle",
                      timeout=RC.NAV_TIMEOUT_MS)
            _open_soh_panel(page, log=log)
            sara._set_telerik_date(page, RC.FIELD_START, day)
            sara._set_telerik_date(page, RC.FIELD_END, day)
            try:
                sara._set_customer_type(page, RC.CUSTOMER_TYPE_BOTH, log=log)
                sara._set_telerik_date(page, RC.FIELD_START, day)
                sara._set_telerik_date(page, RC.FIELD_END, day)
            except Exception as e:  # noqa: BLE001 -- dealer may lack it
                log("no Customer Type control (%s) -- dealer default" % e)
            log("date range %s -> %s" % (day, day))
            sara._submit(page, log=log)

            seen = 0
            prev_text = ""
            for page_no in range(1, C.MAX_PAGES + 1):
                headers, rows = _read_grid_raw(page)
                if page_no == 1:
                    log("grid headers (%d): %s"
                        % (len(headers), " | ".join(h for h in headers if h)[:600]))
                    if probe:
                        _probe_dump("grid headers %s" % day,
                                    ["[%d] %s" % (i, h) for i, h in enumerate(headers)],
                                    log=log)
                cols = map_columns(headers)
                data_rows = [(i, r) for i, r in enumerate(rows)
                             if r and len(r) > cols["order_id"] and r[cols["order_id"]]]
                log("page %d: %d order row(s)" % (page_no, len(data_rows)))
                for ix, r in data_rows:
                    if limit and seen >= limit:
                        break
                    seen += 1
                    oid = r[cols["order_id"]]
                    sp = (_norm(r[cols["salesperson"]])
                          if "salesperson" in cols and len(r) > cols["salesperson"] else "")
                    rec = {"order_id": oid, "rep": _norm(r[cols["rep"]]),
                           "salesperson": sp,
                           "customer": _norm(r[cols["customer"]]),
                           "sent_via": "", "confirmed": "", "card_read": "no"}
                    res = _open_card(page, oid, ix)
                    if res != "clicked":
                        log("  %s: %s" % (oid, res))
                        out.append(rec)
                        continue
                    url, txt = _card_frame_text(page, oid, rec["customer"],
                                                prev_text, C.CARD_TIMEOUT_MS,
                                                log=log)
                    if txt:
                        prev_text = txt
                        card = parse_card_text(txt)
                        rec["sent_via"] = card.get(C.LABEL_SENT_VIA, "")
                        rec["confirmed"] = card.get(C.LABEL_CONFIRMED, "")
                        rec["card_read"] = "yes"
                        if probe:
                            lines = [l.strip() for l in txt.splitlines() if l.strip()]
                            _probe_dump("card %s (%s)" % (oid, url[:100]), lines, log=log)
                            log("  parsed: %s" % json.dumps(card)[:400])
                    else:
                        log("  %s: the customer card never showed its T&C block"
                            % oid)
                    log("  %-14s %-22s rep=%r salesperson=%r via=%r confirmed=%r"
                        % (oid, rec["customer"][:22], rec["rep"][:30], sp[:30],
                           rec["sent_via"][:40], rec["confirmed"][:30]))
                    out.append(rec)
                    _close_card(page)
                    page.wait_for_timeout(1200)
                if limit and seen >= limit:
                    break
                if not _next_page(page):
                    break
                log("pager: next page")
        finally:
            ctx.close()
    return out


# ---------------------------------------------------------------- slack ----

def _load_state() -> Dict[str, List[str]]:
    try:
        return json.loads(C.STATE_PATH.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _save_state(state: Dict[str, List[str]]) -> None:
    C.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    keep = sorted(state)[-30:]
    C.STATE_PATH.write_text(json.dumps({k: state[k] for k in keep}, indent=1))


def _thread_ts(today: dt.date) -> Optional[str]:
    """Today's NDS Metrics thread, if nds_metrics has opened it."""
    try:
        from automations.nds_metrics.run import _state_path
        sp = _state_path(today)
        if sp.exists():
            return json.loads(sp.read_text()).get("ts")
    except Exception:  # noqa: BLE001
        pass
    return None


def post(missing: List[Dict[str, str]], *, day: dt.date, slot: str,
         send: bool, log=_log) -> int:
    key = "%s|%s" % (day.isoformat(), slot)
    state = _load_state()
    done = set(state.get(key, []))
    ts = _thread_ts(dt.date.today())
    n = 0
    client = None
    for rec in missing:
        text = C.message(first_name(rec["customer"]), rec["rep"])
        if rec["order_id"] in done:
            log("already posted this slot: %s" % rec["order_id"])
            continue
        if not send:
            log("DRY RUN would post to %s%s: %s"
                % (C.CHANNEL[0], " (NDS Metrics thread)" if ts else "", text))
            continue
        if client is None:
            from automations.shared.slack_metrics_post import _client
            client = _client()
        kw = {"channel": C.CHANNEL[1], "text": text}
        if ts:
            kw["thread_ts"] = ts
        client.chat_postMessage(**kw)
        done.add(rec["order_id"])
        state[key] = sorted(done)
        _save_state(state)
        n += 1
        log("posted: %s" % text)
    return n


# ----------------------------------------------------------------- main ----

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--date", help="YYYY-MM-DD (default today)")
    ap.add_argument("--yesterday", action="store_true",
                    help="the morning pass: the day before")
    ap.add_argument("--slot", default=None,
                    help="label for the posted-state key (default from --date/time)")
    ap.add_argument("--post", action="store_true",
                    help="actually post to Slack (default: dry run)")
    ap.add_argument("--probe", action="store_true",
                    help="dump grid headers + card text (read-only)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args(argv)

    now = dt.datetime.now()
    if a.date:
        day = dt.date.fromisoformat(a.date)
    elif a.yesterday:
        day = now.date() - dt.timedelta(days=1)
    else:
        day = now.date()
    slot = a.slot or ("morning" if a.yesterday else now.strftime("%H:%M"))
    log = _log
    log("day %s · slot %s · %s" % (day, slot, "POST" if a.post else "DRY RUN"))

    try:
        recs = scan(day, limit=a.limit, probe=a.probe, headless=not a.headed, log=log)
    except Exception as e:  # noqa: BLE001
        log("FAILED: %s: %s" % (type(e).__name__, str(e)[:600]))
        return 1

    if not recs:
        log("no orders on %s -- nothing to check (never post blank)" % day)
        return 0
    unread = [r for r in recs if r["card_read"] != "yes"]
    missing = [r for r in recs
               if r["card_read"] == "yes"
               and not has_confirmation_date({C.LABEL_CONFIRMED: r["confirmed"]})]
    log("%d order(s): %d confirmed, %d NOT confirmed, %d card(s) unreadable"
        % (len(recs), len(recs) - len(missing) - len(unread), len(missing),
           len(unread)))
    for r in unread:
        log("  unreadable card (NOT called out): %s %s / %s"
            % (r["order_id"], r["customer"], r["rep"]))
    if a.probe:
        return 0
    n = post(missing, day=day, slot=slot, send=a.post, log=log)
    log("finished: %d call-out(s) %s" % (n if a.post else len(missing),
                                          "posted" if a.post else "would post"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
