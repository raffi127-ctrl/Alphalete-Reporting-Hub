"""Daily 6am friendly weather alert for the Frisco, TX team → #alphalete-sales.

Pulls today's forecast from Open-Meteo (free, NO API key), writes a short,
friendly "prep for the day" message (via Claude, with a plain-template
fallback so it never hard-fails), and posts it to #alphalete-sales. Runs
unattended on the always-on Mac mini at 6am Central.

    python -m automations.weather_alert.run            # post to Slack
    python -m automations.weather_alert.run --dry-run  # print only, no post

Deps already in the venv: requests (Open-Meteo), anthropic (wording),
slack_sdk (posting, via automations.shared.slack_metrics_post).
Needs on the machine: the Slack user token
(~/.config/recruiting-report/slack-user-token) to post, and the Anthropic key
(~/.config/brand-audit/keys.json) for the nicer wording (falls back to a
template without it).
"""
from __future__ import annotations

import argparse
import sys

import requests

# DFW metro (coordinates: Frisco, TX)
LAT, LON = 33.1507, -96.8236
LOCATION = "DFW"
TZ = "America/Chicago"

# WMO weather codes → plain description (Open-Meteo's daily weather_code).
_WMO = {
    0: "clear and sunny", 1: "mostly sunny", 2: "partly cloudy", 3: "cloudy",
    45: "foggy", 48: "foggy", 51: "drizzly", 53: "drizzly", 55: "drizzly",
    61: "rainy", 63: "rainy", 65: "heavy rain", 66: "freezing rain",
    67: "freezing rain", 71: "snowy", 73: "snowy", 75: "heavy snow",
    77: "snow grains", 80: "rain showers", 81: "rain showers",
    82: "heavy showers", 85: "snow showers", 86: "snow showers",
    95: "thunderstorms", 96: "thunderstorms with hail", 99: "severe thunderstorms",
}


def _fetch_forecast() -> dict:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
        "wind_speed_10m_max,weather_code"
        "&hourly=precipitation_probability,temperature_2m"
        "&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch"
        f"&timezone={TZ}&forecast_days=1"
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _fmt_hour(h: int) -> str:
    """24h int → '3pm' / '12pm' / '7am'."""
    suffix = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}{suffix}"


def _summarize(fc: dict) -> dict:
    daily = fc["daily"]
    hourly = fc.get("hourly", {})
    hi = round(daily["temperature_2m_max"][0])
    lo = round(daily["temperature_2m_min"][0])
    wind = round(daily["wind_speed_10m_max"][0])
    rain_prob = int(daily["precipitation_probability_max"][0] or 0)
    code = daily["weather_code"][0]
    conditions = _WMO.get(code, "mixed conditions")

    # Peak rain window (only call it out if it's a real chance).
    rain_time = None
    probs = hourly.get("precipitation_probability") or []
    times = hourly.get("time") or []
    if probs and times:
        peak_i = max(range(len(probs)), key=lambda i: probs[i] or 0)
        if (probs[peak_i] or 0) >= 30:
            try:
                rain_time = _fmt_hour(int(times[peak_i][11:13]))
            except Exception:
                rain_time = None
    return {
        "hi": hi, "lo": lo, "wind": wind, "rain_prob": rain_prob,
        "rain_time": rain_time, "conditions": conditions,
    }


def _facts_line(s: dict) -> str:
    parts = [f"{LOCATION} today: {s['conditions']}, high {s['hi']}°F / low {s['lo']}°F",
             f"wind up to {s['wind']} mph"]
    if s["rain_prob"] >= 30:
        when = f" around {s['rain_time']}" if s["rain_time"] else ""
        parts.append(f"{s['rain_prob']}% chance of rain{when}")
    return "; ".join(parts) + "."


def _template_message(s: dict) -> str:
    """Friendly fallback if Claude is unavailable — still warm + useful."""
    tips = []
    spread = s["hi"] - s["lo"]
    if s["rain_prob"] >= 30:
        when = f" (looks heaviest around {s['rain_time']})" if s["rain_time"] else ""
        tips.append(f"grab an umbrella{when}")
    if s["lo"] <= 60 and spread >= 15:
        tips.append("wear a removable outer layer so you're warm this morning but "
                    "can power through the afternoon in a t-shirt")
    elif s["lo"] <= 50:
        tips.append("bundle up — chilly start")
    if s["hi"] >= 85:
        tips.append("sunscreen + bug spray for the afternoon sun")
    tips.append("and pack plenty of water")
    tip_str = "; ".join(tips)
    return (f"🔥 RISE AND GRIND, Dawgs! {_facts_line(s)}\n\n"
            f"Game plan: {tip_str}. Now get out there and OWN those streets — every "
            f"door is money. Let's EAT! — Lucy 🐾")


def _claude_message(s: dict) -> str:
    """Write the friendly blurb with Claude; fall back to the template on any
    error (missing key, network, etc.) — a weather post must never hard-fail."""
    try:
        import anthropic
        from automations.brand_audit import credentials

        system = (
            "You ARE 'Lucy' — the team's office dog mascot turned HIGH-ENERGY "
            "door-to-door sales closer and hype machine. Channel the intensity of "
            "Alex Hormozi, Gary Vee, and Grant Cardone (Wolf-of-Wall-Street fire) — "
            "but keep it 100% clean and workplace-appropriate: NO profanity, no crude "
            "or offensive content. Audience: hungry 20-25-year-old D2D reps who knock "
            "doors all day and live for the grind. Voice: punchy, loud, motivational, "
            "short hard-hitting sentences, momentum and urgency — hustle, grind, "
            "close, 10X, obsessed, 'let's GO', 'every door is money'. Address them as "
            "'Dawgs'. You're still Lucy the pup, so keep a 🐾 and an occasional dog "
            "nod, but the energy is a closer pumping up the team. CRUCIAL: still "
            "deliver the actual weather prep clearly and frame it as ARMOR/FUEL to go "
            "dominate the day — umbrella/rain jacket if rain; shed-able layers if the "
            "morning's cool but the afternoon's hot; sunscreen/bug spray + extra "
            "water if hot & sunny; hydrate. Start with a high-energy greeting + a "
            "fire/weather emoji, weave in the forecast facts, and sign off '— Lucy "
            "🐾'. 2-5 short punchy sentences. PLAIN TEXT ONLY — no markdown, no "
            "asterisks/bold/headers (Slack shows them literally); use ALL-CAPS for "
            "emphasis instead. No hashtags."
        )
        user = (
            f"Forecast — {_facts_line(s)}\n"
            f"(high {s['hi']}F, low {s['lo']}F, wind {s['wind']}mph, "
            f"rain chance {s['rain_prob']}%"
            + (f" around {s['rain_time']}" if s["rain_time"] else "")
            + "). Write the team's weather note."
        )
        client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=320,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = next((b.text for b in resp.content if b.type == "text"), "").strip()
        return text or _template_message(s)
    except Exception as e:
        print(f"[weather] Claude wording unavailable ({type(e).__name__}: "
              f"{str(e)[:120]}) — using template.", flush=True)
        return _template_message(s)


def main() -> int:
    ap = argparse.ArgumentParser(description="Post the daily Frisco weather alert "
                                             "to #alphalete-sales.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the message instead of posting to Slack.")
    args = ap.parse_args()

    try:
        fc = _fetch_forecast()
    except Exception as e:
        print(f"[weather] forecast fetch failed: {type(e).__name__}: {e}", flush=True)
        return 1
    s = _summarize(fc)
    msg = _claude_message(s)

    if args.dry_run:
        print("----- would post to #alphalete-sales -----")
        print(msg)
        print("------------------------------------------")
        return 0

    try:
        from automations.shared import slack_metrics_post as smp
        client = smp._client()
        client.chat_postMessage(channel=smp.CHANNEL_ID, text=msg)
    except Exception as e:
        print(f"[weather] Slack post failed: {type(e).__name__}: {e}", flush=True)
        return 1
    print("[weather] posted to #alphalete-sales ✓", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
