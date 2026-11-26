"""Indeed Account Check -- one page off the office computer's Octo run.

gather(): the newest probe-octo-lookup row for today (Relay Faults tab, filled by
Lucy 1's relay_faults verb), the Billing Holds tab and the live-ads Days Down.
render(): the HTML page (no doctype/html/head/body: the Artifact skeleton adds them).
"""
import datetime as dt, html, json, re, sys, warnings
warnings.filterwarnings("ignore")
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "output" / "indeed-account-check.html"
DATA = Path(__file__).resolve().parents[2] / "output" / "octo-report-data.json"
DASH = "111Bmxx1JvT1UFXaLin7gPH53149WBZhMe0r7CHirHbA"
LIVE_ADS_NAME = {"New Ascendra": "Ascendra", "VividReach - Active": "VividReach"}
PROFILES = ["Fast Track Strategies", "Revolt Consulting Marketing", "Iron Sales Group",
            "Raw Sales Group Marketing", "Peak Sales Strategies", "Hawk Specialized Marketing",
            "Titanium TX", "W Edge", "Haus Specialized Marketing", "Magma Inc Marketing",
            "Kinetic Marketing Partners", "New Ascendra", "Pinnacle Growth Acquisitions",
            "Market Minds", "Riot Specialized Marketing", "Maverick Strategies", "VividReach - Active"]
# the week's morning lookups, off the daily tally rows (today's comes from the newest row)
WEEK = [("Thu 20", 1, 0), ("Fri 21", 3, 1), ("Sat 22", 0, 1), ("Sun 23", 2, 4), ("Mon 24", 8, 3)]
# what each account last read, before Octo stopped opening (Mon 5am): used only
# when the fresh run did not read it
LAST_KNOWN = {
    "Hawk Specialized Marketing": ("live", "Clean at Mon 11/24, 5am"),
    "Iron Sales Group": ("live", "Clean at Mon 11/24, 5am"),
    "Magma Inc Marketing": ("live", "Clean at Mon 11/24, 5am"),
    "Raw Sales Group Marketing": ("live", "Clean at Mon 11/24, 5am"),
    "Fast Track Strategies": ("live", "Clean at Sun 11/23, 5am"),
    "Revolt Consulting Marketing": ("live", "Clean at Sun 11/23, 5am"),
    "Market Minds": ("live", "Clean at Sun 11/23, 5am"),
    "Maverick Strategies": ("live", "Clean at Sun 11/23, 5am"),
    "Pinnacle Growth Acquisitions": ("live", "Clean at Sun 11/23, 5am"),
    "Riot Specialized Marketing": ("live", "Clean at Sun 11/23, 5am"),
    "VividReach - Active": ("live", "Clean at Sun 11/23, 5am"),
    "W Edge": ("live", "Clean at Sun 11/23, 5am"),
    "Peak Sales Strategies": ("unknown", "Walled Mon 5am; a new 'Payment declined' email Sun 11/23, 2:03pm"),
    "Haus Specialized Marketing": ("hold", "Flagged Mon 11/24, 5am"),
    "Titanium TX": ("hold", "Flagged Sun 11/23, 1pm"),
    "Kinetic Marketing Partners": ("hold", "Flagged every check since Thu 11/19"),
    "New Ascendra": ("hold", "Flagged every check since Sat 11/21"),
}
SHORT = {"Fast Track Strategies": "Fast Track", "Revolt Consulting Marketing": "Revolt", "Iron Sales Group": "Iron Sales",
         "Raw Sales Group Marketing": "Raw Sales", "Peak Sales Strategies": "Peak Sales", "Hawk Specialized Marketing": "Hawk",
         "Haus Specialized Marketing": "Haus", "Magma Inc Marketing": "Magma", "Kinetic Marketing Partners": "Kinetic",
         "Pinnacle Growth Acquisitions": "Pinnacle", "Riot Specialized Marketing": "Riot", "Maverick Strategies": "Maverick"}
FIRST_DECLINE = {"Peak Sales Strategies": "Sun 11/23, 2:03 pm"}   # read off its inbox 11/24; paid 11/21 2:20 pm
OCTO_WALL_FROM = "2026-11-24T05:10"
OFFICE_TZ_NOW = None  # set in gather()


def _p(s):
    """'11/16/2026 7:33 PM' or ISO -> datetime, else None."""
    s = (s or "").strip()
    for f in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return dt.datetime.strptime(s, f)
        except ValueError:
            pass
    return None


def _day(d):
    return d.strftime("%a %-m/%d")


def _when(d):
    return d.strftime("%a %-m/%d, %-I:%M %p").replace("AM", "am").replace("PM", "pm")


def _tolerant(detail):
    """The row's JSON, or what can be pulled out of a cut one: every top-level
    value that is still whole (raw_decode from its key), and for a dict cut in
    the middle, its whole entries."""
    try:
        return json.loads(detail)
    except ValueError:
        pass
    dec = json.JSONDecoder()
    out = {"cut": True, "accounts": {}, "billing": {}, "found": [], "missing": [], "ran": {}, "billing_mail": {}}
    # the top-level key, told apart from a same-named key inside `ran`
    # ("lookups", "billing") by the type of value that follows it
    typed = {"office": '"', "date": '"', "at": '"', "ran": "{", "snapshot": '"', "listed": "0-9",
             "found": "[", "missing": "[", "accounts": "{", "billing": "{", "billing_mail": "{",
             "elapsed_min": "0-9", "csv_rows": "0-9"}
    for key, t in typed.items():
        m = re.search(r'"%s":(?=[%s])' % (key, re.escape(t) if t != "0-9" else "0-9"), detail)
        if not m:
            continue
        try:
            val, _ = dec.raw_decode(detail, m.end())
            out[key] = val
        except ValueError:
            seg = detail[m.end():]
            if seg.startswith("{"):
                part = {}
                for k, v in re.findall(r'"([^"]+)":(\{[^{}]*\})', seg):
                    try:
                        part[k] = json.loads(v)
                    except ValueError:
                        pass
                out[key] = part
    return out


def gather(want_kick=""):
    from automations.recruiting_report import fill as _fill
    from automations.day_orchestrator import mini_control as MC
    gc = _fill._client()
    # --- today's rows off the Relay Faults tab
    rows = gc.open_by_key(MC.CONTROL_SHEET_ID).worksheet("Relay Faults").get_all_values()
    lines = [r[0] if r else "" for r in rows]
    runs, i = [], 1
    while i < len(lines):
        if lines[i].startswith("row "):
            head, summary = lines[i], lines[i + 1]
            j = i + 2
            detail = ""
            while j < len(lines) and lines[j] != "":
                detail += lines[j]; j += 1
            d = _tolerant(detail)
            d["_head"], d["_summary"] = head, summary
            runs.append(d)
            i = j
        else:
            i += 1
    today = [r for r in runs if (r.get("date") or "") == dt.date.today().isoformat()
             or dt.date.today().strftime("%-m/%-d/%Y") in r.get("_head", "")]
    pick = None
    if want_kick:
        for r in today:
            if (r.get("ran") or {}).get("kick") == want_kick:
                pick = r
    if pick is None and today:
        pick = max(today, key=lambda r: r.get("at") or "")
    # --- holds
    sh = gc.open_by_key(DASH)
    holds = []
    for r in sh.worksheet("Billing Holds").get_all_values()[1:]:
        r = (r + [""] * 4)[:4]
        if not r[0].strip():
            continue
        holds.append({"account": r[0].strip(), "from": r[1].strip(), "until": r[2].strip(), "note": r[3].strip(),
                      "estimated": "estimated" in r[3].lower()})
    # --- live ads: newest week block, Days Down per account
    rows = sh.worksheet("carlos' live ads").get_all_values()
    blocks = {}
    for r in rows[1:]:
        r = (r + [""] * 14)[:14]
        if not r[0] or not r[3]:
            continue
        blocks.setdefault(r[0], []).append(r)
    newest = max(blocks, key=lambda k: _p(k + " 12:00 AM") or dt.datetime.min) if blocks else None
    ads = {}
    for r in blocks.get(newest, []):
        if r[4].strip().lower() not in ("yes", "y", "true", "active"):
            continue                                   # a closed ad is not a live one
        try:
            dd = float(str(r[13]).replace("$", "") or 0)
        except ValueError:
            dd = 0.0
        a = ads.setdefault(r[3].strip(), {"ads": 0, "days_down": 0.0})
        a["ads"] += 1
        a["days_down"] = max(a["days_down"], dd)
    data = {"run": pick, "holds": holds, "ads": ads, "ads_week": newest,
            "gathered": dt.datetime.now().isoformat(timespec="minutes")}
    DATA.write_text(json.dumps(data, indent=1))
    return data


def classify(title, run):
    """-> (state, headline, detail) for one Octo profile off the fresh run."""
    b = ((run or {}).get("billing") or {}).get(title, "")
    a = ((run or {}).get("accounts") or {}).get(title, "")
    at = (run or {}).get("at") or ""
    when = "the %s check" % at if at else "this check"
    if b == "ok":
        return "live", "Live", "Clean at %s" % when
    if b.startswith("PROBLEM"):
        hit = b.split(":", 1)[1].strip()
        return "hold", "On hold", "Indeed shows: “%s”" % (hit[:90] + ("…" if len(hit) > 90 else ""))
    if b == "walled":
        return "unread", "Not read", "Cloudflare wall did not pass; next try at the 5am run"
    if b.startswith("could not start"):
        why = b[len("could not start"):].strip(" ()")
        return "unread", "Not opened", "Octo would not open it: %s" % why
    if b in ("in use", "in use on another computer"):
        return "unread", "Not opened", "Profile open on another computer"
    if b == "out of time":
        return "unread", "Not read", "The run hit its time budget before this account"
    if b.startswith("error"):
        return "unread", "Not read", "Browser error while reading"
    if b == "blank":
        return "unread", "Not read", "All Jobs page came back blank"
    if b:
        return "unread", "Not read", b[:80]
    return "unread", "Not read", a[:80] if a else "Not in this run"


def render(data):
    run = data.get("run") or {}
    ran = run.get("ran") or {}
    at = _p("%sT%s:00" % (run.get("date") or dt.date.today().isoformat(), run.get("at") or "00:00")) \
        if run.get("at") else None
    now = dt.datetime.now()
    holds = data["holds"]
    ads = data["ads"]
    open_hold = {}
    for h in holds:
        if not h["until"]:
            open_hold[h["account"]] = h
    rows = []
    counts = {"live": 0, "hold": 0, "unread": 0, "empty": 0}
    for t in PROFILES:
        state, head, detail = classify(t, run)
        name = LIVE_ADS_NAME.get(t, t)
        if state == "live" and not (ads.get(name) or {}).get("ads"):
            state, head, detail = "empty", "No ads", "Nothing posted on this account; billing page clean"
        since = ""
        if state == "hold":
            oh = open_hold.get(name)
            mail = ((run.get("billing_mail") or {}).get(t) or {})
            if oh and _p(oh["from"]):
                since = "On hold since %s%s" % (_when(_p(oh["from"])), " (estimated)" if oh["estimated"] else "")
            elif _p(mail.get("declined") or ""):
                since = "Latest ‘Payment declined’ email %s" % _when(_p(mail["declined"]))
                if t in FIRST_DECLINE:
                    since += "; first one after its last payment %s" % FIRST_DECLINE[t]
            elif mail.get("signed_in") is False:
                since = "Hold start unknown: this account’s Gmail is signed out in Octo"
        if state == "unread":
            lk = LAST_KNOWN.get(t)
            if lk:
                prev_state, prev = lk
                if prev_state == "hold":
                    oh = open_hold.get(name)
                    if oh and _p(oh["from"]):
                        since = "Last known: on hold since %s" % _when(_p(oh["from"]))
                    else:
                        since = "Last known: " + prev
                elif prev_state == "live":
                    since = "Last known: live. " + prev
                else:
                    since = "Last known: " + prev
        counts[state] += 1
        a = ads.get(name, {})
        rows.append({"title": t, "name": name, "state": state, "head": head, "detail": detail,
                     "since": since, "ads": a.get("ads", 0), "days_down": a.get("days_down", 0.0),
                     "last_state": (LAST_KNOWN.get(t) or ("", ""))[0]})
    order = {"hold": 0, "unread": 1, "live": 2, "empty": 3}
    rows.sort(key=lambda r: (order[r["state"]], 0 if r["last_state"] == "hold" else 1, r["name"]))
    found, missing = run.get("found") or [], run.get("missing") or []
    opened = sum(1 for r in rows if r["state"] != "unread")
    with_lookups = bool(ran.get("lookups", True))

    # ---------- pieces
    def esc(s):
        return html.escape(str(s))

    def pill(state, head):
        return '<span class="pill %s">%s</span>' % (state, esc(head))

    acc_rows = []
    for r in rows:
        dd = ("%.1f d" % r["days_down"]) if r["days_down"] else ("0" if r["ads"] else "—")
        ads_txt = ("%d ad%s" % (r["ads"], "" if r["ads"] == 1 else "s")) if r["ads"] else "no live ad on the sheet"
        sub = esc(r["detail"])
        if r["since"]:
            sub += '<br><span class="since">%s</span>' % esc(r["since"])
        acc_rows.append(
            '<div class="acc %s"><div class="acc-main"><div class="acc-name">%s <span class="ads">%s</span></div>'
            '<div class="acc-sub">%s</div></div><div class="acc-side">%s<div class="dd" title="Days Down on the live-ads sheet, this ad run">%s</div></div></div>'
            % (r["state"], esc(r["name"]), esc(ads_txt), sub, pill(r["state"], r["head"]), esc(dd)))

    # timeline Nov 16 00:00 -> Nov 26 00:00 (10 equal days)
    t0, t1 = dt.datetime(2026, 11, 16), dt.datetime(2026, 11, 26)
    span = (t1 - t0).total_seconds()

    def pct(d):
        return max(0.0, min(100.0, (d - t0).total_seconds() / span * 100))

    by_acct = {}
    for h in holds:
        by_acct.setdefault(h["account"], []).append(h)
    tl_order = sorted(by_acct, key=lambda a: (0 if a in open_hold else 1, a))
    tl_rows = []
    for a in tl_order:
        bars = []
        for h in by_acct[a]:
            f, u = _p(h["from"]), _p(h["until"]) if h["until"] else None
            if not f:
                continue
            end = u or now
            left, width = pct(f), max(0.6, pct(end) - pct(f))
            cls = "bar" + (" est" if h["estimated"] else "") + ("" if u else " open")
            hours = (end - f).total_seconds() / 3600
            dur = ("%.0f h" % hours) if hours < 48 else ("%.1f d" % (hours / 24))
            tip = "%s → %s (%s)%s" % (_when(f), _when(u) if u else "still on hold", dur,
                                           " · estimated" if h["estimated"] else "")
            bars.append('<div class="%s" style="left:%.2f%%;width:%.2f%%" title="%s">%s</div>'
                        % (cls, left, width, esc(tip), ("<span>%s</span>" % esc(dur)) if width >= 5 else ""))
        tl_rows.append('<div class="tl-row"><div class="tl-name" title="%s">%s</div><div class="tl-strip">%s</div></div>'
                       % (esc(a), esc(SHORT.get(a, a)), "".join(bars)))
    quiet = sorted(SHORT.get(n, n) for n in set(LIVE_ADS_NAME.get(t, t) for t in PROFILES) - set(by_acct))
    wall_from = _p(OCTO_WALL_FROM)
    wall_to = at if (at and opened) else now
    wall = '<div class="wall" style="left:%.2f%%;width:%.2f%%" title="Octo Browser would not open accounts: %s → %s"></div>' % (
        pct(wall_from), pct(wall_to) - pct(wall_from), esc(_when(wall_from)), esc(_when(wall_to)))
    now_line = '<div class="now" style="left:%.2f%%"><i>now</i></div>' % pct(now)
    ticks = "".join('<span style="left:%d%%">%s</span>' % (i * 10, (t0 + dt.timedelta(days=i)).strftime("%a<br>%-d"))
                    for i in range(0, 11, 2))
    grid = "".join('<i style="left:%d%%"></i>' % (i * 10) for i in range(0, 11))

    # the week's lookups
    week = list(WEEK)
    if with_lookups and run:
        week.append(("Wed 25", len(found), len(missing)))
    elif run:
        week.append(("Wed 25", 0, 6))
    mx = max((f + m) for _, f, m in week) or 1
    bars = []
    for lab, f, m in week:
        hf, hm = round(f / mx * 96), round(m / mx * 96)
        bars.append('<div class="wk"><div class="stack"><div class="miss" style="height:%dpx" title="%d not found"></div>'
                    '<div class="got" style="height:%dpx" title="%d found"></div></div><div class="n">%d<small>/%d</small></div><div class="l">%s</div></div>'
                    % (hm, m, hf, f, f, f + m, esc(lab)))

    found_names = ", ".join(sorted(set(x[0] if isinstance(x, list) else str(x) for x in found))) or "none"
    miss_items = []
    for x in missing:
        if isinstance(x, list) and len(x) >= 3:
            why = x[2]
            if why.startswith("could not start"):
                why = "account would not open"
            elif why == "not in list":
                why = "no longer on the candidate list under that name"
            miss_items.append("%s (%s): %s" % (esc(x[0]), esc(LIVE_ADS_NAME.get(x[1], x[1]).replace(".com", "")), esc(why)))
        else:
            miss_items.append(esc(x))

    run_line = ("%s · %s%s" % (_when(at), "phone lookups + billing" if with_lookups else "billing only",
                                      ((" · %.0f min" % run["elapsed_min"]) if run["elapsed_min"] >= 1 else " · under a minute") if run.get("elapsed_min") else "")
                if at else "no run read yet today")
    kick = ran.get("kick")
    run_note = ("Started by hand (Carlos, “try now”)" if kick else "The scheduled run") if run else ""
    release = ran.get("release") or ""
    if run.get("cut"):
        run_note += " · the tally row was cut, so Indeed email times are missing for some accounts"

    mails = run.get("billing_mail") or {}
    so = sorted(LIVE_ADS_NAME.get(t, t) for t, m in mails.items() if isinstance(m, dict) and m.get("signed_in") is False)
    unread = sorted(LIVE_ADS_NAME.get(t, t) for t in PROFILES if t not in mails)
    signed_out_line = ("Gmail is signed out in Octo for %s, so their hold times come from the checks, not the emails."
                       % (", ".join(so) if so else "no account"))
    if unread:
        signed_out_line += " Email times not carried for %s (the tally row was cut)." % ", ".join(unread)
    restart = ran.get("restart") or []
    restart_block = ""
    if restart:
        restart_block = ('<section><h2>What the run did about Octo\u2019s update</h2><ol class="steps">%s</ol></section>'
                         % "".join("<li>%s</li>" % esc(x) for x in restart))

    # ---------- page
    tiles = [("Live ads", counts["live"], "good"), ("Billing issue", counts["hold"], "bad"),
             ("No ads", counts["empty"], "na")]
    if counts["unread"]:
        tiles.append(("Not read", counts["unread"], "na"))
    tiles.append(("Numbers found", "%d<small>/%d</small>" % (len(found), len(found) + len(missing)) if with_lookups else "—", "acc"))
    tiles_html = "".join('<div class="tile %s"><div class="v">%s</div><div class="k">%s</div></div>' % (c, v, k)
                         for k, v, c in tiles)

    tpl = """<title>Indeed Account Check</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* layout: one quiet column; the figures first, the account list, the week's timeline, the lookups */
:root{--bg:#f3f5f8;--panel:#ffffff;--fg:#182230;--muted:#5b6778;--line:#dde3ea;--soft:#eef2f6;
 --accent:#0e7490;--good:#15803d;--good-bg:#e7f6ec;--bad:#b42318;--bad-bg:#fbeae7;--na:#667085;--na-bg:#eef1f5;
 --band:rgba(102,112,133,.16);--sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;--mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0e1319;--panel:#161c25;--fg:#e7ecf2;--muted:#98a4b3;--line:#273140;--soft:#1d2531;
 --accent:#38bdf8;--good:#4ade80;--good-bg:#12301d;--bad:#f87171;--bad-bg:#3a1a18;--na:#9aa5b4;--na-bg:#242c37;--band:rgba(154,165,180,.18);color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0e1319;--panel:#161c25;--fg:#e7ecf2;--muted:#98a4b3;--line:#273140;--soft:#1d2531;
 --accent:#38bdf8;--good:#4ade80;--good-bg:#12301d;--bad:#f87171;--bad-bg:#3a1a18;--na:#9aa5b4;--na-bg:#242c37;--band:rgba(154,165,180,.18);color-scheme:dark}
body{background:var(--bg);color:var(--fg);font-family:var(--sans);font-size:15px;line-height:1.45;
 padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-block:20px 48px}
main{max-width:760px;margin:0 auto;display:grid;gap:22px}
h1{font-size:1.45rem;font-weight:600;margin:0;letter-spacing:-.01em;text-wrap:balance}
h2{font-size:.78rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0 0 10px}
.sub{color:var(--muted);margin:4px 0 0;font-size:.95rem}
.sub b{color:var(--fg);font-weight:500}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
@media (max-width:520px){.tiles{grid-template-columns:repeat(2,1fr)}}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;min-width:0}
.tile .v{font-family:var(--mono);font-size:1.7rem;font-weight:500;line-height:1.1;font-variant-numeric:tabular-nums}
.tile .v small{font-size:.95rem;color:var(--muted);font-weight:400}
.tile .k{color:var(--muted);font-size:.82rem;margin-top:4px}
.tile.good .v{color:var(--good)}.tile.bad .v{color:var(--bad)}.tile.na .v{color:var(--na)}.tile.acc .v{color:var(--accent)}
section{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 16px 14px;min-width:0}
.acc{display:flex;gap:12px;align-items:flex-start;padding:10px 0;border-top:1px solid var(--line)}
.acc:first-of-type{border-top:0;padding-top:4px}
.acc-main{flex:1;min-width:0}
.acc-name{font-weight:600}
.acc-name .ads{font-weight:400;color:var(--muted);font-size:.82rem;margin-left:4px;white-space:nowrap}
.acc-sub{color:var(--muted);font-size:.88rem;margin-top:2px;overflow-wrap:anywhere}
.acc-sub .since{color:var(--fg)}
.acc.hold .acc-sub .since{color:var(--bad)}
.acc-side{display:flex;flex-direction:column;align-items:flex-end;gap:6px;flex-shrink:0}
.pill{font-size:.76rem;font-weight:600;letter-spacing:.02em;padding:3px 9px;border-radius:999px;white-space:nowrap;border:1px solid transparent}
.pill.live{color:var(--good);background:var(--good-bg)}
.pill.hold{color:var(--bad);background:var(--bad-bg)}
.pill.unread{color:var(--na);background:var(--na-bg)}
.pill.empty{color:var(--na);background:transparent;border-color:var(--line)}
.dd{font-family:var(--mono);font-size:.82rem;color:var(--muted);font-variant-numeric:tabular-nums}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;color:var(--muted);font-size:.8rem;margin-top:10px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;vertical-align:-1px;margin-right:6px}
.tl{display:grid;gap:6px;position:relative}
.tl-row{display:grid;grid-template-columns:96px 1fr;gap:10px;align-items:center}
@media (max-width:520px){.tl-row{grid-template-columns:78px 1fr}.tl-name{font-size:.78rem}}
.tl-name{font-size:.84rem;color:var(--fg);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tl-strip{position:relative;height:22px;background:var(--soft);border-radius:4px;overflow:visible}
.tl-strip .bar{position:absolute;top:3px;height:16px;background:var(--bad);border-radius:3px;color:#fff;font-family:var(--mono);font-size:.68rem;line-height:16px;padding-left:5px;white-space:nowrap;overflow:hidden;text-shadow:0 0 3px rgba(0,0,0,.75),0 0 1px rgba(0,0,0,.9)}
.tl-strip .bar.est{background:repeating-linear-gradient(135deg,var(--bad) 0 4px,color-mix(in srgb,var(--bad) 55%,transparent) 4px 8px)}
.tl-strip .bar.open{border-right:2px dashed var(--bad);border-radius:3px 0 0 3px}
.tl-chart{position:relative}
.tl-chart .grid{position:absolute;left:106px;right:0;top:0;bottom:0;pointer-events:none}
@media (max-width:520px){.tl-chart .grid{left:88px}}
.tl-chart .grid i{position:absolute;top:0;bottom:0;border-left:1px dashed var(--line)}
.tl-chart .wall{position:absolute;top:-4px;bottom:-4px;background:var(--band);border-radius:4px}
.tl-chart .now{position:absolute;top:-6px;bottom:-4px;border-left:2px solid var(--accent)}
.tl-chart .now i{position:absolute;top:-16px;left:-12px;font-style:normal;font-size:.68rem;color:var(--accent);font-family:var(--mono)}
.axis{position:relative;height:34px;margin-left:106px;font-family:var(--mono);font-size:.7rem;color:var(--muted);margin-top:14px}
@media (max-width:520px){.axis{margin-left:88px}}
.axis span{position:absolute;transform:translateX(-50%);text-align:center;line-height:1.2}
.axis span:first-child{transform:none}
.axis span:last-child{transform:translateX(-100%)}
.week{display:flex;gap:10px;align-items:flex-end;margin-top:6px}
.wk{flex:1;min-width:0;text-align:center}
.wk .stack{display:flex;flex-direction:column;justify-content:flex-end;height:100px;background:var(--soft);border-radius:4px;overflow:hidden}
.wk .got{background:var(--accent)}
.wk .miss{background:var(--na-bg);border-bottom:1px solid var(--line)}
.wk .n{font-family:var(--mono);font-size:.9rem;margin-top:6px;font-variant-numeric:tabular-nums}
.wk .n small{color:var(--muted);font-size:.72rem}
.wk .l{font-size:.72rem;color:var(--muted)}
ul,ol{margin:8px 0 0;padding-left:18px}
ol.steps li{font-family:var(--mono);font-size:.82rem;margin:3px 0;overflow-wrap:anywhere}
li{margin:4px 0;color:var(--fg)}
li small,.note{color:var(--muted)}
p{margin:6px 0}
.foot{color:var(--muted);font-size:.8rem}
</style>
<main>
<header>
 <h1>Indeed Account Check</h1>
 <p class="sub"><b>{{run_line}}</b> · office computer, Octo Browser{{release}}<br>{{run_note}}</p>
</header>
<div class="tiles">{{tiles}}</div>
<section>
 <h2>Accounts ({{n}}): {{with_ads}} with ads, {{empty}} with nothing posted · {{opened}} opened this run</h2>
 {{acc_rows}}
 <div class="legend"><span><i style="background:var(--good)"></i>Live: All Jobs page clean</span><span><i style="background:var(--bad)"></i>On hold: Indeed shows a payment alert</span><span><i style="background:var(--na)"></i>Not read this run</span><span><i style="border:1px solid var(--na);background:transparent"></i>No ads: nothing posted on the account</span><span>Right-hand number: Days Down on the live-ads sheet ({{ads_week}} block)</span></div>
</section>
<section>
 <h2>Billing holds, Nov 16 → today</h2>
 <div class="tl-chart">
  <div class="grid">{{grid}}{{wall}}{{now_line}}</div>
  <div class="tl">{{tl_rows}}</div>
  <div class="axis">{{ticks}}</div>
 </div>
 <div class="legend"><span><i style="background:var(--bad)"></i>On hold (from the Indeed emails)</span><span><i style="background:repeating-linear-gradient(135deg,var(--bad) 0 3px,transparent 3px 6px)"></i>Estimated (inbox unread)</span><span><i style="background:var(--band)"></i>Octo would not open accounts</span><span>Dashed end = still on hold</span></div>
 <p class="note">No holds since Nov 16: {{quiet}}.</p>
</section>
{{restart_block}}
<section>
 <h2>Phone lookups, 5am runs this week</h2>
 <div class="week">{{week}}</div>
 <p class="note">Found / looked up. Today’s bar is this run.</p>
 <p><b>Found today:</b> {{found_names}}</p>
 {{missing_block}}
</section>
<section>
 <h2>This week</h2>
 <ul>
  <li>Mon 5am: Octo Browser downloaded an update mid-run and refused every account until restarted. Nothing was read Mon 1pm, Tue 5am, Tue 1pm, or on the first try-now pass at 5:14pm. <small>Fixed on the second pass: the run quits Octo, has it install the update through Octo’s own API and carries on (Octo went 3.1.3 → 3.2.7 at 5:3x pm).</small></li>
  <li>Four “ads back live” DMs went out on their own: Ascendra and Peak (Fri 11/20), W Edge (Sat 11/21), Raw (Sun 11/22). Titanium and Haus holds opened Sun 11/22 off the Indeed emails.</li>
  <li>{{signed_out}}</li>
 </ul>
</section>
<p class="foot">Read off the office computer’s tally rows, the Billing Holds tab and the live-ads sheet at {{gathered}}. Phone numbers never appear here.</p>
</main>
"""
    vals = {
        "run_line": esc(run_line), "release": (" · release %s" % esc(release)) if release else "",
        "run_note": esc(run_note), "tiles": tiles_html, "n": len(rows), "opened": opened,
        "acc_rows": "".join(acc_rows), "with_ads": counts["live"] + counts["hold"], "empty": counts["empty"], "ads_week": esc(data.get("ads_week") or "newest"),
        "grid": grid, "wall": wall, "now_line": now_line, "tl_rows": "".join(tl_rows), "ticks": ticks,
        "quiet": esc(", ".join(quiet)), "week": "".join(bars), "found_names": esc(found_names),
        "missing_block": ("<p><b>Not found:</b></p><ul>%s</ul>" % "".join("<li>%s</li>" % m for m in miss_items)) if miss_items else "",
        "gathered": esc(_when(dt.datetime.fromisoformat(data["gathered"]))),
        "restart_block": restart_block,
        "signed_out": esc(signed_out_line),
    }
    for k, v in vals.items():
        tpl = tpl.replace("{{%s}}" % k, str(v))
    return tpl


if __name__ == "__main__":
    kick = sys.argv[1] if len(sys.argv) > 1 else ""
    if "--render-only" in sys.argv:
        data = json.loads(DATA.read_text())
    else:
        data = gather(kick)
    OUT.write_text(render(data))
    run = data.get("run") or {}
    print("run at", run.get("at"), "kick", (run.get("ran") or {}).get("kick"), "cut", run.get("cut"),
          "| holds", len(data["holds"]), "| wrote", OUT)
