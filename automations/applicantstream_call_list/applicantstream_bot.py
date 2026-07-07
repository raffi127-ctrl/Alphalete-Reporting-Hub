#!/usr/bin/env python3
"""
ApplicantStream — Extract Resumes & Send to AI
Office: CARLOS HIDALGO (#11580 - ALPHALETE SPECIALIZED MARKETING, INC.)

Automates:
  1. Login check (STOPS if not already logged in — never enters credentials)
  2. Select office 11580
  3. Open the Appstream AI dashboard -> Applicants -> Process Emails -> Process in Batches
  4. Extract resumes in a loop until "Ready For Extraction" == 0
  5. Send all valid applicants to the AI call list in repeated passes
  6. Print a summary

Credentials are NEVER stored or typed by this script. You log in manually in the
Chrome window it opens; the script waits for you, then drives the rest.

Usage:
    pip install -r requirements.txt
    python applicantstream_bot.py
"""

import re
import sys
import time
import argparse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

BASE_URL = "https://applicantstream.com"
OFFICE_ID = "11580"
OFFICE_MATCH = re.compile(r"11580\s+CARLOS HIDALGO", re.I)

# Seconds to wait between extraction Start and the reload/count check.
EXTRACT_WAIT_SECONDS = 180
# Max extraction loops (safety cap).
MAX_EXTRACT_LOOPS = 30
# Max send-to-AI passes (safety cap).
MAX_SEND_PASSES = 10


# --------------------------------------------------------------------------- #
# Setup
# --------------------------------------------------------------------------- #
def build_driver(user_data_dir=None):
    """Launch Chrome. Optionally reuse a profile so an existing login persists."""
    opts = Options()
    if user_data_dir:
        opts.add_argument(f"--user-data-dir={user_data_dir}")
    opts.add_argument("--start-maximized")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    return webdriver.Chrome(options=opts)


def is_login_screen(driver):
    """Login page shows a Username field and title 'Login'."""
    if "login" in (driver.title or "").lower():
        return True
    try:
        driver.find_element(By.CSS_SELECTOR, "input[name*='user' i], input[id*='user' i]")
        # A username field on the landing page => not logged in.
        return "dashboard" not in driver.current_url.lower()
    except NoSuchElementException:
        return False


# --------------------------------------------------------------------------- #
# Step 2 — office selection
# --------------------------------------------------------------------------- #
def select_office(driver, wait):
    if f"newOfficeId={OFFICE_ID}" in driver.current_url:
        print(f"[office] already on {OFFICE_ID}")
        return True

    print(f"[office] selecting {OFFICE_ID} ...")
    field = wait.until(EC.element_to_be_clickable(
        (By.CSS_SELECTOR, "input.office-search, input[id*='office' i], input[placeholder*='office' i]")
    ))
    field.click()
    field.clear()
    field.send_keys(OFFICE_ID)
    time.sleep(2)  # let autocomplete populate

    # Find the matching dropdown entry and fire a full mouse-event sequence,
    # because the autocomplete may ignore a plain .click().
    clicked = driver.execute_script(
        """
        const rx = /11580\\s+CARLOS HIDALGO/i;
        const opt = [...document.querySelectorAll(
            '.autocomplete li, .autocomplete a, ul.dropdown-menu li a, ul li a, .tt-suggestion'
        )].find(el => rx.test(el.textContent));
        if (!opt) return null;
        ['mouseover','mouseenter','mousedown','mouseup','click'].forEach(t =>
            opt.dispatchEvent(new MouseEvent(t, {bubbles:true, cancelable:true, view:window})));
        return opt.textContent.trim();
        """
    )
    if not clicked:
        print("[office] ERROR: could not find '11580 CARLOS HIDALGO' in dropdown")
        return False

    time.sleep(3)
    ok = f"newOfficeId={OFFICE_ID}" in driver.current_url or OFFICE_ID in driver.page_source
    print(f"[office] selected: {clicked!r} (confirmed={ok})")
    return ok


# --------------------------------------------------------------------------- #
# Step 3 — reach the Process in Batches page
# --------------------------------------------------------------------------- #
def open_batch_page(driver, wait):
    print("[nav] opening Appstream AI dashboard ...")
    try:
        btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//*[contains(normalize-space(),'Explore Appstream AI')]")
        ))
        btn.click()
        time.sleep(4)
    except TimeoutException:
        print("[nav] 'Explore Appstream AI' not found — may already be on modern dashboard")

    # Applicants -> Process Emails -> Process in Batches
    actions = webdriver.ActionChains(driver)
    try:
        applicants = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//*[self::a or self::button][contains(.,'Applicants')]")))
        actions.move_to_element(applicants).perform()
        time.sleep(1)
        process_emails = driver.find_element(
            By.XPATH, "//*[contains(.,'Process Emails')]")
        actions.move_to_element(process_emails).perform()
        time.sleep(1)
        driver.find_element(By.XPATH, "//*[contains(.,'Process in Batches')]").click()
        time.sleep(4)
        print("[nav] on Process in Batches page")
        return True
    except (TimeoutException, NoSuchElementException) as e:
        print(f"[nav] ERROR reaching batch page: {e}")
        return False


# --------------------------------------------------------------------------- #
# Step 4 — extraction loop
# --------------------------------------------------------------------------- #
def read_ready_count(driver):
    text = driver.find_element(By.TAG_NAME, "body").text
    m = re.search(r"Ready For Extraction[^0-9]*([0-9,]+)", text, re.I)
    return int(m.group(1).replace(",", "")) if m else None


def extract_resumes(driver, wait):
    total_seen_start = None
    loops = 0
    while loops < MAX_EXTRACT_LOOPS:
        count = read_ready_count(driver)
        if total_seen_start is None:
            total_seen_start = count or 0
        print(f"[extract] Ready For Extraction = {count}")
        if not count or count <= 0:
            break

        # Robot icon -> Resume Helper popup -> Start
        try:
            robot = wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "[class*='robot'], [title*='Resume Helper' i], .fa-robot")))
            robot.click()
            time.sleep(1)
            start = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(.,'Start')]")))
            start.click()
            print(f"[extract] Start clicked — waiting ~{EXTRACT_WAIT_SECONDS}s ...")
        except (TimeoutException, NoSuchElementException) as e:
            print(f"[extract] could not start extraction: {e}")
            break

        time.sleep(EXTRACT_WAIT_SECONDS)
        driver.get(driver.current_url)  # reload — elapsed timer is NOT reliable
        time.sleep(4)
        loops += 1

    remaining = read_ready_count(driver) or 0
    extracted = max(0, (total_seen_start or 0) - remaining)
    print(f"[extract] done. ~{extracted} extracted this run, {remaining} still ready")
    return extracted


# --------------------------------------------------------------------------- #
# Step 5/6 — send to AI in passes
# --------------------------------------------------------------------------- #
def send_all_to_ai(driver, wait):
    total_sent = 0
    for p in range(1, MAX_SEND_PASSES + 1):
        # Put every record on one page.
        driver.execute_script(
            "jQuery('#table-batch-resume').DataTable().page.len(1000).draw();")
        time.sleep(3)

        # Select-all header checkbox next to "Id".
        try:
            header_cb = driver.find_element(
                By.CSS_SELECTOR, "#table-batch-resume thead input[type='checkbox']")
            if not header_cb.is_selected():
                header_cb.click()
            time.sleep(1)
        except NoSuchElementException:
            print("[send] no select-all checkbox — table may be empty")
            break

        # Send To AI
        try:
            driver.find_element(
                By.XPATH, "//button[contains(.,'Send To AI')]").click()
        except NoSuchElementException:
            print("[send] 'Send To AI' button not found")
            break
        time.sleep(2)

        dialog = driver.find_element(By.TAG_NAME, "body").text
        m = re.search(r"Sent to Call List[^0-9]*([0-9,]+)", dialog, re.I)
        sent = int(m.group(1).replace(",", "")) if m else 0

        no_more = "no applicants to send" in dialog.lower()
        if no_more or sent == 0:
            print(f"[send] pass {p}: Sent to Call List = 0 — stopping")
            _click_if_present(driver, ["Close", "Yes"])
            break

        # Confirm "Do you want to continue?" -> Yes
        _click_if_present(driver, ["Yes"])
        total_sent += sent
        print(f"[send] pass {p}: sent {sent} (running total {total_sent})")
        time.sleep(4)

    return total_sent


def _click_if_present(driver, labels):
    for label in labels:
        try:
            driver.find_element(
                By.XPATH, f"//button[contains(.,'{label}')]").click()
            time.sleep(2)
            return True
        except NoSuchElementException:
            continue
    return False


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="ApplicantStream extractor / sender")
    ap.add_argument("--profile", help="Chrome user-data-dir to reuse an existing login")
    ap.add_argument("--login-wait", type=int, default=120,
                    help="seconds to wait for manual login if not already logged in")
    args = ap.parse_args()

    driver = build_driver(args.profile)
    wait = WebDriverWait(driver, 30)
    try:
        driver.get(BASE_URL)
        time.sleep(3)

        if is_login_screen(driver):
            print(f"[login] not logged in. Log in manually within {args.login_wait}s ...")
            deadline = time.time() + args.login_wait
            while time.time() < deadline and is_login_screen(driver):
                time.sleep(3)
            if is_login_screen(driver):
                print("[login] STILL on login screen — stopping. (No credentials are "
                      "entered by this script.)")
                sys.exit(1)

        if not select_office(driver, wait):
            sys.exit("Stopped: could not select office 11580.")
        if not open_batch_page(driver, wait):
            sys.exit("Stopped: could not reach Process in Batches page.")

        extracted = extract_resumes(driver, wait)
        sent = send_all_to_ai(driver, wait)

        print("\n===== SUMMARY =====")
        print(f"Resumes extracted this run : ~{extracted}")
        print(f"Applicants sent to call list: {sent}")
        print("Remaining records are structural duplicates or data-error rows "
              "(blank/placeholder email or phone) that this tool cannot send.")
    finally:
        input("\nPress Enter to close the browser...")
        driver.quit()


if __name__ == "__main__":
    main()
