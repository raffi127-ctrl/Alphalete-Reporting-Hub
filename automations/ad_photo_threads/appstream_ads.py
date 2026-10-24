"""The ad a 1st-round candidate applied to, read off their AppStream record.

Eve 10/24 ("si"): the offices applicant_tracker doesn't import (Drew, Jairo,
Valeria, Colten, George...) had ~70 interviews in a week with a blank Ad Title
in the sheet and in Slack, and nobody answered the channel notes. The ad is
still on each applicant's record: AppStream keeps the Indeed mail it came in
on, "[Action required] New application for <ad>, <City>, <ST>" (the same text
oat_processing's read_posting_title reads).

READ-ONLY on AppStream: the console's global search by last name, open the
match, read the page, go back. Nothing on the record is touched.

What a lookup found is kept in the state file (state[channel]["appstream_ads"],
{"YYYY-MM-DD|name": ad text or ""}) so collect.build can use it on every later
pass without opening AppStream again; "" = looked, nothing usable (not asked
twice).
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from typing import Dict, List, Optional, Tuple

_APPLIED = re.compile(r"new application for\s*[:\-]?\s*(.+)", re.I)
# Where the mail subject ends on the record ("... Frisco, TX  10/21/2026 ...").
_TAIL = re.compile(r"\s{2,}|\s+\d{1,2}/\d{1,2}/\d{2,4}\b.*$")


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]+", " ", s.lower())).strip()


def key(day: dt.date, name: str) -> str:
    return f"{day.isoformat()}|{name.strip().lower()}"


def ads_in_text(text: str) -> List[str]:
    """Every "New application for <ad>" on a record page, the ad text only."""
    out = []
    for line in (text or "").splitlines():
        m = _APPLIED.search(" ".join(line.split()))
        if not m:
            continue
        ad = _TAIL.sub("", m.group(1)).strip(" .,-")
        if len(ad) > 3 and ad not in out:
            out.append(ad)
    return out


def split_name(name: str) -> Tuple[str, str]:
    parts = _fold(name).split()
    if not parts:
        return "", ""
    return parts[0], parts[-1] if len(parts) > 1 else ""


_RESULTS_JS = """(args) => {
    const [f, l] = args;
    const fold = s => (s || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g, '')
        .toLowerCase().replace(/[^a-z ]+/g, ' ');
    const out = [];
    document.querySelectorAll('a').forEach((e, i) => {
        const t = fold(e.innerText);
        if (t.length < 80 && t.includes(l) && (!f || t.includes(f)))
            out.push(i);
    });
    return out; }"""


def _search(page, last: str) -> None:
    if page.locator("input[name='globalSrchFor']").count() == 0:
        raise RuntimeError(f"no search box on {page.url[:90]}")
    page.fill("input[name='globalSrchFor']", last, timeout=8000)
    for sel in ("#glblSrchSbmt", "input[name='glblSrchSbmt']",
                "xpath=//input[@value='Go']"):
        b = page.locator(sel).first
        if b.count() > 0:
            b.click(timeout=5000, no_wait_after=True)
            break
    else:
        page.press("input[name='globalSrchFor']", "Enter")
    page.wait_for_timeout(3500)


def _page_text(page) -> str:
    out = []
    for fr in list(page.frames):
        try:
            out.append(fr.evaluate("() => document.body ? document.body.innerText : ''") or "")
        except Exception:  # noqa: BLE001
            continue
    return "\n".join(out)


def lookup(page, home_url: str, name: str, max_open: int = 3,
           debug: bool = False) -> Tuple[List[str], str]:
    """(ads found, how) for one candidate in the office already selected.
    `home_url` = the console page with the search box, reloaded before each
    search so one bad page can't leak into the next name."""
    first, last = split_name(name)
    if not last:
        return [], "one-word name, not searched"

    def results():
        """Search from a fresh console; [(frame, link index)] naming them.
        The results page is a POST, so each record opens off a new search."""
        page.goto(home_url, timeout=60000)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(1500)
        _search(page, last)
        out = []
        for fr in list(page.frames):
            try:
                out += [(fr, i) for i in fr.evaluate(_RESULTS_JS, [first, last])]
            except Exception:  # noqa: BLE001
                continue
        return out

    hits = results()
    if debug:
        print(f"    [{name}] search '{last}': {len(hits)} result link(s) with both names "
              f"| page: {page.url[:90]} | frames: {len(page.frames)}")
        if not hits:
            near = [ln.strip()[:100] for ln in _page_text(page).splitlines()
                    if last in _fold(ln)][:6]
            print(f"      lines with '{last}': {near or 'none'}")
    if not hits:
        return [], "no search result"
    ads: List[str] = []
    for n in range(min(len(hits), max_open)):
        if n:
            hits = results()
            if n >= len(hits):
                break
        fr, idx = hits[n]
        fr.locator("a").nth(idx).click(timeout=8000, no_wait_after=True)
        page.wait_for_timeout(3000)
        text = _page_text(page)
        found = ads_in_text(text)
        if debug:
            near = [ln.strip() for ln in text.splitlines()
                    if re.search(r"application|position|applied|job", ln, re.I)][:6]
            print(f"      record {n + 1}: ads={found} | lines: {near}")
        ads += [a for a in found if a not in ads]
    return ads, f"{len(hits)} record(s)"


def run(office_key: str, day: dt.date, *, names: Optional[List[str]] = None,
        apply: bool = False, limit: Optional[int] = None, debug: bool = True,
        lookback: Optional[int] = None, cache: Optional[dict] = None) -> Dict[str, object]:
    """Look up the office's interviews still on no thread (unthreaded.find).
    Prints what it finds; with `apply` keeps it in the state file."""
    from automations.ad_photo_threads import collect, config, post, unthreaded
    from automations.indeed_source_report import fetch
    from automations.shared.tableau_patchright import appstream_direct_session

    o = config.office(office_key)
    config.use(o)
    if lookback:
        unthreaded.LOOKBACK_DAYS = lookback
    cache = {} if cache is None else cache
    todo = [(d, c) for d, c in unthreaded.find(day, cache=cache)
            if collect.blank_title(c.title_raw)]
    if names:
        want = {n.strip().lower() for n in names}
        todo = [(d, c) for d, c in todo if c.name.strip().lower() in want]
    channel = o["live_channel"]
    state = post._load_state()
    done = (state.get(channel) or {}).get("appstream_ads") or {}
    todo = [(d, c) for d, c in todo if key(d, c.name) not in done]
    if limit:
        todo = todo[:limit]
    print(f"[appstream ads] {office_key}: {len(todo)} candidate(s) to look up"
          + ("" if apply else " (dry run: nothing saved)"))
    if not todo:
        return {"looked": 0, "found": 0}
    oids = [s["office_id"] for s in config.SOURCES if s.get("office_id")]
    got: Dict[str, str] = {}
    with appstream_direct_session(headless=True, verbose=False) as page:
        tok = fetch.token(page)
        fetch.select_office(page, tok, oids[0])
        home = page.url
        if debug:
            box = page.locator("input[name='globalSrchFor']").count() > 0
            print(f"  office {oids[0]} selected, owner={fetch.owner_name(page)!r}, "
                  f"search box: {box}")
        for d, c in todo:
            try:
                ads, how = lookup(page, home, c.name, debug=debug)
            except Exception as e:  # noqa: BLE001 -- one name never stops the rest
                print(f"  {c.name} ({d:%m/%d}): lookup failed: {type(e).__name__}: {str(e)[:120]}")
                continue
            one = ads[0] if len(ads) == 1 else ""
            got[key(d, c.name)] = one
            print(f"  {c.name} ({d:%m/%d}): {ads or '-'}  [{how}]"
                  + ("" if one or not ads else "  -> 2+ ads, left for the channel"))
    if apply and got:
        state = post._load_state()
        state.setdefault(channel, {}).setdefault("appstream_ads", {}).update(got)
        post._save_state(state)
    return {"looked": len(got), "found": sum(1 for v in got.values() if v)}
