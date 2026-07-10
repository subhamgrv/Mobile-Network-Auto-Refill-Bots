#!/usr/bin/env python3

import os
import re
import sys
import time
import traceback

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


def load_dotenv(path=".env"):
    if not os.path.isfile(path):
        return

    with open(path, encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


load_dotenv()


USERNAME = os.getenv("LIDL_USERNAME", "").strip()
PASSWORD = os.getenv("LIDL_PASSWORD", "").strip()

LOGIN_URL = os.getenv(
    "LIDL_LOGIN_URL",
    "https://kundenkonto.lidl-connect.de/mein-lidl-connect.html",
)
LOGIN_URL_FALLBACKS = [
    LOGIN_URL,
    "https://kundenkonto.lidl-connect.de/mein-lidl-connect/login.html",
    "https://kundenkonto.lidl-connect.de/mein-lidl-connect.html",
]

HEADLESS = os.getenv("HEADLESS", "true").strip().lower() in {"1", "true", "yes", "on"}
WAIT_SECS = int(os.getenv("WAIT_SECS", "45"))
ARTIFACT_DIR = os.getenv("LIDL_ARTIFACT_DIR", "/tmp/lidl")
REFILL_THRESHOLD_GB = float(os.getenv("REFILL_THRESHOLD_GB", "0.9"))
PAUSE_BEFORE_QUIT_SECS = int(os.getenv("PAUSE_BEFORE_QUIT_SECS", "0"))
SCRIPT_VERSION = "2026-07-10-maintenance-fallback"


def make_driver():
    opts = Options()
    if HEADLESS:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--window-size=1920,1080")

    chrome_bin = os.getenv("CHROME_BINARY")
    if chrome_bin and os.path.isfile(chrome_bin):
        opts.binary_location = chrome_bin

    chromedriver_path = os.getenv("CHROMEDRIVER_PATH")
    if chromedriver_path and os.path.isfile(chromedriver_path):
        driver = webdriver.Chrome(service=Service(chromedriver_path), options=opts)
    else:
        driver = webdriver.Chrome(options=opts)

    driver.set_page_load_timeout(90)
    return driver


def js_click(driver, element):
    driver.execute_script(
        """
        const el = arguments[0];
        if (!el) return;
        try { el.scrollIntoView({block: 'center'}); } catch (e) {}
        try { el.focus(); } catch (e) {}
        try { el.click(); } catch (e) {}
        try {
          el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
        } catch (e) {}
        """,
        element,
    )


def accept_cookies_if_any(driver, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        try:
            clicked = driver.execute_script(
                """
                const texts = ['akzeptieren', 'alle akzeptieren', 'zustimmen', 'ok', 'okay'];

                function norm(s) {
                  return (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                }

                function candidates(root) {
                  if (!root) return [];
                  return Array.from(root.querySelectorAll('button, a, [role="button"], input[type="button"], input[type="submit"]'));
                }

                function clickIn(root) {
                  for (const el of candidates(root)) {
                    const text = norm(el.innerText || el.textContent || el.value || el.getAttribute('aria-label'));
                    if (texts.some(t => text === t || text.includes(t))) {
                      try { el.scrollIntoView({block: 'center'}); } catch (e) {}
                      el.click();
                      return true;
                    }
                  }
                  return false;
                }

                if (clickIn(document)) return true;
                for (const host of document.querySelectorAll('*')) {
                  if (host.shadowRoot && clickIn(host.shadowRoot)) return true;
                }
                return false;
                """
            )
            if clicked:
                print("[INFO] Cookie prompt accepted")
                time.sleep(0.5)
                return True
        except Exception:
            pass
        time.sleep(0.25)
    print("[INFO] Cookie prompt not found")
    return False


def visible_enabled(element):
    try:
        return element.is_displayed() and element.is_enabled()
    except Exception:
        return False


def first_present(driver, candidates):
    for by, selector in candidates:
        matches = driver.find_elements(by, selector)
        for element in matches:
            if visible_enabled(element):
                return element
    return None


def wait_for_first(driver, candidates, description):
    wait = WebDriverWait(driver, WAIT_SECS)
    try:
        return wait.until(lambda d: first_present(d, candidates))
    except TimeoutException as exc:
        selectors = ", ".join(selector for _, selector in candidates)
        raise TimeoutException(f"Timed out waiting for {description}. Tried: {selectors}") from exc


def wait_for_js(driver, script, description):
    wait = WebDriverWait(driver, WAIT_SECS)
    try:
        return wait.until(lambda d: d.execute_script(script))
    except TimeoutException as exc:
        raise TimeoutException(
            f"Timed out waiting for {description}. URL={driver.current_url!r}, title={driver.title!r}"
        ) from exc


def on_maintenance_page(driver):
    title = (driver.title or "").lower()
    if "wartungsseite" in title or "maintenance" in title:
        return True

    try:
        body = driver.find_element(By.TAG_NAME, "body").text.lower()
    except Exception:
        body = ""
    return "wartungsseite" in body or "maintenance" in body


def login_form_present(driver):
    try:
        return bool(
            driver.execute_script(
                """
                return Boolean(
                  document.querySelector("form[data-form-login] input[name='msisdn'], app-login-v2 input[name='msisdn'], input[data-msisdn]")
                  && document.querySelector("form[data-form-login] input[name='password'], app-login-v2 input[name='password'], input[data-password]")
                );
                """
            )
        )
    except Exception:
        return False


def open_login_page(driver):
    tried = []
    for url in dict.fromkeys(LOGIN_URL_FALLBACKS):
        tried.append(url)
        print("[INFO] Opening login URL:", url)
        driver.get(url)
        accept_cookies_if_any(driver)

        if login_form_present(driver):
            print("[INFO] Login form detected")
            return True

        if on_maintenance_page(driver):
            print("[WARN] Lidl returned maintenance page for:", url)
            continue

        print(f"[WARN] Login form not detected at {url}; title={driver.title!r}")

    if on_maintenance_page(driver):
        print("[WARN] Lidl maintenance page received for all login URLs; skipping this run")
        save_artifacts(driver)
        return False

    raise TimeoutException(
        f"Could not find Lidl login form. Tried: {', '.join(tried)}. "
        f"Final URL={driver.current_url!r}, title={driver.title!r}"
    )


def fill_login_form(driver):
    wait_for_js(
        driver,
        """
        return Boolean(
          document.querySelector("form[data-form-login] input[name='msisdn'], app-login-v2 input[name='msisdn'], input[data-msisdn]")
          && document.querySelector("form[data-form-login] input[name='password'], app-login-v2 input[name='password'], input[data-password]")
        );
        """,
        "Lidl login form",
    )

    result = driver.execute_script(
        """
        function setValue(el, value) {
          if (!el) return false;
          el.focus();
          el.value = value;
          el.dispatchEvent(new Event('input', {bubbles: true}));
          el.dispatchEvent(new Event('change', {bubbles: true}));
          el.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true, key: 'a'}));
          return true;
        }

        const username = document.querySelector("form[data-form-login] input[name='msisdn'], app-login-v2 input[name='msisdn'], input[data-msisdn]");
        const password = document.querySelector("form[data-form-login] input[name='password'], app-login-v2 input[name='password'], input[data-password]");
        const hiddenUsername = document.querySelector("form.mod_login input[name='username'], input#username");
        const hiddenPassword = document.querySelector("form.mod_login input[name='password'], input#password");

        return {
          username: setValue(username, arguments[0]),
          password: setValue(password, arguments[1]),
          hiddenUsername: setValue(hiddenUsername, arguments[0]),
          hiddenPassword: setValue(hiddenPassword, arguments[1]),
        };
        """,
        USERNAME,
        PASSWORD,
    )
    if not result.get("username") or not result.get("password"):
        raise RuntimeError(f"Could not fill Lidl login form: {result}")
    print("[INFO] Login form filled")


def click_login_button(driver):
    wait_for_js(
        driver,
        """
        return Boolean(document.querySelector("form[data-form-login] button[type='submit'], app-login-v2 button[type='submit'], button#submit-10"));
        """,
        "Lidl login button",
    )
    clicked = driver.execute_script(
        """
        const button = document.querySelector("form[data-form-login] button[type='submit'], app-login-v2 button[type='submit'], button#submit-10");
        if (!button) return false;
        try { button.scrollIntoView({block: 'center'}); } catch (e) {}
        button.click();
        button.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
        return true;
        """
    )
    if not clicked:
        raise RuntimeError("Could not click Lidl login button")
    print("[INFO] Login submitted")


def collect_page_text(driver):
    body_text = ""
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
    except Exception:
        pass

    shadow_text = ""
    try:
        shadow_text = driver.execute_script(
            """
            function collect(root, out) {
              if (!root) return out;
              const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
              let node = walker.currentNode;
              while (node) {
                const text = (node.innerText || node.textContent || '').trim();
                if (text) out.push(text);
                if (node.shadowRoot) collect(node.shadowRoot, out);
                node = walker.nextNode();
              }
              return out;
            }
            return collect(document.documentElement, []).join('\\n');
            """
        ) or ""
    except Exception:
        pass

    return "\n".join(part for part in (body_text, shadow_text, driver.page_source) if part)


def login_error_text(driver):
    text = collect_page_text(driver)
    patterns = [
        r"dein\s+login\s+ist\s+fehlgeschlagen.{0,160}",
        r"login\s+ist\s+fehlgeschlagen.{0,160}",
        r"(passwort|kennwort).{0,80}(falsch|ungueltig|ungultig)",
        r"(rufnummer|benutzer|login).{0,80}(falsch|ungueltig|ungultig)",
        r"(account|konto).{0,80}(ist|wurde)\s+(gesperrt|deaktiviert)",
        r"captcha",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return " ".join(match.group(0).split())
    return None


def wait_after_login(driver):
    start_url = driver.current_url
    wait = WebDriverWait(driver, WAIT_SECS)

    def is_ready(d):
        if d.find_elements(By.ID, "lidl-connect-overview"):
            return True
        if d.find_elements(By.CSS_SELECTOR, "label[for='REFILLABLE_DATA']"):
            return True
        if get_remaining_unlimited(d) is not None:
            return True
        err = login_error_text(d)
        if err:
            raise RuntimeError(f"Lidl rejected the login or requires attention: {err}")
        return d.current_url != start_url and "login" not in d.current_url.lower()

    try:
        wait.until(is_ready)
        print("[INFO] Login completed; current URL:", driver.current_url)
    except TimeoutException as exc:
        raise TimeoutException(
            f"Timed out after login. URL={driver.current_url!r}, title={driver.title!r}"
        ) from exc


def parse_gb_pair(text):
    matches = list(
        re.finditer(
            r"(\d+(?:[.,]\d+)?)\s*GB\s*(?:/|von)\s*(\d+(?:[.,]\d+)?)\s*GB",
            text or "",
            flags=re.IGNORECASE,
        )
    )
    if not matches:
        return None

    parsed = []
    for match in matches:
        available = float(match.group(1).replace(",", "."))
        total = float(match.group(2).replace(",", "."))
        parsed.append((available, total))

    one_gb = [item for item in parsed if abs(item[1] - 1.0) < 1e-6]
    return one_gb[0] if one_gb else parsed[0]


def get_remaining_unlimited(driver):
    labels = driver.find_elements(By.CSS_SELECTOR, "label[for^='progress-refill-REFILLABLE_DATA']")
    for label in labels:
        parsed = parse_gb_pair(label.text)
        if parsed:
            return parsed

    labels = driver.find_elements(By.CSS_SELECTOR, "app-consumptions-refill-v2 label")
    for label in labels:
        parsed = parse_gb_pair(label.text)
        if parsed:
            return parsed

    return parse_gb_pair(collect_page_text(driver))


def click_refill_button(driver):
    refill = driver.execute_script(
        """
        function norm(s) {
          return (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
        }
        function textOf(el) {
          let text = norm(el.innerText || el.textContent || el.value || el.getAttribute('aria-label'));
          if (el.shadowRoot) text += ' ' + norm(el.shadowRoot.innerText || el.shadowRoot.textContent);
          return text;
        }

        const root = document.querySelector('app-consumptions-refill-v2');
        if (!root) return null;

        const nodes = Array.from(root.querySelectorAll('button, [role="button"], one-button'));
        for (const el of nodes) {
          const text = textOf(el);
          if (text.includes('refill aktivieren')) return el;
        }
        return null;
        """
    )
    if refill:
        js_click(driver, refill)
        return True

    candidates = [
        (
            By.XPATH,
            "//app-consumptions-refill-v2//*[self::button or @role='button'][contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'refill aktivieren')]",
        ),
    ]
    button = first_present(driver, candidates)
    if button:
        js_click(driver, button)
        return True
    return False


def save_artifacts(driver):
    try:
        os.makedirs(ARTIFACT_DIR, exist_ok=True)
        driver.save_screenshot(os.path.join(ARTIFACT_DIR, "screen.png"))
        with open(os.path.join(ARTIFACT_DIR, "page.html"), "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        with open(os.path.join(ARTIFACT_DIR, "meta.txt"), "w", encoding="utf-8") as f:
            f.write(f"url={driver.current_url}\n")
            f.write(f"title={driver.title}\n")
        print(f"[INFO] Saved artifacts to {ARTIFACT_DIR}/")
    except Exception as exc:
        print(f"[WARN] Could not save artifacts: {exc}")


def main():
    print(f"[INFO] Lidl bot version: {SCRIPT_VERSION}")
    if not USERNAME or not PASSWORD:
        print("Missing credentials", file=sys.stderr)
        return 1

    driver = make_driver()
    try:
        if not open_login_page(driver):
            return 0
        fill_login_form(driver)
        accept_cookies_if_any(driver, timeout=2)
        click_login_button(driver)
        wait_after_login(driver)

        remaining = get_remaining_unlimited(driver)
        if remaining is None:
            print("[WARN] Could not detect remaining GB")
            save_artifacts(driver)
            return 0

        available, total = remaining
        print(f"[INFO] Refill data: available={available:.3f} GB / total={total:.3f} GB")

        if available <= REFILL_THRESHOLD_GB:
            if click_refill_button(driver):
                print("[INFO] Refill activated successfully")
            else:
                print("[WARN] Refill button not found")
                save_artifacts(driver)
        else:
            print(f"[INFO] No refill needed; available {available:.3f} GB is above threshold {REFILL_THRESHOLD_GB:.3f} GB")

        return 0

    except Exception as exc:
        print("[ERROR]", repr(exc), file=sys.stderr)
        traceback.print_exc()
        save_artifacts(driver)
        return 3

    finally:
        if PAUSE_BEFORE_QUIT_SECS > 0:
            print(f"[INFO] Keeping browser open for {PAUSE_BEFORE_QUIT_SECS} seconds")
            time.sleep(PAUSE_BEFORE_QUIT_SECS)
        driver.quit()


if __name__ == "__main__":
    sys.exit(main())
