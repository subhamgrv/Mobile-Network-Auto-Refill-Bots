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
# Cookie handling
# ---------------------------------------------------------
def accept_cookies_if_any(driver):
    buttons = [
        "//button[contains(., 'Ok')]",
        "//button[contains(., 'Akzeptieren')]",
    ]
    for xpath in buttons:
        try:
            b = driver.find_element(By.XPATH, xpath)
            driver.execute_script("arguments[0].click();", b)
            time.sleep(0.5)
            return
        except:
            pass


# ---------------------------------------------------------
# Extract remaining GB from REFILLABLE_DATA block
# ---------------------------------------------------------
def get_remaining_unlimited(driver, wait):
    try:
        label = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "label[for='REFILLABLE_DATA']"))
        )
    except TimeoutException:
        print("[WARN] REFILLABLE_DATA label not found")
        return None

    text = label.text.strip().replace("\n", " ")
    # expected format: "0 GB / 1 GB"
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*GB\s*/\s*(\d+(?:[.,]\d+)?)\s*GB", text)
    if not m:
        print("[WARN] Could not parse remaining from:", text)
        return None

    used = float(m.group(1).replace(",", "."))
    total = float(m.group(2).replace(",", "."))
    remaining = total - used
    print(f"[DEBUG] Unlimited Refill: used={used}, total={total}, remaining={remaining}")
    return remaining


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------
def main():
    if not USERNAME or not PASSWORD:
        print("Missing credentials", file=sys.stderr)
        return 1

    driver = make_driver()
    wait = WebDriverWait(driver, WAIT_SECS)

    try:
        driver.get(LOGIN_URL)
        accept_cookies_if_any(driver)

        # Login
        u = wait.until(EC.presence_of_element_located((By.NAME, "msisdn")))
        p = wait.until(EC.presence_of_element_located((By.NAME, "password")))

        u.send_keys(USERNAME)
        p.send_keys(PASSWORD)

        login_button = wait.until(EC.element_to_be_clickable((By.ID, "submit-10")))
        login_button.click()

        # Wait until dashboard
        wait.until(
            EC.presence_of_element_located((By.ID, "lidl-connect-overview"))
        )

        # --- Extract remaining GB (correct block) ---
        remaining = get_remaining_unlimited(driver, wait)
        print(f"Remaining GB: {remaining}")

        # --- Refill button ---
        if remaining is not None and remaining <= 0.9:
            try:
                refill_btn = wait.until(
                    EC.element_to_be_clickable(
                        (
                            By.XPATH,
                            "//div[contains(@class,'consumption-box')]//button[contains(., 'Activate refill')]"
                        )
                    )
                )

                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", refill_btn)
                time.sleep(0.2)

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
# Save artifacts
# ---------------------------------------------------------
def save_artifacts(driver):
    try:
        os.makedirs("/tmp/lidl", exist_ok=True)
        driver.save_screenshot("/tmp/lidl/screen.png")
        with open("/tmp/lidl/page.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
    except:
        pass


if __name__ == "__main__":
    sys.exit(main())
