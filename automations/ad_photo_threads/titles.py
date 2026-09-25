"""One ad, many spellings — folding the interviewers' typed titles onto one ad.

The "Ad Title" column is pasted/typed by the interviewers, so a single Indeed
ad shows up several ways (three weeks of Raf's tab, 2026-09-21: 190 raw
spellings, ~35 real ads):

    AT&T Sales Agent, Arlington, TX,
    AT&T Sales Agent ? Arlington TX          <- ApplicantStream's "–" mangled
    New application for AT&T Sales Agent, Arlington, TX,
    AT&T Sales Agent, Arlington, T           <- cut off mid-paste
    AT&T Erollment Associate, Denton, TX     <- typo

Two steps, both deliberately conservative:

  1. `norm` drops what is never meaningful: case, punctuation, the "?"/","
     separators, a leading "New application for".
  2. `TitleBook` learns the running ads from the sheet itself (a spelling seen
     at least MIN_SEEN times is an ad) and folds a rarer spelling onto one of
     them only when it is a cut-off of exactly ONE ad, or a near-identical
     typo of one. "AT&T Wireless Associate (Spanish)" is a cut-off of BOTH the
     Frisco and the "2 locations" ad, so it stays unresolved instead of being
     guessed into either.
"""
from __future__ import annotations

import difflib
import re
from collections import Counter
from typing import Dict, Iterable, List, Optional

MIN_SEEN = 3          # a spelling seen this often in the lookback is an ad
TYPO_RATIO = 0.92     # difflib ratio that counts as the same ad mistyped
MIN_PREFIX = 12       # shorter cut-offs ("at&t role") say too little to fold

_LEAD_JUNK = re.compile(r"^\s*(new application for|indeed\s*/)\s*", re.I)


# The company tacked on at the end (Carlos 9/23: "Event Marketing & Sales
# Assistant (Spanish Needed) – 2 locations – Vantura Acquisition" got a thread
# next to "..., 2 locations" -- same ad). Only names ending in Acquisition(s) /
# Inc / LLC, one word before it (the company's name): "Marketing" and
# "Management" also end real ad titles, so they stay.
# Plus company names seen pasted on their own, cut before "Acquisition"
# (Carlos 9/23: "... (Spanish Needed) – Ft Worth TX – Vantura").
# Khalil 9/24: "– Everforward Management" / "– Everforward" (his company) and
# "– Confidential" (what Indeed shows for a hidden company). Longest first.
KNOWN_COMPANIES = ("everforward management", "everforward", "confidential", "vantura")
_TAIL_COMPANY = re.compile(
    r"(?:\s+[a-z0-9&]+\s+acquisitions?(?:\s+inc)?|\s+(?:inc|llc)"
    r"|\s+(?:" + "|".join(KNOWN_COMPANIES) + r"))$")


def norm_keep_company(title: str) -> str:
    """`norm` as it was before 9/23: the company tail stays. The keys saved
    in state before then were made this way (--merge-dups needs it)."""
    t = (title or "").replace("&amp;", "&").replace("·", " ").lower()
    t = _LEAD_JUNK.sub("", t)
    t = t.replace("entry-level", "entry level")
    t = re.sub(r"[^a-z0-9&()]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def norm(title: str) -> str:
    t = norm_keep_company(title)
    return _TAIL_COMPANY.sub("", t).strip() or t


def pretty(title: str) -> str:
    """How a title is SHOWN: the interviewers' spelling, minus the paste junk."""
    t = (title or "").replace("&amp;", "&")
    t = _LEAD_JUNK.sub("", t)
    t = re.sub(r"\s+\?\s+", " – ", t)
    t = re.sub(r"\s+", " ", t).strip(" ,")
    return t


def _other_city(a: str, b: str) -> bool:
    """Same title, same state, a DIFFERENT city: two ads, not a typo. 9/25
    Isaiah: "... irving tx" vs "... garland tx" scored 0.93 and the merge
    moved Irving's people into the Garland thread. A typo bends letters
    ("arlingotn"); it doesn't swap the city."""
    wa, wb = a.split(), b.split()
    if not (wa and wb and wa[-1] == wb[-1] and len(wa[-1]) == 2 and wa[-1].isalpha()):
        return False
    p = 0
    while p < min(len(wa), len(wb)) - 1 and wa[p] == wb[p]:
        p += 1
    ca, cb = " ".join(wa[p:-1]), " ".join(wb[p:-1])
    return bool(ca and cb) and difflib.SequenceMatcher(None, ca, cb).ratio() < 0.75


class TitleBook:
    """The running ads, learned from the sheet's own title column."""

    def __init__(self, titles: Iterable[str],
                 aliases: Optional[Dict[str, str]] = None):
        # Office-confirmed equivalences, {spelling: the ad it is} (config
        # TITLE_ALIASES; Colten's team 9/24 sent their live ad list, so the
        # title typed without its city folds onto the one ad with that title).
        self.aliases = {norm(a): norm(b) for a, b in (aliases or {}).items()
                        if norm(a) and norm(b)}
        raw = [t for t in titles if norm(t)]
        self.counts: Counter = Counter(self.aliases.get(norm(t), norm(t)) for t in raw)
        # Most common raw spelling per key — that is what gets displayed.
        spellings: Dict[str, Counter] = {}
        for t in raw:
            if norm(t) in self.aliases:
                continue          # show the ad the way its own title is typed
            spellings.setdefault(norm(t), Counter())[t.strip()] += 1
        self._spelling = {k: c.most_common(1)[0][0] for k, c in spellings.items()}

        # Ads, biggest first; a smaller "ad" that is really a cut-off or typo
        # of a bigger one folds into it (e.g. "... mesquite tx (dallas county"
        # seen 3 times is the Mesquite ad missing its last bracket).
        self.ads: List[str] = []
        self._fold: Dict[str, str] = {}
        for key, n in self.counts.most_common():
            if n < MIN_SEEN:
                break
            home = self._match(key, self.ads)
            if home:
                self._fold[key] = home
            else:
                self.ads.append(key)

    @staticmethod
    def _match(key: str, ads: List[str]) -> Optional[str]:
        if key in ads:
            return key
        if len(key) >= MIN_PREFIX:
            # Cut off at the END (pasted short) or at the FRONT: 9/22 "AT&T
            # Services (Spanish Required) ? Dallas TX" was the Client Solutions
            # Specialist Dallas ad minus its first words, and got its own
            # thread next to the real one. Front cuts match on whole words only,
            # and only when they point at ONE ad (otherwise: as before).
            cut = [a for a in ads if a.startswith(key)]
            if len(cut) == 1:
                return cut[0]
            if len(cut) > 1:
                return None          # a cut-off of two ads: don't pick one
            front = [a for a in ads if a.endswith(" " + key)]
            if len(front) == 1:
                return front[0]
        close = [(difflib.SequenceMatcher(None, key, a).ratio(), a) for a in ads]
        close = [c for c in close if c[0] >= TYPO_RATIO and not _other_city(key, c[1])]
        if close:
            close.sort(reverse=True)
            if len(close) == 1 or close[0][0] - close[1][0] >= 0.03:
                return close[0][1]
        return None

    def resolve(self, title: str) -> Optional[str]:
        """The ad key this title belongs to, or None if it can't be told."""
        key = norm(title)
        if not key:
            return None
        key = self.aliases.get(key, key)
        if key in self.ads:
            return key
        if key in self._fold:
            return self._fold[key]
        return self._match(key, self.ads)

    def find_in_text(self, text: str) -> Optional[str]:
        """An ad named somewhere in free text (the candidate's Slack line) —
        the fallback for a sheet row with a blank title. Longest ad wins, so
        "... (spanish required) arlington tx" beats "... arlington tx"."""
        blob = norm(text)
        hits = [a for a in self.ads if a in blob]
        return max(hits, key=len) if hits else None

    def display(self, key: str) -> str:
        return pretty(self._spelling.get(key, key))
