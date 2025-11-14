#!/usr/bin/env python3
# lidl.py — fully GitHub Actions compatible (Ubuntu 24.04, Chrome stable, Selenium 4.x)

import os
import sys
import time
import traceback
import re

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException


# --- Config ---
USERNAME = os.getenv("LIDL_USERNAME", "").strip()
PASSWORD = os.getenv("LIDL_PASSWORD", "").strip()
URL = "https://kundenkonto.lidl-connect.de/mein-lidl-connect/mein-tarif/uebersicht.html"

HEADLESS = os.getenv("HEADLESS", "true").lower() in ("1", "true", "yes")
WAIT_SECS = int(os.getenv("WAIT_SECS", "40"))


# ===========================================================
#  Chrome Driver Setup — FIXED FOR SELENIUM 4
# ===========================================================
def make_driver() -> webdriver.Chrome:
    opts = Options()

    if HEADLESS:
        opts.add_argument("--headless=new")

    # Required in GitHub Actions
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--remote-debugging-port=9222")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=en-US,en")

    # Chrome binary path (auto-set in workflow)
    chrome_bin = os.getenv("CHROME_BINARY")
    if chrome_bin and os.path.isfile(chrome_bin):
        opts.binary_location = chrome_bin

    # Chromedriver path (auto-set in workflow)
    chromedriver_path = os.getenv("CHROMEDRIVER_PATH")
    if chromedriver_path and os.path.isfile(chromedriver_path):
        service = Service(chromedriver_path)
        return webdriver.Chrome(service=service, options=opts)

    # Fallback (Selenium Manager)
    return webdriver.Chrome(options=opts)


# ===========================================================
# Utilities
# ===========================================================
def click_if_present(driver, by, value):
    try:
        elem = driver.find_element(by, value)
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elem)
        if elem.is_enabled():
            elem.click()
            return True
    except:
        pass
    return False


def accept_cookies_if_any(driver):
    selectors = [
        (By.XPATH, "//button[contains(., 'Alle akzeptieren') or contains(., 'Akzeptieren') or contains(., 'Accept')]"),
        (By.CSS_SELECTOR, "button[aria-label*='Akzept'], button[aria-label*='Accept']"),
    ]
    for by, sel in selectors:
        if click_if_present(driver, by, sel):
            time.sleep(0.5)
            return True
    return False


def get_consumption_blocks(driver, wait):
    """Return ALL non-empty text blocks from .consumption-info elements."""
    try:
        wait.until(EC.presence_of_element_located((By.ID, "lidl-connect-overview")))
    except TimeoutException:
        pass

    elems = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".consumption-info")))
    results = []

    for e in elems:
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", e)
        except:
            pass
        txt = driver.execute_script("return (arguments[0].textContent || '').trim();", e)
        if txt:
            results.append(" ".join(txt.split()))
    return results


# ===========================================================
#  MAIN LOGIC
# ===========================================================
def main() -> int:
    if not USERNAME or not PASSWORD:
        print("ERROR: Missing LIDL_USERNAME or LIDL_PASSWORD", file=sys.stderr)
        return 1

    driver = make_driver()
    wait = WebDriverWait(driver, WAIT_SECS)

    try:
        driver.get(URL)
        accept_cookies_if_any(driver)

        # Login form
        username_field = wait.until(EC.presence_of_element_located((By.ID, "__BVID__27")))
        password_field = wait.until(EC.presence_of_element_located((By.ID, "__BVID__31")))

        username_field.clear(); username_field.send_keys(USERNAME)
        password_field.clear(); password_field.send_keys(PASSWORD)

        login_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn-login.btn-primary")))
        driver.execute_script("arguments[0].removeAttribute('disabled');", login_button)
        login_button.click()

        # Wait until dashboard
        wait.until(EC.any_of(
            EC.url_contains("uebersicht"),
            EC.presence_of_element_located((By.ID, "lidl-connect-overview"))
        ))

        blocks = get_consumption_blocks(driver, wait)

        # Parse remaining data
        remaining = None
        for b in blocks:
            m = re.search(r"(\d+(?:[.,]\d+)?) (?:von|GB von) (\d+(?:[.,]\d+)?) GB", b)
            if m:
                used, total = m.groups()
                used = float(used.replace(",", "."))
                total = float(total.replace(",", "."))
                remaining = total - used
                break

        print(f"Remaining GB: {remaining}")

        # Auto-refill
        if remaining is not None and remaining <= 0.9:
            try:
                refill_button = wait.until(EC.element_to_be_clickable((By.CLASS_NAME, "tariff-btn-177")))
                try:
                    refill_button.click()
                except:
                    driver.execute_script("arguments[0].click();", refill_button)
                print("Refill activated successfully!")
            except TimeoutException:
                print("[warn] No refill button found.")
        else:
            print("No refill needed.")

        return 0

    except Exception as e:
        print("[ERROR]", e, file=sys.stderr)
        _save_artifacts(driver)
        return 3

    finally:
        driver.quit()


# ===========================================================
#  ARTIFACT SAVER
# ===========================================================
def _save_artifacts(driver):
    try:
        os.makedirs("/tmp/lidl", exist_ok=True)
        driver.save_screenshot("/tmp/lidl/screen.png")
        with open("/tmp/lidl/page.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print("Saved /tmp/lidl/screen.png and /tmp/lidl/page.html", file=sys.stderr)
    except:
        pass


# ===========================================================
if __name__ == "__main__":
    sys.exit(main())
