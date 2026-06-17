"""Shared collector plumbing: the normalized result shape, a flag helper, and a
polite HTTP getter. Keeping these in one place means every collector reports
results the same way, so scoring + the report never special-case a source.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import requests

from automations.brand_audit.config import HTTP_USER_AGENT, HTTP_TIMEOUT

# Flag severities the scorer + alerts understand.
NEGATIVE = "negative"   # a real negative finding (bad review, bad thread)
WARN = "warn"           # something off / anomalous (fill-but-flag)
INFO = "info"           # noteworthy but neutral


@dataclass
class Flag:
    level: str
    message: str
    url: str = ""
    detail: str = ""

    def as_dict(self) -> dict:
        return {"level": self.level, "message": self.message,
                "url": self.url, "detail": self.detail}


@dataclass
class CollectorResult:
    source: str
    ok: bool = True
    error: Optional[str] = None
    metrics: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    flags: list[Flag] = field(default_factory=list)

    def flag(self, level: str, message: str, url: str = "", detail: str = ""):
        self.flags.append(Flag(level, message, url, detail))

    @classmethod
    def failed(cls, source: str, error: str) -> "CollectorResult":
        return cls(source=source, ok=False, error=error)

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "ok": self.ok,
            "error": self.error,
            "metrics": self.metrics,
            "evidence": self.evidence,
            "flags": [f.as_dict() for f in self.flags],
        }


# Some public sites (Indeed, Glassdoor, social platforms, marketing sites behind
# a CDN) reject non-browser user-agents. Use this for those scrape collectors.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def http_get(url: str, *, params: dict | None = None,
             headers: dict | None = None, timeout: int = HTTP_TIMEOUT,
             browser: bool = False, **kwargs) -> requests.Response:
    """GET with a user-agent + timeout baked in. Set browser=True for public
    sites that block non-browser traffic."""
    h = {"User-Agent": BROWSER_UA if browser else HTTP_USER_AGENT}
    if headers:
        h.update(headers)
    return requests.get(url, params=params, headers=h, timeout=timeout, **kwargs)


def get_json(url: str, **kwargs) -> Any:
    r = http_get(url, **kwargs)
    r.raise_for_status()
    return r.json()
