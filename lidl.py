#!/usr/bin/env python3
# lidl.py — fully GitHub Actions compatible (Ubuntu 24.04, Chrome stable, Selenium 4.x)

import os
import sys
import time
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

LOGIN_URL = "https://kundenkonto.lidl-connect.de/mein-lidl-connect/login.html"
DASHBOARD_URL = "https://kundenkonto.lidl-connect.de/mein-lidl-connect/mein-tarif/uebersicht.html"

HEADLESS = os.getenv("HEADLESS", "true").lower() in ("1", "true", "yes")
WAIT_SECS = int(os.getenv("WAIT_SECS", "40"))


# ===========================================================
#  Chrome Setup
# ===========================================================
def make_driver() -> webdriver.Chrome:
    opts = Options()

    if HEADLESS:
        opts.add_argument("--headless=new")

    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--remote-debugging-port=9222")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=en-US,en")

    chrome_bin = os.getenv("CHROME_BINARY")
    if chrome_bin and os.path.isfile(chrome_bin):
        opts.binary_location = chrome_bin

    chromedriver_path = os.getenv("CHROMEDRIVER_PATH")
    if chromedriver_path and os.path.isfile(chromedriver_path):
        service = Service(chromedriver_path)
        return webdriver.Chrome(service=service, options=opts)

    return webdriver.Chrome(options=opts)


# ===========================================================
# Utility functions
# ===========================================================
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
    selectors = [
        (By.XPATH, "//button[contains(., 'Ok')]"),
        (By.XPATH, "//button[contains(., 'Akzeptieren')]"),
    ]
    for by, sel in selectors:
        if click_if_present(driver, by, sel):
            time.sleep(0.5)
            return True
    return False


def get_remaining_gb(driver, wait) -> float | None:
    """
    Extract 'used / total GB' from the new Lidl Connect UI, e.g.:

        <label for="DATA" class="unit-display text-xs">
            50 GB / 50 GB
        </label>

    Returns remaining GB (total - used) as float, or None if not found.
    """
    try:
        # Wait until the consumption card is present
        wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".app-consumption-list")
            )
        )
    except TimeoutException:
        print("[WARN] .app-consumption-list not found", file=sys.stderr)
        return None

    labels = driver.find_elements(
        By.CSS_SELECTOR,
        ".app-consumption-list label.unit-display.text-xs",
    )

    for label in labels:
        text = label.text.strip().replace("\n", " ")
        # Expect something like "0.01 GB / 1 GB" or "50 GB / 50 GB"
        m = re.search(
            r"(\d+(?:[.,]\d+)?)\s*GB\s*/\s*(\d+(?:[.,]\d+)?)\s*GB",
            text,
        )
        if m:
            used_str, total_str = m.groups()
            used = float(used_str.replace(",", "."))
            total = float(total_str.replace(",", "."))
            remaining = total - used
            print(f"[DEBUG] Parsed usage from label: used={used}, total={total}, remaining={remaining}")
            return remaining

    print("[WARN] No matching 'X GB / Y GB' pattern found in labels", file=sys.stderr)
    return None


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
        driver.get(LOGIN_URL)
        accept_cookies_if_any(driver)

        # Login fields
        username_field = wait.until(
            EC.presence_of_element_located((By.NAME, "msisdn"))
        )
        password_field = wait.until(
            EC.presence_of_element_located((By.NAME, "password"))
        )

        username_field.clear()
        username_field.send_keys(USERNAME)

        password_field.clear()
        password_field.send_keys(PASSWORD)

        login_button = wait.until(
            EC.element_to_be_clickable((By.ID, "submit-10"))
        )
        login_button.click()

        # Wait for dashboard
        wait.until(
            EC.any_of(
                EC.url_contains("uebersicht"),
                EC.presence_of_element_located((By.ID, "lidl-connect-overview")),
            )
        )

        # --- NEW: read remaining GB from the new card HTML ---
        remaining = get_remaining_gb(driver, wait)
        print(f"Remaining GB: {remaining}")

        # =====================================================
        # Refill Activation
        # =====================================================
        if remaining is not None and remaining <= 0.9:
            try:
                refill_button = wait.until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//button[contains(., 'Activate refill')]")
                    )
                )

                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});",
                    refill_button,
                )
                time.sleep(0.3)

                try:
                    refill_button.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", refill_button)

                print("Refill activated successfully!")

            except TimeoutException:
                print("[WARN] Refill button not found.")
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
# Artifacts saver
# ===========================================================
def _save_artifacts(driver):
    try:
        os.makedirs("/tmp/lidl", exist_ok=True)
        driver.save_screenshot("/tmp/lidl/screen.png")
        with open("/tmp/lidl/page.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print("Saved /tmp/lidl/screen.png and /tmp/lidl/page.html", file=sys.stderr)
    except Exception:
        pass


# ===========================================================
if __name__ == "__main__":
    sys.exit(main())
