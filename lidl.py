#!/usr/bin/env python3

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


USERNAME = os.getenv("LIDL_USERNAME", "").strip()
PASSWORD = os.getenv("LIDL_PASSWORD", "").strip()

LOGIN_URL = "https://kundenkonto.lidl-connect.de/mein-lidl-connect/login.html"

HEADLESS = os.getenv("HEADLESS", "true").lower() in ("1","true","yes")
WAIT_SECS = int(os.getenv("WAIT_SECS", "40"))


# ---------------------------------------------------------
# Chrome Setup
# ---------------------------------------------------------
def make_driver():
    opts = Options()
    if HEADLESS:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--remote-debugging-port=9222")
    opts.add_argument("--window-size=1920,1080")

    chrome_bin = os.getenv("CHROME_BINARY")
    if chrome_bin and os.path.isfile(chrome_bin):
        opts.binary_location = chrome_bin

    chromedriver_path = os.getenv("CHROMEDRIVER_PATH")
    if chromedriver_path and os.path.isfile(chromedriver_path):
        return webdriver.Chrome(service=Service(chromedriver_path), options=opts)

    return webdriver.Chrome(options=opts)


# ---------------------------------------------------------
# Accept cookies if shown
# ---------------------------------------------------------
def accept_cookies_if_any(driver):
    selectors = [
        "//button[contains(., 'Ok')]",
        "//button[contains(., 'OK')]",
        "//button[contains(., 'Akzeptieren')]",
    ]
    for xp in selectors:
        try:
            btn = driver.find_element(By.XPATH, xp)
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(0.3)
            return
        except:
            pass


# ---------------------------------------------------------
# Extract remaining refillable data (0.04 GB / 1 GB)
# ---------------------------------------------------------
def get_remaining_unlimited(driver, wait):
    try:
        label = wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "label[for='REFILLABLE_DATA']")
            )
        )
    except TimeoutException:
        print("[WARN] REFILLABLE_DATA label not found")
        return None

    text = label.text.strip().replace("\n", " ")
    # Example: "0.04 GB / 1 GB"
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*GB\s*/\s*(\d+(?:[.,]\d+)?)\s*GB", text)
    if not m:
        print("[WARN] Could not parse REFILLABLE_DATA text:", text)
        return None

    used = float(m.group(1).replace(",", "."))
    total = float(m.group(2).replace(",", "."))
    remaining = total - used

    print(f"[DEBUG] Unlimited Refill: used={used}, total={total}, remaining={remaining}")
    return remaining


# ---------------------------------------------------------
# Main logic
# ---------------------------------------------------------
def main():
    if not USERNAME or not PASSWORD:
        print("Missing credentials", file=sys.stderr)
        return 1

    driver = make_driver()
    wait = WebDriverWait(driver, WAIT_SECS)

    try:
        # Load login page
        driver.get(LOGIN_URL)
        accept_cookies_if_any(driver)

        # Login form
        u = wait.until(EC.presence_of_element_located((By.NAME, "msisdn")))
        p = wait.until(EC.presence_of_element_located((By.NAME, "password")))

        u.send_keys(USERNAME)
        p.send_keys(PASSWORD)

        login_btn = wait.until(EC.element_to_be_clickable((By.ID, "submit-10")))
        login_btn.click()

        # Wait for dashboard
        wait.until(EC.presence_of_element_located((By.ID, "lidl-connect-overview")))

        # Extract unlimited refill remaining
        remaining = get_remaining_unlimited(driver, wait)
        print(f"Remaining GB: {remaining}")

        # Refill if <= 0.9 GB remaining
        if remaining is not None and remaining <= 0.9:
            try:
                # IMPORTANT: Correct selector for refill button
                refill_btn = wait.until(
                    EC.element_to_be_clickable((
                        By.XPATH,
                        "//app-consumptions-refill-v2//button[contains(., 'Activate refill')]"
                    ))
                )

                # Scroll into view
                driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", refill_btn
                )
                time.sleep(0.2)

                # Try click
                try:
                    refill_btn.click()
                except:
                    driver.execute_script("arguments[0].click();", refill_btn)

                print("Refill activated successfully!")
            except TimeoutException:
                print("[WARN] Refill button not found")

        else:
            print("No refill needed")

        return 0

    except Exception as e:
        print("[ERROR]", e, file=sys.stderr)
        save_artifacts(driver)
        return 3

    finally:
        driver.quit()


# ---------------------------------------------------------
# Save debug artifacts
# ---------------------------------------------------------
def save_artifacts(driver):
    try:
        os.makedirs("/tmp/lidl", exist_ok=True)
        driver.save_screenshot("/tmp/lidl/screen.png")
        with open("/tmp/lidl/page.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print("Saved artifacts to /tmp/lidl/")
    except:
        pass


if __name__ == "__main__":
    sys.exit(main())
