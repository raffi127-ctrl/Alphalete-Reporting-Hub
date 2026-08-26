"""Make the OwnerVille profile say exactly what Sterling ran the check under.

Megan 2026-08-26: "if the name isn't an exact match in OV from their sterling BG
check it's edited to match."

WHERE THIS SITS. The name gate fixes the CHECKLIST. This fixes OWNERVILLE, and
the two are not the same problem: the checklist can be right while OV still
holds the nickname somebody typed when the profile was made. OV is what Sterling
is fed from and what activations read, so a nickname sitting there is what starts
the email chain this whole build exists to kill.

WHO IT TOUCHES. Only people whose Sterling result we hold — a real background
check, run under a real legal name. No result, no opinion: this never renames
somebody on a hunch about their spelling.

WHAT COUNTS AS A MISMATCH. Case and spacing don't ("BIANCA MENDEZ" is Bianca
Mendez). A different name does, including a dropped middle or second surname —
"exact match" is Megan's bar and Sterling's spelling is the one that has to win,
because Sterling is where the legal name was typed by the applicant themselves.

WHAT IT REFUSES. Rep not in OV; two reps who could both be them; a profile page
that doesn't look like the one we expect. Each refusal is reported by name and
reason and the run carries on — renaming the wrong rep in OV is worse than
leaving a nickname in place, and it is the kind of wrong nobody notices until a
background check comes back under a name that isn't on any checklist.

STATUS: the rep lookup here is the one headshots and digi_docs already drive on
this page (the campaign walk, the short DataTables probes, the Show All widen).
The PROFILE page beyond it has not met a live run yet — this machine's OV
session is expired and a laptop cannot reseed one. So `edit_profile_name` logs
the page it landed on and the fields it found before it changes anything, and
`apply=False` is the default: the first pass on the mini reports what it saw
instead of clicking through a form nobody has looked at.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from automations.bg_check_sync.parse import norm
from automations.shared.name_case import titlecase_name

PROFILE_DIR = (Path(__file__).resolve().parents[1] / "uploaded"
               / ".browser_profile_bg_name")


class Refused(RuntimeError):
    """We stopped on purpose. A refusal always names its reason."""


@dataclass
class OVCheck:
    """One rep's OV name versus the name Sterling ran their check under."""
    sheet_name: str            # what the checklist calls them
    legal_first: str
    legal_last: str
    email: str = ""            # col G — the key we actually look them up by
    phone: str = ""            # col H — the key that works when the emails differ
    proof: str = ""            # how the OV row was identified: email/phone/name
    ov_name: str = ""          # what OV calls them, once we've looked
    campaign: str = ""
    action: str = ""           # 'match' | 'would-edit' | 'edited' | 'refused'
    reason: str = ""

    @property
    def legal_name(self) -> str:
        return f"{self.legal_first} {self.legal_last}".strip()


def _clean(name: str) -> str:
    """OV decorates the display name — 'Mendez, Bianca (9445955)' or a trailing
    pill — so strip the id and punctuation before comparing anything.

    LETTERS, not A-Z. An ASCII-only strip turned "Cruz Jiménez" into
    "Cruz Jim nez", so the name stopped matching ITSELF and Guadalupe Cruz
    Jiménez was reported as needing an edit to Guadalupe Cruz Jiménez
    (2026-08-26). Half this sheet's surnames carry an accent.
    """
    s = re.sub(r"\(.*?\)", " ", name or "")
    s = "".join(c if (c.isalpha() or c in " ,'-") else " " for c in s)
    return re.sub(r"\s+", " ", s).strip()


def split_display(name: str) -> tuple[str, str]:
    """OV shows either 'First Last' or 'Last, First'. Return (first, last)."""
    s = _clean(name)
    if "," in s:
        last, _, first = s.partition(",")
        return first.strip(), last.strip()
    parts = s.split()
    if len(parts) < 2:
        return s, ""
    return parts[0], " ".join(parts[1:])


def matches(ov_name: str, legal_first: str, legal_last: str) -> bool:
    """Is OV already saying exactly what Sterling ran?

    Compared as a whole normalized string in BOTH orders rather than field by
    field, because a two-word surname lands in whichever field the person
    entering it felt like using: OV's 'Monzon Martinez, Berenice' and Sterling's
    'Berenice Monzon Martinez' are the same human being spelled the same way.
    """
    first, last = split_display(ov_name)
    want = f"{norm(legal_first)} {norm(legal_last)}".strip()
    got = f"{norm(first)} {norm(last)}".strip()
    return bool(want) and want == got


def needs_edit(ov_name: str, legal_first: str, legal_last: str) -> bool:
    return bool(_clean(ov_name)) and not matches(ov_name, legal_first, legal_last)


# --- the browser half -------------------------------------------------------
# The page is "Sales Reps" (p=20), which is what Alphalete Marketing meant by
# "go to sales rep, find the name and click on it": each row's name links to
# p=21&pid=<rep id>, the edit form, whose name boxes are `fname` and `lname` and
# whose submit is "Save Changes". Verified live 2026-08-26.
#
# NOT View Progress (p=201), where this started. That table is the onboarding
# funnel and a hired rep is simply not in it -- the first probe walked all four
# campaigns for Bianca Mendez and found "no data available" every time.
#
# WE FIND PEOPLE BY EMAIL, NOT BY NAME. The rep list carries each rep's address
# and the OBCL carries the same one in col G, so the join is an exact string on
# both sides. That matters more here than anywhere else in this build: the whole
# problem is that names disagree between systems, so a name is precisely the
# wrong key to look somebody up by, and a near-twin ("Ana Gonzalez" /
# "Ana Griffin") would be a rename of the wrong human. Email is checked first,
# and a name lookup is only a fallback that must land on exactly one row whose
# surname agrees.

REP_LIST_P = 20
PROFILE_P = 21


def session(*, headless: bool = True, verbose: bool = True,
            allow_login: bool = False):
    """Our OWN browser profile. digi_docs and headshots drive OwnerVille on the
    same box; sharing a profile is the 2026-08-19 lock wedge.

    allow_login=True re-enables OwnerVille's login form. Note what that flag
    really does: it DRIVES the form with stored credentials, it does not wait
    for a person -- so on a laptop the working move is to sign in once in a
    window (the persistent profile below keeps it), not to pass this.
    """
    from automations.shared.tableau_patchright import ownerville_session
    return ownerville_session(headless=headless, verbose=verbose,
                              allow_form_login=allow_login,
                              profile_dir=PROFILE_DIR)


def open_rep_list(page, *, verbose: bool = True) -> str:
    """Load Sales Reps and return the session's rqst token."""
    from automations.b2b_dispositions.capture import capture_rqst
    rqst = capture_rqst(page)
    page.set_default_navigation_timeout(90000)
    page.goto(f"https://v2.ownerville.com/index.cfm?p={REP_LIST_P}&rqst={rqst}",
              wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=60000)
    except Exception:
        pass
    if verbose:
        print(f"  rep list loaded ({page.url.split('&rqst=')[0]})")
    return rqst


def _columns(page) -> dict:
    """{lowercased header: index} for the rep table.

    By label, never by position — the table has thirteen columns today and the
    day somebody adds one, index-based parsing starts reading phone numbers as
    surnames.
    """
    heads = [h.strip().lower() for h in page.locator("thead th").all_inner_texts()]
    return {h: i for i, h in enumerate(heads) if h}


def _search_rows(page, term: str) -> list:
    """Type `term` into the table's search box; return the rows that are real.

    DataTables answers an empty result with ONE row that says "No data available
    in table", so a row only counts if it carries a pid link.
    """
    box = page.locator("input[type='search']:visible").first
    box.wait_for(state="visible", timeout=20000)
    box.fill("")
    box.press_sequentially(term, delay=25)
    page.wait_for_timeout(1500)
    out = []
    rows = page.locator("tbody tr")
    for i in range(rows.count()):
        row = rows.nth(i)
        href = ""
        anchors = row.locator("a")
        for j in range(anchors.count()):
            h = anchors.nth(j).get_attribute("href") or ""
            if "pid=" in h:
                href = h
                break
        if href:
            out.append((row, href))
    return out


def _row_fields(page, row, cols: dict) -> dict:
    cells = row.locator("td").all_inner_texts()

    def cell(label: str) -> str:
        i = cols.get(label)
        return (cells[i].strip() if i is not None and i < len(cells) else "")

    return {"first": cell("first"), "last": cell("last"),
            "full": cell("full name"), "email": cell("email"),
            "phone": cell("phone"), "status": cell("status")}


def digits(phone: str) -> str:
    """Last ten digits — the checklist writes 19455363583, OwnerVille writes
    (945) 536-3583, and those are the same phone."""
    d = re.sub(r"\D", "", phone or "")
    return d[-10:] if len(d) >= 10 else ""


def _tokens(s: str) -> set:
    return {t for t in re.split(r"[^a-z0-9]+", norm(s)) if t}


def _part_agrees(got: str, want: str) -> bool:
    """One name part against another, forgiving a dropped half: OwnerVille's
    'Hernandez' agrees with Sterling's 'Hernandez Rodriguez'."""
    a, b = _tokens(got), _tokens(want)
    return bool(a and b and (a <= b or b <= a))


def identifies(fields: dict, check: "OVCheck") -> str:
    """How this row proves it is our person: 'email', 'name', or '' for not.

    Email first and email alone when it hits — it is the one field both systems
    hold verbatim. Names are the fallback and are checked against BOTH the
    checklist spelling and Sterling's, because either system can be the one
    holding the nickname (OwnerVille has Shuminique Valentine while the
    checklist says Nikki — the checklist is the wrong one there).
    """
    if check.email and fields.get("email"):
        if norm(check.email) == norm(fields["email"]):
            return "email"
    # Phone next, and it carries the same weight. The two systems can hold two
    # different addresses for one person — Nikki Valentine's checklist address
    # is Shuminiquevalentine@yahoo.com and her OwnerVille one is
    # Nikkivalentine93@yahoo.com — while the number is identical.
    if check.phone and fields.get("phone"):
        a, b = digits(check.phone), digits(fields["phone"])
        if a and a == b:
            return "phone"
    parts = check.sheet_name.split()
    candidates = []
    if parts:
        candidates.append((parts[0], " ".join(parts[1:])))
    candidates.append((check.legal_first, check.legal_last))
    for want_first, want_last in candidates:
        if not (want_first and want_last):
            continue
        if (_part_agrees(fields.get("first", ""), want_first)
                and _part_agrees(fields.get("last", ""), want_last)):
            return "name"
    return ""


def _probes(check: "OVCheck") -> list:
    """Single-token searches, best first.

    ONE TOKEN AT A TIME, never "First Last". The rep table filters on fields
    rather than the display string, so a full name filters to zero — searching
    "Carol Pena" finds nothing while "Carol" finds her. Same lesson headshots
    learned on the other OwnerVille table, relearned here on 2026-08-26.
    """
    out = []
    if check.email:
        out.append(check.email)
    if digits(check.phone):
        # The table renders (945) 536-3583, so search the seven-digit tail —
        # the part that survives whichever way either system punctuates it.
        out.append(digits(check.phone)[-7:])
    parts = check.sheet_name.split()
    if parts:
        out.append(parts[-1])          # surname is the most selective token
        if len(parts) > 1:
            out.append(parts[0])
    for tok in (check.legal_last or "").split() + [check.legal_first]:
        if tok:
            out.append(tok)
    seen, uniq = set(), []
    for t in out:
        k = norm(t)
        if k and k not in seen:
            seen.add(k)
            uniq.append(t)
    return uniq


def find_rep_row(page, cols: dict, check: "OVCheck", *, verbose: bool = True):
    """(row, href, fields) for this person, or a Refused explaining why not.

    Every probe's rows are judged by `identifies`, and the candidates are
    collected by rep id across probes. Exactly one id survives or we refuse:
    renaming the wrong rep is worse than leaving a nickname in place.
    """
    found: dict = {}
    for probe in _probes(check):
        for row, href in _search_rows(page, probe):
            fields = _row_fields(page, row, cols)
            how = identifies(fields, check)
            if not how:
                continue
            m = re.search(r"[?&]pid=(\d+)", href or "")
            pid = m.group(1) if m else href
            # Email or phone is proof of WHO, not a name resemblance. Keep it
            # and stop looking.
            if how in ("email", "phone"):
                check.proof = how
                return row, href, fields
            found.setdefault(pid, (row, href, fields))
        if len(found) > 1:
            break
    if not found:
        raise Refused(f"{check.sheet_name}: not in OwnerVille's Sales Reps list"
                      + (f" (searched {check.email})" if check.email else ""))
    if len(found) > 1:
        who = ", ".join(f"{f['first']} {f['last']}" for _, _, f in found.values())
        raise Refused(f"{check.sheet_name}: {len(found)} OwnerVille reps could be "
                      f"them ({who}) — refusing to guess")
    check.proof = "name"
    return next(iter(found.values()))


def profile_url(href: str, rqst: str) -> str:
    """The edit page for the rep whose row link is `href`."""
    m = re.search(r"[?&]pid=(\d+)", href or "")
    if not m:
        raise Refused(f"no rep id in the OwnerVille row link ({href!r})")
    return (f"https://v2.ownerville.com/index.cfm?p={PROFILE_P}"
            f"&rqst={rqst}&pid={m.group(1)}")


def _name_inputs(page) -> tuple:
    """The profile form's first/last boxes — `fname` and `lname` live.

    Matched on the field's own name/id/placeholder rather than position: this
    form has twenty-three inputs and the two we want are the two that say what
    they are.
    """
    first = last = None
    inputs = page.locator("input:visible")
    for i in range(inputs.count()):
        el = inputs.nth(i)
        ident = " ".join(filter(None, [
            el.get_attribute("name") or "", el.get_attribute("id") or "",
            el.get_attribute("placeholder") or "",
        ])).lower()
        if not ident:
            continue
        if first is None and re.search(r"\bf(irst)?[_\s-]?name\b|\bfname\b", ident):
            first = el
        elif last is None and re.search(r"\bl(ast)?[_\s-]?name\b|\blname\b", ident):
            last = el
    return first, last


def edit_profile_name(page, check: "OVCheck", *, apply: bool = False,
                      verbose: bool = True) -> "OVCheck":
    """Set the profile's name to Sterling's. Reports before it writes."""
    first_in, last_in = _name_inputs(page)
    if first_in is None or last_in is None:
        found = ", ".join(n for n, el in (("first", first_in), ("last", last_in)) if el)
        raise Refused(f"{check.sheet_name}: profile page has no first/last name "
                      f"fields we recognise (found: {found or 'none'})")
    current = f"{first_in.input_value()} {last_in.input_value()}".strip()
    if matches(current, check.legal_first, check.legal_last):
        check.action, check.reason = "match", f"OV already says {current}"
        return check
    check.reason = f"{current or '(blank)'} -> {check.legal_name}"
    if not apply:
        check.action = "would-edit"
        if verbose:
            print(f"    WOULD set {check.reason}")
        return check
    first_in.fill(titlecase_name(check.legal_first))
    last_in.fill(titlecase_name(check.legal_last))
    from automations.headshots.ov_upload import _click_any
    _click_any(page, "Save Changes", page=page)
    page.wait_for_load_state("networkidle")
    check.action = "edited"
    if verbose:
        print(f"    set {check.reason}")
    return check


def sync_names(people: list, *, apply: bool = False, headless: bool = True,
               verbose: bool = True, allow_login: bool = False) -> list:
    """Walk a list of OVCheck targets. One session, one rep at a time.

    Never raises for one rep: a refusal is recorded on that rep and the walk
    carries on, so one missing profile can't cost the other twenty their fix.
    """
    results: list = []
    if not people:
        return results
    # Entered by hand rather than with a `with`, because the session only fails
    # on __enter__ (an expired storage state) and that failure has to become a
    # refusal on every target instead of an exception out of this function.
    browser = session(headless=headless, verbose=verbose, allow_login=allow_login)
    try:
        page = browser.__enter__()
    except Exception as e:  # noqa: BLE001
        why = f"no OwnerVille session: {str(e).splitlines()[0][:160]}"
        for check in people:
            check.action, check.reason = "refused", why
        if verbose:
            print(f"  REFUSED all {len(people)}: {why}")
        return list(people)
    try:
        rqst = open_rep_list(page, verbose=verbose)
        cols = _columns(page)
        for check in people:
            try:
                row, href, fields = find_rep_row(page, cols, check, verbose=verbose)
                check.ov_name = (f"{fields['first']} {fields['last']}".strip()
                                 or fields["full"])
                if matches(check.ov_name, check.legal_first, check.legal_last):
                    check.action = "match"
                    check.reason = f"OV already says {check.ov_name}"
                    results.append(check)
                    continue
                # Only now is a page load worth it — the list row already told
                # us the name, so a rep who is fine costs one search, not two
                # navigations.
                page.goto(profile_url(href, rqst), wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle")
                results.append(edit_profile_name(page, check, apply=apply,
                                                 verbose=verbose))
                open_rep_list(page, verbose=False)   # back to the list for the next one
            except Refused as e:
                check.action, check.reason = "refused", str(e)
                results.append(check)
                if verbose:
                    print(f"  REFUSED {e}")
            except Exception as e:  # noqa: BLE001
                check.action = "refused"
                check.reason = f"{type(e).__name__}: {str(e).splitlines()[0][:120]}"
                results.append(check)
                if verbose:
                    print(f"  REFUSED {check.sheet_name}: {check.reason}")
    finally:
        try:
            browser.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass
    return results


def summarise(results: list) -> str:
    buckets: dict[str, list] = {}
    for r in results:
        buckets.setdefault(r.action or "?", []).append(r)
    parts = []
    for action in ("edited", "would-edit", "match", "refused"):
        rs = buckets.get(action)
        if rs:
            parts.append(f"{len(rs)} {action}")
    return ", ".join(parts) or "nothing to do"


# --- proving identity instead of asking about it ----------------------------
# The gate asks a human because a shared surname is not proof. OwnerVille can
# often supply the proof it is missing: it holds the rep's phone and email
# alongside their name, so when the checklist row and an OV profile share a
# NUMBER, and that profile's name is exactly what Sterling ran, the chain is
# closed without anybody guessing:
#
#     checklist row --same phone--> OwnerVille profile --same name--> Sterling
#
# That is the Nikki Valentine case exactly: her two systems hold two different
# email addresses, the same phone number, and OwnerVille already spells her
# Shuminique Valentine. Nothing about that needs a human to confirm it.
#
# Anything the chain does NOT close still goes to the channel. Proof shrinks the
# asking; it never replaces it.

def prove(people: list, *, headless: bool = True, verbose: bool = True,
          allow_login: bool = False) -> dict:
    """{sheet_name: (proven, why)} — does OwnerVille confirm this rename?

    Proven needs BOTH halves: the OV row identified by email or phone (a name
    lookup proves nothing here — the name is the thing in dispute), and that
    row's name matching Sterling's exactly.
    """
    out: dict = {}
    if not people:
        return out
    browser = session(headless=headless, verbose=verbose, allow_login=allow_login)
    try:
        page = browser.__enter__()
    except Exception as e:  # noqa: BLE001
        why = f"OwnerVille unreachable: {str(e).splitlines()[0][:120]}"
        return {c.sheet_name: (False, why) for c in people}
    try:
        rqst = open_rep_list(page, verbose=verbose)
        cols = _columns(page)
        for check in people:
            try:
                _row, _href, fields = find_rep_row(page, cols, check, verbose=verbose)
            except Refused as e:
                out[check.sheet_name] = (False, str(e))
                continue
            except Exception as e:  # noqa: BLE001
                out[check.sheet_name] = (False, f"{type(e).__name__}: {e}")
                continue
            ov_name = f"{fields['first']} {fields['last']}".strip()
            if check.proof not in ("email", "phone"):
                out[check.sheet_name] = (
                    False, f"OwnerVille row {ov_name!r} only matched on the name")
                continue
            if matches(ov_name, check.legal_first, check.legal_last):
                out[check.sheet_name] = (
                    True, f"same {check.proof} as OwnerVille's {ov_name!r}, "
                          f"which is exactly what Sterling ran")
            else:
                out[check.sheet_name] = (
                    False, f"OwnerVille says {ov_name!r}, Sterling ran "
                           f"{check.legal_name!r}")
    finally:
        try:
            browser.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass
    return out
