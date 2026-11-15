"""Consumer tallies for a B2B office — OwnerVille CRU/IRU Engagement (p=164).

Jamis (Midspire, 2026-11-14): "is there a way to include consumer tallies?
It's new on b2b because these dispos only include business." They live on
OwnerVille → TeleMapper Leads → Reports → CRU/IRU Engagement → Consumer Tally,
which the page fills from ONE clean JSON call (found by consumer_tally_probe,
2026-11-15):

    components/telemapper/report_consumer.cfc?method=getConsumerTally
        &rqst=<session>&startDate=YYYY-MM-DD&endDate=YYYY-MM-DD

    {"data":{"reps":[{"name","repId","appts","locCount","flyCount",
                      "loc":{"c1".."c6"}, "fly":{"c1".."c6"}}, ...]}}

c1..c6 are the tab's columns in order (proven on Jason Suarez 11/14: page
row 3/2/1/0/0/0 == loc c1..c6). `loc` = "At business location", `fly` = "On
the fly"; the tab's Total row is their sum. `appts` = Appointments Set.

This module: the column names, the fetch (on an already-impersonated page),
a pull for one office (impersonate → pin campaign → fetch → exit), and the
two board shapes. CLI `--json` prints the normalised reps for one day so a
Lucy run can be read back through logdump.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ENDPOINT = "components/telemapper/report_consumer.cfc"

# c1..c6, in the Consumer Tally tab's own order.
TALLY_COLUMNS = ["Talk To", "Qualifying Questions", "Presentation", "Close",
                 "Sara Plus (Credit Check)", "Client Acq."]
COL_APPTS = "Appointments Set"
CONSUMER_PREFIX = "Consumer "


def _n(v) -> int:
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def normalise(payload: dict) -> list:
    """API payload -> [{rep, loc:{col:n}, fly:{col:n}, total:{col:n}, appts}]."""
    reps = ((payload or {}).get("data") or {}).get("reps") or []
    out = []
    for r in reps:
        loc = {c: _n((r.get("loc") or {}).get("c%d" % (i + 1)))
               for i, c in enumerate(TALLY_COLUMNS)}
        fly = {c: _n((r.get("fly") or {}).get("c%d" % (i + 1)))
               for i, c in enumerate(TALLY_COLUMNS)}
        out.append({"rep": (r.get("name") or "").strip(),
                    "rep_id": str(r.get("repId") or "").split(".")[0],
                    "loc": loc, "fly": fly,
                    "total": {c: loc[c] + fly[c] for c in TALLY_COLUMNS},
                    "appts": _n(r.get("appts"))})
    return [r for r in out if r["rep"]]


def fetch_on_page(page, rqst: str, day: dt.date) -> dict:
    """The raw JSON, fetched INSIDE the impersonated page (same cookies)."""
    host = re.match(r"https?://[^/]+", page.url).group(0)
    url = ("%s/%s?method=getConsumerTally&rqst=%s&startDate=%s&endDate=%s"
           % (host, ENDPOINT, rqst, day.isoformat(), day.isoformat()))
    return page.evaluate("""async (u) => {
        const r = await fetch(u, {credentials: 'include'});
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return await r.json();
    }""", url)


def pull(office: str, day: dt.date, campaign: str = "2") -> list:
    """Impersonate `office`, fetch its consumer tallies for `day`, exit."""
    from automations.shared.tableau_patchright import ownerville_session
    from automations.focus_office_att.aliases import alias_to_canonical, load_aliases
    from automations.focus_office_att.run_all_owners import (
        _navigate_to_office_access, _find_owner_and_impersonate, _exit_impersonation)
    from automations.focus_office_att.step5_fill_one_owner import page_rqst
    from automations.rashad_metrics.knocks_pull import assert_impersonating, _pin_campaign

    aliases = load_aliases()
    canonical = alias_to_canonical(office, aliases)
    with ownerville_session(verbose=False) as page:
        page.set_default_timeout(60_000)
        _exit_impersonation(page)
        if not _navigate_to_office_access(page):
            raise RuntimeError("Office Access (?p=901) did not load")
        try:
            rqst, reason = _find_owner_and_impersonate(page, canonical, aliases)
            if not rqst:
                raise RuntimeError("Couldn't impersonate %r: %s" % (canonical, reason))
            assert_impersonating(page, rqst, canonical, aliases, verbose=False)
            rqst = page_rqst(page) or rqst
            _pin_campaign(page, rqst, campaign, verbose=False)
            payload = fetch_on_page(page, rqst, day)
        finally:
            try:
                _exit_impersonation(page)
            except Exception:  # noqa: BLE001
                pass
    if not ((payload or {}).get("data") or {}).get("reps") and \
            "reps" not in ((payload or {}).get("data") or {}):
        raise RuntimeError("unexpected getConsumerTally answer: %r"
                           % (json.dumps(payload)[:300],))
    return normalise(payload)


# --- the two board shapes -----------------------------------------------------
def extra_columns(reps: list) -> dict:
    """Option B — {column: {rep: n}} for render_knocks_boards(extra_columns=):
    the 7 consumer totals (business location + on the fly)."""
    cols = {CONSUMER_PREFIX + c: {r["rep"]: r["total"][c] for r in reps}
            for c in TALLY_COLUMNS}
    cols[CONSUMER_PREFIX + COL_APPTS] = {r["rep"]: r["appts"] for r in reps}
    return cols


def render_board(day: dt.date, reps: list, out_dir: Path, *,
                 office: str = "") -> Path:
    """Option A — its own 'CONSUMER TALLY' image, laid out like OwnerVille's
    tab: one block per rep (At business / On the fly / Total), office total on
    top, reps ordered by total Talk To."""
    from PIL import Image, ImageDraw
    from automations.total_knocks import render as R

    font = getattr(R, "_font", None)
    def F(size, bold=False):
        if font:
            try:
                return font(size, bold=bold)
            except TypeError:
                return font(size)
        from PIL import ImageFont
        return ImageFont.load_default()

    heads = ["Rep", "Where"] + TALLY_COLUMNS + [COL_APPTS]
    widths = [300, 210] + [130] * len(TALLY_COLUMNS) + [140]
    reps = sorted(reps, key=lambda r: (-r["total"]["Talk To"],
                                       -sum(r["total"].values()), r["rep"]))
    tot = {c: sum(r["total"][c] for r in reps) for c in TALLY_COLUMNS}
    tot_appts = sum(r["appts"] for r in reps)

    rows = [("total", ["OFFICE TOTAL", "%d reps" % len(reps)]
             + [str(tot[c]) for c in TALLY_COLUMNS] + [str(tot_appts)])]
    for r in reps:
        rows.append(("loc", [r["rep"], "At business"]
                     + [str(r["loc"][c]) for c in TALLY_COLUMNS] + [str(r["appts"])]))
        rows.append(("fly", ["", "On the fly"]
                     + [str(r["fly"][c]) for c in TALLY_COLUMNS] + [""]))
        rows.append(("sum", ["", "Total"]
                     + [str(r["total"][c]) for c in TALLY_COLUMNS] + [str(r["appts"])]))

    pad, title_h, head_h, row_h = 24, 70, 64, 40
    W = sum(widths) + 2 * pad
    H = pad + title_h + head_h + row_h * len(rows) + pad
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    brand, dark, cream, line = (181, 82, 12), (61, 46, 37), (248, 243, 236), (220, 212, 200)
    d.rectangle([pad, pad, W - pad, pad + title_h], fill=brand)
    title = "CONSUMER TALLY — %s%s" % (
        (office.upper() + " — ") if office else "",
        "%s, %s %d, %d" % (day.strftime("%A"), day.strftime("%B"), day.day, day.year))
    d.text((pad + 16, pad + 18), title, fill="white", font=F(30, True))
    y = pad + title_h
    x = pad
    for h, w in zip(heads, widths):
        d.rectangle([x, y, x + w, y + head_h], fill=dark, outline=line)
        label = {"Qualifying Questions": "Qualifying\nQuestions",
                 "Sara Plus (Credit Check)": "Sara Plus\n(Credit Check)",
                 COL_APPTS: "Appointments\nSet"}.get(h, h)
        d.multiline_text((x + w / 2, y + head_h / 2), label,
                         fill="white", font=F(16, True), anchor="mm", align="center")
        x += w
    y += head_h
    for kind, vals in rows:
        fill = brand if kind == "total" else (cream if kind == "sum" else "white")
        color = "white" if kind == "total" else "black"
        bold = kind in ("total", "sum")
        x = pad
        for i, (v, w) in enumerate(zip(vals, widths)):
            d.rectangle([x, y, x + w, y + row_h], fill=fill, outline=line)
            if kind in ("loc", "fly", "sum") and i >= 2 and v == "0":
                c = (175, 175, 175)
            else:
                c = color
            d.text((x + w / 2, y + row_h / 2), v, fill=c,
                   font=F(17, bold or i == 0), anchor="mm")
            x += w
        y += row_h
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / ("consumer_tally_%s.png" % day.isoformat())
    img.save(out)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="b2b_metrics.consumer_tally")
    ap.add_argument("--office", default="Jamis Garay")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: yesterday)")
    ap.add_argument("--campaign", default="2")
    ap.add_argument("--json", action="store_true",
                    help="print the normalised reps as one JSON line")
    a = ap.parse_args(argv)
    day = (dt.date.fromisoformat(a.date) if a.date
           else dt.date.today() - dt.timedelta(days=1))
    reps = pull(a.office, day, a.campaign)
    print("[consumer-tally] %s %s — %d rep(s)" % (a.office, day, len(reps)), flush=True)
    for r in reps:
        print("  %-28s total %s appts %d" % (r["rep"], r["total"], r["appts"]), flush=True)
    if a.json:
        print("CONSUMER_TALLY_JSON " + json.dumps({"day": day.isoformat(),
                                                   "office": a.office, "reps": reps}),
              flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
