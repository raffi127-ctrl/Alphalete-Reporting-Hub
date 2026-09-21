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


def norm(title: str) -> str:
    t = (title or "").replace("&amp;", "&").replace("·", " ").lower()
    t = _LEAD_JUNK.sub("", t)
    t = t.replace("entry-level", "entry level")
    t = re.sub(r"[^a-z0-9&()]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def pretty(title: str) -> str:
    """How a title is SHOWN: the interviewers' spelling, minus the paste junk."""
    t = (title or "").replace("&amp;", "&")
    t = _LEAD_JUNK.sub("", t)
    t = re.sub(r"\s+\?\s+", " – ", t)
    t = re.sub(r"\s+", " ", t).strip(" ,")
    return t


class TitleBook:
    """The running ads, learned from the sheet's own title column."""

    def __init__(self, titles: Iterable[str]):
        raw = [t for t in titles if norm(t)]
        self.counts: Counter = Counter(norm(t) for t in raw)
        # Most common raw spelling per key — that is what gets displayed.
        spellings: Dict[str, Counter] = {}
        for t in raw:
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
            cut = [a for a in ads if a.startswith(key)]
            if len(cut) == 1:
                return cut[0]
            if len(cut) > 1:
                return None          # a cut-off of two ads: don't pick one
        close = [(difflib.SequenceMatcher(None, key, a).ratio(), a) for a in ads]
        close = [c for c in close if c[0] >= TYPO_RATIO]
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
