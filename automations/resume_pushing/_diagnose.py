#!/usr/bin/env python3
"""Diagnose the Resume Helper popup AFTER the extractor plugin is loaded.
Navigates to the v2 batch page, clicks the robot, and dumps every frame + button
+ any popup text, so we can see where "Start" actually lives (extensions often
inject their UI into an iframe). Sends NOTHING. Run via deploy/probe_extractor.command."""
from automations.shared.tableau_patchright import appstream_direct_session
from automations.recruiting_report import fetch_office
from automations.resume_pushing.run import (
    open_v2_dashboard, goto_process_in_batches)


def _buttons_in(frame):
    out = []
    try:
        loc = frame.locator("button, a[role='button'], [role='button'], "
                             "input[type='button'], input[type='submit'], .btn")
        for i in range(min(loc.count(), 50)):
            try:
                el = loc.nth(i)
                if not el.is_visible():
                    continue
                t = " ".join((el.inner_text() or "").split())
                v = el.get_attribute("value") or ""
                lab = (t or v).strip()
                if lab:
                    out.append(lab[:45])
            except Exception:
                pass
    except Exception:
        pass
    return out


def _dump(page, label):
    print(f"\n========== {label} ==========")
    print(f"frames ({len(page.frames)}):")
    for f in page.frames:
        print(f"  - {(f.url or '(no url)')[:95]}")
    for idx, f in enumerate(page.frames):
        btns = _buttons_in(f)
        if btns:
            print(f"buttons in frame#{idx} {(f.url or '')[:60]}:")
            for b in dict.fromkeys(btns):          # de-dupe, keep order
                print(f"    • {b}")
    # Any text that hints at extraction / install state, across all frames
    print("keyword hits (Start / Extract / install / plugin / Resume Helper):")
    seen = set()
    for f in page.frames:
        for kw in ["Start", "Extract", "install", "Install", "download",
                   "plugin", "Resume Helper", "Begin", "Run", "Process"]:
            try:
                loc = f.locator(f"xpath=//*[contains(text(),'{kw}')]")
                for i in range(min(loc.count(), 4)):
                    t = " ".join((loc.nth(i).inner_text() or "").split())
                    t = t[:90]
                    if t and t not in seen:
                        seen.add(t)
                        print(f"    [{kw}] {t}")
            except Exception:
                pass


with appstream_direct_session(yield_if_busy=True, load_extensions=True) as page:
    fetch_office._switch_office(page, "11580", "CARLOS HIDALGO")
    page.wait_for_timeout(1500)
    page = open_v2_dashboard(page)
    goto_process_in_batches(page)
    page.wait_for_timeout(2500)

    _dump(page, "BEFORE robot click")

    print("\n--- clicking the robot / Resume Helper ---")
    for sel in ["button[title*='Resume' i]", "[title*='Resume Helper' i]",
                "[title*='extract resume data' i]", "a[title*='Resume' i]",
                ".fa-robot", "i.fa-robot", "button:has(.fa-robot)",
                "[class*='robot']"]:
        loc = page.locator(sel)
        if loc.count():
            try:
                loc.first.click(timeout=8000)
                print(f"clicked robot via: {sel}")
                break
            except Exception as e:
                print(f"click {sel} failed: {e}")
    page.wait_for_timeout(4000)

    _dump(page, "AFTER robot click")
    print("\n=== diagnose done ===")
