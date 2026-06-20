"""Best posting time from the company's OWN Zoho post performance.

Scrapes the published-posts list (each row has a datetime + engagement),
buckets by hour-of-day, and returns the hour with the best average engagement.
Falls back to a research-backed default when there isn't enough signal yet
(e.g. a young post history that's all auto-posts at one time). Result is cached
so we don't re-scrape on every run; it improves on its own as real, varied
engagement data accumulates.

No circular import: this imports zoho_draft for the browser launch; zoho_draft
does NOT import this — callers compute the time and pass it to next_daily_slot.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from collections import defaultdict
from pathlib import Path

from automations.brand_audit.zoho_draft import ZOHO_SOCIAL_URL, _launch_zoho

# We post once a day but NEVER at the same time daily (robotic-looking). We
# rotate across several good windows. Default spread (used until our own data
# shows clear per-hour winners) = morning / lunch / afternoon / early-evening.
# Megan's rule: NOTHING posts past 7pm, so the latest window is 6pm.
EARLIEST_HOUR = 8
LATEST_HOUR = 18                    # 6pm — keeps every post comfortably before 7pm
DEFAULT_WINDOWS = [9, 12, 15, 18]
DEFAULT_BEST_HOUR = 12      # single-value fallback (legacy callers)
DEFAULT_BEST_MINUTE = 0
MIN_GOOD_HOURS = 3          # need this many data-backed hours to skip the spread
MIN_POSTS = 10              # need at least this many before trusting our data
MIN_TOTAL_ENGAGEMENT = 30   # and real engagement, not a handful of likes
MIN_DISTINCT_HOURS = 3      # and posts spread across times, else no comparison
_MAX_SANE_ENGAGEMENT = 500  # ignore caption $ amounts mis-read as counts
PRIORITY_CHANNEL = "instagram"   # the main channel for this recruiting content

_CACHE = Path.home() / ".config" / "brand-audit" / "best_time.json"
_CACHE_TTL_DAYS = 7

_DT_RE = re.compile(
    r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})\s+(\d{1,2}):(\d{2})\s*(AM|PM)", re.I)


def _scrape_samples(pg, channel: str = PRIORITY_CHANNEL, scrolls: int = 8) -> list[tuple[int, int]]:
    """Return [(hour_0_23, engagement)] for published posts on `channel`."""
    pg.evaluate(f'location.hash="#posts/published/{channel}"')
    pg.wait_for_timeout(4000)
    for _ in range(scrolls):       # lazy-loaded list — scroll to pull more rows
        pg.mouse.wheel(0, 3000)
        pg.wait_for_timeout(900)
    rows = pg.evaluate(
        r"""() => {
          const out = [];
          document.querySelectorAll('[class*=post],li,tr,[class*=feed],[class*=row]')
            .forEach(n => {
              const t = (n.innerText || '').replace(/\s+/g, ' ').trim();
              if (t.length > 15 && t.length < 300 &&
                  /\d{1,2} [A-Za-z]{3} \d{4} \d{1,2}:\d{2} (AM|PM)/i.test(t))
                out.push(t);
            });
          return [...new Set(out)];
        }""")
    samples = []
    for t in rows:
        m = _DT_RE.search(t)
        if not m:
            continue
        hour = int(m.group(4)) % 12 + (12 if m.group(6).upper() == "PM" else 0)
        # engagement = the LAST integer in the row (likes/comments trail it),
        # ignoring implausibly large numbers (caption $ amounts / years)
        tail_nums = [int(x) for x in re.findall(r"\b(\d{1,4})\b", t[m.end():])
                     if int(x) <= _MAX_SANE_ENGAGEMENT]
        samples.append((hour, tail_nums[-1] if tail_nums else 0))
    return samples


def compute_best_hour(samples: list[tuple[int, int]]) -> int | None:
    """Best hour by average engagement, or None if there isn't enough signal
    (too few posts, or zero engagement everywhere)."""
    if len(samples) < MIN_POSTS:
        return None
    if sum(e for _, e in samples) < MIN_TOTAL_ENGAGEMENT:
        return None                       # not enough real engagement to trust
    by_hour: dict[int, list[int]] = defaultdict(list)
    for h, e in samples:
        by_hour[h].append(e)
    if len(by_hour) < MIN_DISTINCT_HOURS:
        return None                       # all posts ~same time → no comparison
    # only consider hours with enough posts to be real (not a lone outlier)
    avg = {h: sum(v) / len(v) for h, v in by_hour.items() if len(v) >= 3}
    if not avg:
        return None
    best = max(avg, key=avg.get)
    return best if avg[best] > 0 else None


def good_hours(samples: list[tuple[int, int]]) -> tuple[list[int], str]:
    """Return (hours, source): the data-backed good hours to rotate across, or
    the default spread when there isn't enough signal. We want VARIETY — posts
    rotate through these so they never land at the same time each day."""
    if len(samples) >= MIN_POSTS and sum(e for _, e in samples) >= MIN_TOTAL_ENGAGEMENT:
        by_hour: dict[int, list[int]] = defaultdict(list)
        for h, e in samples:
            by_hour[h].append(e)
        # hours with enough posts AND positive engagement, best first
        ranked = sorted(
            (h for h, v in by_hour.items()
             if len(v) >= 3 and sum(v) > 0 and EARLIEST_HOUR <= h <= LATEST_HOUR),
            key=lambda h: sum(by_hour[h]) / len(by_hour[h]), reverse=True)
        if len(ranked) >= MIN_GOOD_HOURS:
            return sorted(ranked[:4]), f"computed from {len(samples)} posts"
    return DEFAULT_WINDOWS, "default spread (not enough varied-time data yet)"


def best_good_hours(company_name: str = "", *, force: bool = False) -> tuple[list[int], str]:
    """Cached list of good hours to rotate across (see good_hours)."""
    if not force:
        try:
            c = json.loads(_CACHE.read_text())
            if (dt.date.today() - dt.date.fromisoformat(c["date"])).days < _CACHE_TTL_DAYS:
                return c["hours"], c.get("source", "cache")
        except Exception:
            pass
    hours, source = DEFAULT_WINDOWS, "default spread"
    try:
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            ctx = _launch_zoho(p, False)
            try:
                pg = ctx.pages[0] if ctx.pages else ctx.new_page()
                pg.goto(ZOHO_SOCIAL_URL, wait_until="networkidle", timeout=60000)
                pg.wait_for_timeout(2000)
                hours, source = good_hours(_scrape_samples(pg))
            finally:
                ctx.close()
    except Exception as e:
        source = f"default spread (scrape failed: {e})"
    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE.write_text(json.dumps({"date": dt.date.today().isoformat(),
                                  "hours": hours, "source": source}))
    return hours, source


def best_posting_time(company_name: str = "", *, force: bool = False) -> tuple[int, int, str]:
    """Return (hour, minute, source). Cached for a week; `force` re-scrapes."""
    if not force:
        try:
            c = json.loads(_CACHE.read_text())
            if (dt.date.today() - dt.date.fromisoformat(c["date"])).days < _CACHE_TTL_DAYS:
                return c["hour"], c["minute"], c.get("source", "cache")
        except Exception:
            pass

    hour, minute, source = DEFAULT_BEST_HOUR, DEFAULT_BEST_MINUTE, "default"
    try:
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            ctx = _launch_zoho(p, False)
            try:
                pg = ctx.pages[0] if ctx.pages else ctx.new_page()
                pg.goto(ZOHO_SOCIAL_URL, wait_until="networkidle", timeout=60000)
                pg.wait_for_timeout(2000)
                samples = _scrape_samples(pg)
                best = compute_best_hour(samples)
                if best is not None:
                    hour, source = best, f"computed from {len(samples)} posts"
                else:
                    source = f"default (only {len(samples)} posts / weak signal)"
            finally:
                ctx.close()
    except Exception as e:
        source = f"default (scrape failed: {e})"

    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE.write_text(json.dumps({"date": dt.date.today().isoformat(),
                                  "hour": hour, "minute": minute, "source": source}))
    return hour, minute, source


def main(argv=None) -> int:
    import sys
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    force = "--force" in (argv or sys.argv[1:])
    h, m, src = best_posting_time(force=force)
    ampm = "AM" if h < 12 else "PM"
    print(f"best posting time: {h % 12 or 12}:{m:02d} {ampm}  ({src})")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
