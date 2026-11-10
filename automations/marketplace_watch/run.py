"""Marketplace Watch — Email when cheap/free office furniture shows up near
the office on Facebook Marketplace.

Every pass: run each search in config.SEARCHES (newest first, ≤ $100),
keep furniture titles from cities within config.MAX_MILES of the office,
and email anything not seen before. Read-only on Facebook: it never messages
sellers, saves items, or changes Marketplace settings.

Facebook account: its own Chrome profile (.browser_profile_fb, gitignored).
Sign in ONCE by hand — this script never types a password:
    python -m automations.marketplace_watch.run --login

Dry run (prints what it would send, sends nothing):
    python -m automations.marketplace_watch.run
Real pass:
    python -m automations.marketplace_watch.run --send
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import quote

from automations.marketplace_watch import config as C

REPO = Path(__file__).resolve().parents[2]
PROFILE = Path(__file__).resolve().parent / ".browser_profile_fb"
STATE_DIR = REPO / "output" / "marketplace_watch"
SEEN_FILE = STATE_DIR / "seen.json"
SEARCH_URL = ("https://www.facebook.com/marketplace/dallas/search?query={q}"
              "&maxPrice={p}&sortBy=creation_time_descend&exact=false"
              "&radius=65")

PRICE_RE = re.compile(r"^(free|\$[\d,]+(\.\d\d)?)$", re.I)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


@dataclass
class Listing:
    item_id: str
    title: str
    price: int          # 0 = free
    city: str
    miles: float
    url: str


# ---------- parsing + filtering (pure, unit-tested) ----------

def miles_between(a, b) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2)
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def parse_card(item_id: str, text: str) -> dict | None:
    """A card's text is lines like: [Just listed] / $40 / [$60 old price] /
    title / City, ST. First price line = current price; last line = city;
    the line before it = title."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    prices = [i for i, ln in enumerate(lines) if PRICE_RE.match(ln)]
    if not prices or len(lines) < prices[-1] + 3:
        return None
    first = lines[prices[0]]
    price = 0 if first.lower() == "free" else int(float(
        first.replace("$", "").replace(",", "")))
    return {"item_id": item_id, "price": price,
            "title": lines[-2], "city": lines[-1]}


def _has_word(title: str, words) -> bool:
    t = " " + re.sub(r"[^a-z0-9]+", " ", title.lower()) + " "
    return any(f" {w} " in t or f" {w}s " in t or (len(w) > 4 and w in t)
               for w in words)


def keep(card: dict, unknown_cities: set) -> Listing | None:
    if card["price"] > C.MAX_PRICE:
        return None
    title = card["title"]
    rest = title.lower()
    wheeled = False
    for w in C.WHEELED_CHAIR:
        rest, n = re.subn(rf"{re.escape(w)}s?", " ", rest)
        wheeled = wheeled or n > 0
    if wheeled:   # "Rolling chair": the leftover "chair" is the same chair
        rest = re.sub(r"\bchairs?\b", " ", rest)
    if not _has_word(rest, C.KEEP_WORDS) or _has_word(title, C.SKIP_WORDS):
        return None
    if "," not in card["city"]:      # "Ships to you" = no pickup city
        return None
    city = card["city"].split(",")[0].strip().lower()
    coords = C.CITY_COORDS.get(city)
    if coords is None:
        unknown_cities.add(card["city"])
        return None
    miles = miles_between((C.OFFICE_LAT, C.OFFICE_LNG), coords)
    if miles > C.MAX_MILES:
        return None
    return Listing(card["item_id"], title, card["price"], card["city"],
                   round(miles, 1),
                   f"https://www.facebook.com/marketplace/item/{card['item_id']}/")


# ---------- browser ----------

CARD_JS = """() => {
  const out = {};
  for (const a of document.querySelectorAll('a[href*="/marketplace/item/"]')) {
    const m = a.getAttribute('href').match(/marketplace\\/item\\/(\\d+)/);
    if (m && !out[m[1]]) out[m[1]] = a.innerText;
  }
  return out;
}"""


def _open(p, headless: bool):
    PROFILE.mkdir(exist_ok=True)
    return p.chromium.launch_persistent_context(
        str(PROFILE), channel="chrome", headless=headless,
        no_viewport=True, args=["--window-size=1280,900"])


def _logged_out(page) -> bool:
    url = page.url
    if "/login" in url or "checkpoint" in url:
        return True
    return page.locator('input[name="email"], input[name="pass"]').count() > 0


def login() -> int:
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = _open(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.facebook.com/login/")
        page.bring_to_front()
        log("Sign in to Facebook in the window that opened "
            "(tick 'remember' if asked). Waiting up to 10 min…")
        for _ in range(180):
            time.sleep(5)
            try:
                if not _logged_out(page) and "facebook.com" in page.url:
                    if "/marketplace" not in page.url:
                        page.goto(SEARCH_URL.format(q="desk", p=C.MAX_PRICE))
                        time.sleep(6)
                    if page.locator('a[href*="/marketplace/item/"]').count():
                        log("Signed in — Marketplace listings visible. Done.")
                        ctx.close()
                        return 0
            except Exception:
                pass
        log("Timed out waiting for sign-in.")
        ctx.close()
        return 2


def scrape(headless: bool) -> tuple[dict, list[str]]:
    """Returns ({item_id: card text}, problems)."""
    from patchright.sync_api import sync_playwright
    cards, problems = {}, []
    with sync_playwright() as p:
        ctx = _open(p, headless=headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            for q in C.SEARCHES:
                page.goto(SEARCH_URL.format(q=quote(q), p=C.MAX_PRICE),
                          wait_until="domcontentloaded", timeout=45000)
                if _logged_out(page):
                    problems.append("LOGGED OUT — run with --login and sign in")
                    break
                loaded = False
                for attempt in range(2):     # FB sometimes serves a blank grid
                    try:
                        page.wait_for_selector(
                            'a[href*="/marketplace/item/"]', timeout=25000)
                        loaded = True
                        break
                    except Exception:
                        if attempt == 0:
                            time.sleep(random.uniform(8, 15))
                            page.reload(wait_until="domcontentloaded")
                if not loaded:
                    problems.append(f"'{q}': no listings loaded")
                    continue
                time.sleep(random.uniform(2, 4))
                page.mouse.wheel(0, 2500)        # load one more screen
                time.sleep(random.uniform(2, 4))
                got = page.evaluate(CARD_JS)
                log(f"'{q}': {len(got)} cards")
                cards.update(got)
                time.sleep(random.uniform(3, 7))  # don't hammer FB
        finally:
            ctx.close()
    return cards, problems


# ---------- state + alert ----------

def load_seen() -> dict:
    try:
        return json.loads(SEEN_FILE.read_text())
    except Exception:
        return {}


def save_seen(seen: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - 30 * 86400          # forget after 30 days
    seen = {k: v for k, v in seen.items() if v > cutoff}
    SEEN_FILE.write_text(json.dumps(seen))


SENDS_FILE = STATE_DIR / "sends.json"


def sends_today() -> int:
    try:
        d = json.loads(SENDS_FILE.read_text())
    except Exception:
        return 0
    return d.get("count", 0) if d.get("date") == time.strftime("%Y-%m-%d") else 0


def record_send() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SENDS_FILE.write_text(json.dumps(
        {"date": time.strftime("%Y-%m-%d"), "count": sends_today() + 1}))


def subject_for(items: list[Listing]) -> str:
    free = sum(1 for i in items if i.price == 0)
    extra = f" ({free} free)" if free else ""
    return f"🪑 {len(items)} new office furniture deals near the office{extra}"


def format_text(items: list[Listing]) -> str:
    lines = []
    for it in sorted(items, key=lambda x: (x.price, x.miles)):
        price = "FREE" if it.price == 0 else f"${it.price}"
        lines.append(f"{price} — {it.title} · {it.city} ({it.miles} mi)\n"
                     f"   {it.url}")
    return "\n".join(lines)


def format_html(items: list[Listing]) -> str:
    from html import escape
    rows = []
    for it in sorted(items, key=lambda x: (x.price, x.miles)):
        price = ("<b style='color:#1a7f37'>FREE</b>" if it.price == 0
                 else f"<b>${it.price}</b>")
        rows.append(
            f"<tr><td style='padding:6px 12px 6px 0'>{price}</td>"
            f"<td style='padding:6px 12px 6px 0'><a href='{it.url}'>"
            f"{escape(it.title)}</a></td>"
            f"<td style='padding:6px 0;color:#555'>{escape(it.city)} · "
            f"{it.miles} mi</td></tr>")
    return ("<div style='font-family:Arial,sans-serif;font-size:15px'>"
            "<p>New on Facebook Marketplace — $100 or less, within ~20 min "
            "of the office. Cheapest first.</p>"
            f"<table style='border-collapse:collapse'>{''.join(rows)}</table>"
            "</div>")


def send_email(to: str, items: list[Listing]) -> None:
    import smtplib
    import ssl
    import certifi
    from email.message import EmailMessage
    from automations.scheduled_6_days_out.email_send import (
        FROM_ADDR, SMTP_HOST, SMTP_PORT, app_password)
    msg = EmailMessage()
    msg["Subject"] = subject_for(items)
    msg["From"] = f"Lucy Reporting <{FROM_ADDR}>"
    msg["To"] = to
    msg.set_content(format_text(items))
    msg.add_alternative(format_html(items), subtype="html")
    # certifi: python 3.14's default context can't verify Gmail's chain here.
    ctx = ssl.create_default_context(cafile=certifi.where())
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as s:
        s.login(FROM_ADDR, app_password())
        s.send_message(msg)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true",
                    help="open the bot's Chrome so you can sign in once")
    ap.add_argument("--send", action="store_true", help="really email")
    ap.add_argument("--to", default=C.ALERT_EMAIL, help="email address")
    ap.add_argument("--mark-seen", action="store_true",
                    help="dry run still records items (to skip a backlog)")
    ap.add_argument("--headless", action="store_true")
    a = ap.parse_args(argv)

    if a.login:
        return login()

    cards, problems = scrape(a.headless)
    unknown: set = set()
    seen = load_seen()
    matches = []
    for item_id, text in cards.items():
        card = parse_card(item_id, text)
        if card:
            hit = keep(card, unknown)
            if hit:
                matches.append(hit)
    new = [m for m in matches if m.item_id not in seen]
    log(f"{len(cards)} cards → {len(matches)} match → {len(new)} new")
    if unknown:
        log("unknown cities (add to config if close): "
            + ", ".join(sorted(unknown)))
    for pr in problems:
        log("PROBLEM: " + pr)
    if not cards:
        return 3        # nothing read at all = a real failure, not "0 new"

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "last_matches.json").write_text(
        json.dumps([asdict(m) for m in matches], indent=1))

    sent_today = sends_today()
    if new:
        if a.send:
            if not a.to:
                log("No --to email set; not sending.")
                return 4
            if sent_today >= C.MAX_ALERTS_PER_DAY:
                # Leave them unseen: they go out in tomorrow's first email.
                log(f"Already sent {sent_today} alerts today (cap "
                    f"{C.MAX_ALERTS_PER_DAY}); holding {len(new)} for next time.")
                return 0
            send_email(a.to, new)
            record_send()
            log(f"Email sent to {a.to}")
        else:
            print(f"\n--- DRY RUN: would email {a.to} ---\n"
                  + subject_for(new) + "\n" + format_text(new))
    if a.send or a.mark_seen:
        now = time.time()
        for m in new:
            seen[m.item_id] = now
        save_seen(seen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
