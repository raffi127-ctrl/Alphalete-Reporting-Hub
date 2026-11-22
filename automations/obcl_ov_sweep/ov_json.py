"""Read View Progress from the endpoint that fills it, not from the table.

WHY (2026-11-21). The sweep read the rendered table and got 24 rows where the
table itself said 139, then spent ~20s per person asking the search box about
each of the other 115 -- a 504s run that still reported two dozen people "not
found in OwnerVille". Four of a six-person sample were in fact there. The
rendered table is the problem, and every route into it is a dead end:

  * the length menu reads 100 while the table shows 25, and setting it changes
    nothing -- its largest option is 100 anyway, and there are 139 people;
  * a real trusted click on the page-2 anchor leaves the table on page 1
    (three earlier attempts at a Next-walk found the same, ownerville.py:268);
  * the API that would settle it is unreachable -- window.jQuery is undefined
    from our evaluate because patchright runs scripts in an isolated world;
  * the read is flaky even at 24: one attempt came back with 0 rows.

The table is drawn from ONE request, which carries every row:

    GET /components/onboard/onboard_setupStatus.cfc
        ?method=getStatus&rqst=<token>&bid=<programme>&rtid=0&showall=0

The search box fires that same request unchanged, so the filtering was always
client-side over a payload we can simply read: 139 active records, among them
every person the sweep could not find. One request replaces the scrape AND the
115 searches.

`showall` is NOT "show all the columns" -- 0 is the active roster (139) and 1
adds 36 records with active=0, people who have been retired. The page sends 0
and so do we: a retired rep must not collect ticks.

COLUMN ORDER IS READ, NEVER ASSUMED. A record is keyed by step id (`type_155`),
and the ids are not in column order, not contiguous, and differ per programme
-- the same page served with no `bid` lists type_2788..2796. So the order comes
from the columns array in the page that renders the table, paired with that
page's own headers. The sweep's judging functions then see exactly the
heads/cells shape the scrape used to hand them, and none of them change.
"""
from __future__ import annotations

import html as _html
import json
import re
from typing import Dict, List, Tuple

STATUS_CFC = "/components/onboard/onboard_setupStatus.cfc"

# Every row of the active roster. See the module docstring on showall.
_FETCH_JS = """async ([rqst, bid]) => {
  const url = '%s?method=getStatus&rqst=' + encodeURIComponent(rqst)
            + '&bid=' + encodeURIComponent(bid) + '&rtid=0&showall=0';
  const r = await fetch(url, {credentials: 'include'});
  return {status: r.status, body: await r.text()};
}""" % STATUS_CFC

# The columns array the page builds its DataTable from, in column order.
_COL_RE = re.compile(r"""['"]?data['"]?\s*:\s*['"]([A-Za-z_0-9]+)['"]""")

_TAG_RE = re.compile(r"<[^>]+>")


def _text_of(markup: str) -> str:
    """innerText, near enough for the judging functions.

    They look for a pill's words ("Photo", "Approved", "In SARA Plus") and for
    a bare id, all of which survive tag-stripping. `cell_filled` and friends
    read the html too, and that is passed through untouched.

    ENTITIES MUST BE UNESCAPED. The served header is "AT&amp;T UID Request"
    where the browser reports "AT&T UID REQUEST"; header_index lowercases but
    does not decode, so leaving the entity in place made every lookup miss and
    done_columns answered None for all 20 columns -- which reads as "we could
    not see this person's row", for all 139 of them.
    """
    return " ".join(_html.unescape(_TAG_RE.sub(" ", markup or "")).split())


def column_keys(page_html: str) -> List[str]:
    """The record keys, in the order their columns appear."""
    return _COL_RE.findall(page_html or "")


def headers(page_html: str) -> List[str]:
    """The table's own header labels, from the served HTML.

    Not from the rendered thead: the table may not have drawn yet, and this
    read must not depend on it having done so.
    """
    m = re.search(r"<thead[^>]*>(.*?)</thead>", page_html or "",
                  re.S | re.I)
    if not m:
        return []
    return [_text_of(th) for th in
            re.findall(r"<th[^>]*>(.*?)</th>", m.group(1), re.S | re.I)]


def bid_for(page, campaign: str):
    """The programme's id, read off the campaign picker by its label.

    The id is what getStatus keys on and it is NOT guessable: RES-AT&T is 19
    on this login. Taken from the dropdown rather than written down here, for
    the same reason every other lookup in this repo goes by label -- an ICD on
    a different programme gets theirs from their own dropdown.
    """
    want = (campaign or "").strip().lower()
    opts = page.evaluate(
        """() => {
             const s = document.querySelector("select[name='bid']");
             if (!s) return [];
             return [...s.options].map(o => [o.value, (o.textContent || '').trim()]);
           }""")
    for value, label in opts:
        if label.strip().lower() == want:
            return value
    for value, label in opts:
        if want and want in label.strip().lower():
            return value
    raise RuntimeError("no %r programme in the picker; it offers: %s"
                       % (campaign, ", ".join(l for _, l in opts) or "nothing"))


def rep_name(rec: dict) -> str:
    """What this record calls the person.

    fname/lname, not the NAME cell: that cell is a block of markup carrying
    the person's id, an Edit link and the Action menu.
    """
    return ("%s %s" % (rec.get("fname") or "",
                       rec.get("lname") or "")).strip()


def cells_for(rec: dict, keys: List[str], width: int) -> List[dict]:
    """One record as the {text, html} cells the judging functions expect."""
    out = []
    for i in range(width):
        key = keys[i] if i < len(keys) else None
        raw = rec.get(key) if key else ""
        if raw is None:
            raw = ""
        elif not isinstance(raw, str):
            raw = str(raw)
        out.append({"text": _text_of(raw), "html": raw})
    return out


def fetch_records(page, rqst: str, bid) -> List[dict]:
    """The active roster for one programme.

    Fetched from inside the page: an APIRequestContext.get of this URL dies on
    "Header overflow" -- ColdFusion answers with more header than the node
    parser will take. The browser has no such trouble, and it already holds
    the session.
    """
    got = page.evaluate(_FETCH_JS, [rqst, str(bid)])
    if got.get("status") != 200:
        raise RuntimeError("getStatus answered HTTP %s" % got.get("status"))
    body = got.get("body") or ""
    try:
        data = json.loads(body)
    except ValueError:
        # A sign-in page or an error page, not the roster. Say which, with
        # enough of it to recognise, rather than "not JSON".
        raise RuntimeError("getStatus did not answer JSON (%d bytes, starts %r)"
                           % (len(body), body[:120]))
    recs = data.get("data") if isinstance(data, dict) else data
    if not isinstance(recs, list):
        raise RuntimeError("getStatus JSON has no record list (keys: %s)"
                           % (list(data)[:8] if isinstance(data, dict) else "-"))
    return recs


def read(page, *, bid, page_html: str,
         verbose: bool = True) -> Tuple[List[str], Dict[str, list], bool]:
    """(headers, {name: cells}, complete) -- the whole roster, one request.

    `complete` is True because the payload IS the roster: there is no page 2
    to have missed and no "of N entries" to fall short of. That matters to the
    caller, which only dares untick a box on a complete read.
    """
    from automations.b2b_dispositions.capture import capture_rqst

    heads = headers(page_html)
    keys = column_keys(page_html)
    if not heads or not keys:
        raise RuntimeError("View Progress served no %s"
                           % ("headers" if not heads else "columns array"))
    if len(keys) != len(heads):
        # Mapping by position only means anything if the two agree. Refuse
        # rather than tick boxes one column out.
        raise RuntimeError(
            "View Progress has %d headers but %d columns -- refusing to map "
            "them by position" % (len(heads), len(keys)))

    recs = fetch_records(page, capture_rqst(page), bid)
    reps: Dict[str, list] = {}
    for rec in recs:
        name = rep_name(rec)
        if name:
            reps[name] = cells_for(rec, keys, len(heads))
    if verbose:
        print("  View Progress (bid=%s, getStatus): %d of %d records"
              % (bid, len(reps), len(recs)), flush=True)
    return heads, reps, True
