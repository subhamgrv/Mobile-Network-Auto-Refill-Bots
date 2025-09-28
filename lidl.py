#!/usr/bin/env python3
# lidl.py — headless-friendly for Ubuntu 22.04 + google-chrome-stable + Selenium 4.x

import os
import sys
import time
import traceback
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

# --- Config (from environment) ---
USERNAME = os.getenv("LIDL_USERNAME", "").strip()
PASSWORD = os.getenv("LIDL_PASSWORD", "").strip()
URL = "https://kundenkonto.lidl-connect.de/mein-lidl-connect/mein-tarif/uebersicht.html"

HEADLESS = os.getenv("HEADLESS", "true").lower() in ("1", "true", "yes")
WAIT_SECS = int(os.getenv("WAIT_SECS", "40"))  # generous for SPA loads

def make_driver() -> webdriver.Chrome:
    opts = Options()
    if HEADLESS:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=en-US,en")

    # if base image provides a chrome binary in /opt/chrome, use it (common for Lambda images)
    chrome_bin = os.getenv("CHROME_BINARY", "/opt/chrome/chrome")
    if os.path.exists(chrome_bin):
        opts.binary_location = chrome_bin

    # If you want to force a chromedriver path:
    chromedriver_path = os.getenv("CHROMEDRIVER_PATH", None)

    # Prefer Selenium Manager, but if you have chromedriver binary in a known path, use that
    if chromedriver_path:
        return webdriver.Chrome(executable_path=chromedriver_path, options=opts)
    else:
        # Let Selenium Manager autodetect (works in many container setups)
        return webdriver.Chrome(options=opts)


def click_if_present(driver, by, value):
    try:
        elem = driver.find_element(by, value)
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elem)
        if elem.is_enabled():
            elem.click()
            return True
    except Exception:
        pass
    return False

def accept_cookies_if_any(driver):
    # Try common cookie consent buttons (German/English)
    candidates = [
        (By.XPATH, "//button[contains(., 'Alle akzeptieren') or contains(., 'Akzeptieren') or contains(., 'Accept all') or contains(., 'Accept')]"),
        (By.CSS_SELECTOR, "button[aria-label*='Akzept'], button[aria-label*='Accept']"),
    ]
    for by, val in candidates:
        if click_if_present(driver, by, val):
            time.sleep(0.5)
            return True
    return False

def get_consumption_blocks(driver, wait):
    """Return ALL non-empty text blocks from elements with class 'consumption-info'."""
    # Anchor on overview container (if present)
    try:
        wait.until(EC.presence_of_element_located((By.ID, "lidl-connect-overview")))
    except TimeoutException:
        pass

    # Wait until at least one .consumption-info exists anywhere in the page
    elems = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".consumption-info")))

    lines = []
    for e in elems:
        # ensure inside viewport, then read textContent via JS (more robust than .text sometimes)
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", e)
        except Exception:
            pass
        txt = driver.execute_script("return (arguments[0].textContent || '').trim();", e)
        if txt:
            # compress whitespace
            lines.append(" ".join(txt.split()))
    return lines
def main() -> int:
    if not USERNAME or not PASSWORD:
        print("Set LIDL_USERNAME and LIDL_PASSWORD environment variables.", file=sys.stderr)
        return 1

    driver = make_driver()
    wait = WebDriverWait(driver, WAIT_SECS)

    try:
        driver.get(URL)
        accept_cookies_if_any(driver)

        username_field = wait.until(EC.presence_of_element_located((By.ID, "__BVID__27")))
        password_field = wait.until(EC.presence_of_element_located((By.ID, "__BVID__31")))
        username_field.clear(); username_field.send_keys(USERNAME)
        password_field.clear(); password_field.send_keys(PASSWORD)

        login_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn-login.btn-primary")))
        driver.execute_script("arguments[0].removeAttribute('disabled')", login_button)
        login_button.click()

        wait.until(EC.any_of(
            EC.url_contains("uebersicht"),
            EC.presence_of_element_located((By.ID, "lidl-connect-overview"))
        ))

        # 1️⃣ Read all .consumption-info blocks
        blocks = get_consumption_blocks(driver, wait)

        # 2️⃣ Extract remaining GB (simple regex)
        import re
        remaining = None
        for b in blocks:
            m = re.search(r"(\d+(?:[.,]\d+)?) (?:von|GB von) (\d+(?:[.,]\d+)?) GB", b)
            if m:
                used, total = m.groups()
                used = float(used.replace(",", "."))
                total = float(total.replace(",", "."))
                left = total - used
                remaining = left
                break  # take the first matching block

        print(f"Remaining GB: {remaining}")

        # 3️⃣ Click refill if ≤ 0.2 GB left
        if remaining is not None and remaining <= 0.2:
            try:
                refill_button = wait.until(EC.element_to_be_clickable((By.CLASS_NAME, "tariff-btn-177")))
                try:
                    refill_button.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", refill_button)
                print("Refill activated successfully!")
            except TimeoutException:
                print("[warn] Refill button not found/clickable — skipping.")
        else:
            print("No refill needed.")

        return 0

    except Exception as e:
        print("[error]", e, file=sys.stderr)
        _save_artifacts(driver)
        return 3
    finally:
        driver.quit()


def _save_artifacts(driver):
    try:
        os.makedirs("/tmp/lidl", exist_ok=True)
        driver.save_screenshot("/tmp/lidl/screen.png")
        with open("/tmp/lidl/page.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print("Saved /tmp/lidl/screen.png and /tmp/lidl/page.html for debugging.", file=sys.stderr)
    except Exception:
        pass

if __name__ == "__main__":
    sys.exit(main())
