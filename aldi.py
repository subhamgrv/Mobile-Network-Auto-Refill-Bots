# aldi.py
# Logs into ALDI TALK Kundenportal (CIAM) by:
# 1) accepting the Usercentrics cookie wall
# 2) typing Rufnummer + Passwort into <one-input> (shadow DOM)
# 3) clicking "Anmelden" (<one-button>, shadow DOM)

import os
import sys
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import re


LOGIN_URL = os.getenv("ALDI_LOGIN_URL", "https://login.alditalk-kundenbetreuung.de/signin/XUI/#login/")
USERNAME = os.getenv("ALDI_RUFNUMMER", "").strip()
PASSWORD = os.getenv("ALDI_PASSWORT", "").strip()
HEADLESS = os.getenv("HEADLESS", "0").strip() == "1"

WAIT_SECS = int(os.getenv("WAIT_SECS", "25"))


def build_driver() -> webdriver.Chrome:
    opts = webdriver.ChromeOptions()

    # Reduce Chrome noise / prompts
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,900")
    # Disable push messaging to reduce those GCM/registration logs (best-effort)
    opts.add_argument("--disable-features=PushMessaging,Notifications")

    prefs = {
        "profile.default_content_setting_values.notifications": 2,
    }
    opts.add_experimental_option("prefs", prefs)

    if HEADLESS:
        # "new" headless works better with modern sites than old headless
        opts.add_argument("--headless=new")

    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(60)
    return driver


def accept_usercentrics_cookie_wall(driver, timeout: int = 12) -> bool:
    """
    Tries multiple strategies:
    - direct DOM query for the accept button
    - query inside #usercentrics-root shadow DOM
    """
    end = time.time() + timeout
    while time.time() < end:
        try:
            clicked = driver.execute_script(
                """
                function clickAcceptInRoot(root){
                    if (!root) return false;
                    const btn = root.querySelector('button[data-testid="uc-accept-all-button"]');
                    if (!btn) return false;
                    btn.scrollIntoView({block:'center'});
                    btn.click();
                    btn.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, view:window}));
                    return true;
                }

                // 1) Try normal DOM
                if (clickAcceptInRoot(document)) return true;

                // 2) Try within usercentrics shadowRoot
                const host = document.querySelector('#usercentrics-root');
                if (host && host.shadowRoot) {
                    if (clickAcceptInRoot(host.shadowRoot)) return true;
                }
                return false;
                """
            )
            if clicked:
                # Wait a moment for overlay to disappear
                time.sleep(0.5)
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def set_one_input_value(driver, host_css: str, value: str, hidden_input_id: str | None = None) -> str:
    """
    Types into <one-input> by reaching its open shadowRoot and setting the inner <input>.
    Also sets the hidden callback input (idToken3/idToken4) used by the form.
    """
    res = driver.execute_script(
        """
        const host = document.querySelector(arguments[0]);
        if (!host) return 'no-host';
        const root = host.shadowRoot;
        if (!root) return 'no-shadow';
        const input = root.querySelector('input');
        if (!input) return 'no-inner-input';

        input.focus();
        input.value = arguments[1];
        host.value = arguments[1];

        const ev = { bubbles: true, composed: true };
        input.dispatchEvent(new Event('input', ev));
        input.dispatchEvent(new Event('change', ev));
        input.dispatchEvent(new KeyboardEvent('keyup', { bubbles:true, composed:true, key:'a' }));
        input.dispatchEvent(new KeyboardEvent('keyup', { bubbles:true, composed:true, key:'Enter' }));
        return 'ok';
        """,
        host_css,
        value,
    )

    if hidden_input_id:
        driver.execute_script(
            """
            const el = document.getElementById(arguments[0]);
            if (el) {
              el.value = arguments[1];
              el.dispatchEvent(new Event('input', {bubbles:true}));
              el.dispatchEvent(new Event('change', {bubbles:true}));
            }
            """,
            hidden_input_id,
            value,
        )
    return res


def one_button_is_enabled(driver, host_css: str) -> bool:
    """
    Checks if <one-button> internal base has aria-disabled="false"
    """
    return bool(
        driver.execute_script(
            """
            const host = document.querySelector(arguments[0]);
            if (!host || !host.shadowRoot) return false;
            const base = host.shadowRoot.querySelector('[part="base"]');
            if (!base) return false;

            // base can be <a> or <button>
            const aria = base.getAttribute('aria-disabled');
            if (aria === 'true') return false;

            // also check disabled class
            if ((base.className || '').includes('button--disabled')) return false;

            return true;
            """,
            host_css,
        )
    )


def click_one_button(driver, host_css: str) -> str:
    """
    Clicks <one-button> by clicking its internal [part="base"] element in shadowRoot.
    """
    return driver.execute_script(
        """
        const host = document.querySelector(arguments[0]);
        if (!host) return 'no-host';
        const root = host.shadowRoot;
        if (!root) return 'no-shadow';
        const base = root.querySelector('[part="base"]');
        if (!base) return 'no-base';
        base.scrollIntoView({block:'center'});
        base.click();
        base.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, view:window}));
        return 'clicked';
        """,
        host_css,
    )

# =========================
# Helpers
# =========================
def env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def js_click(driver, el):
    """Robust click (works for <one-button> shadow DOM and normal elements)."""
    return driver.execute_script(
        """
        const el = arguments[0];
        if (!el) return 'no-el';

        function doClick(target){
          try { target.scrollIntoView({block:'center'}); } catch(e) {}
          try { target.focus(); } catch(e) {}
          try { target.click(); } catch(e) {}
          try {
            target.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, view:window}));
          } catch(e) {}
        }

        // If it's a <one-button>, click the internal base
        const tag = (el.tagName || '').toLowerCase();
        if (tag === 'one-button' && el.shadowRoot) {
          const base = el.shadowRoot.querySelector('[part="base"], button, a');
          if (base) { doClick(base); return 'clicked-shadow'; }
        }

        // fallback: click host element
        doClick(el);
        return 'clicked';
        """,
        el,
    )


def shadow_dom_text(driver) -> str:
    """Collects text including open shadow roots (best-effort)."""
    try:
        return driver.execute_script(
            r"""
            function collect(node, out){
              out = out || [];
              if (!node) return out;

              // Element
              if (node.nodeType === 1) {
                const t = (node.innerText || node.textContent || '').trim();
                if (t) out.push(t);
                if (node.shadowRoot) collect(node.shadowRoot, out);
                const kids = node.children || [];
                for (let i=0; i<kids.length; i++) collect(kids[i], out);
                return out;
              }

              // Document / ShadowRoot / DocumentFragment
              const children = node.children || [];
              for (let i=0; i<children.length; i++) collect(children[i], out);

              return out;
            }

            const parts = collect(document.documentElement, []);
            return parts.join("\n");
            """
        ) or ""
    except Exception:
        return ""


# =========================
# Remaining data (generic)
# =========================
def get_remaining_gb_from_text(text: str):
    text = (text or "").replace("\n", " ")

    # Common formats:
    # "0,8 GB / 1,0 GB"   or  "0.8GB/1GB"
    # "0,8 GB von 1,0 GB"
    matches = list(
        re.finditer(
            r"(\d+(?:[.,]\d+)?)\s*GB\s*(?:/|von)\s*(\d+(?:[.,]\d+)?)\s*GB",
            text,
            flags=re.IGNORECASE,
        )
    )
    if not matches:
        return None

    def parse(m):
        used = float(m.group(1).replace(",", "."))
        total = float(m.group(2).replace(",", "."))
        return used, total, (total - used)

    parsed = [parse(m) for m in matches]

    # If multiple packages shown, prefer the 1GB bucket if present (as you had)
    one_gb = [t for t in parsed if abs(t[1] - 1.0) < 1e-6]
    return (one_gb[0] if one_gb else parsed[0])


def get_remaining_gb(driver):
    # 1) fast path: visible body text
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
    except Exception:
        body_text = ""
    r = get_remaining_gb_from_text(body_text)
    if r:
        return r

    # 2) include shadow dom text
    r = get_remaining_gb_from_text(shadow_dom_text(driver))
    if r:
        return r

    # 3) last resort: raw HTML
    return get_remaining_gb_from_text(driver.page_source)


def click_1gb_button(driver, wait):
    """
    Tries:
    - JS search across one-button/button/a by text "1 GB" (including shadowRoot text)
    - then your XPath candidates as fallback
    """
    # --- 1) JS-based search (best for shadow DOM) ---
    el = driver.execute_script(
        """
        const want = (arguments[0] || '').toLowerCase();

        function norm(s){
          return (s || '').replace(/\\s+/g,' ').trim().toLowerCase();
        }
        function textOf(node){
          let t = '';
          try { t += (node.innerText || node.textContent || ''); } catch(e) {}
          try {
            if (node.shadowRoot) t += ' ' + (node.shadowRoot.innerText || node.shadowRoot.textContent || '');
          } catch(e) {}
          return norm(t);
        }

        const nodes = Array.from(document.querySelectorAll('one-button, button, a'));
        for (const n of nodes) {
          const t = textOf(n);
          if (t.includes(want)) return n;
        }
        return null;
        """,
        "1 gb",
    )
    if el:
        js_click(driver, el)
        return True

    # --- 2) XPath fallback ---
    candidates = [
        (By.XPATH, "//one-button[.//one-text[contains(normalize-space(.),'1 GB')]]"),
        (By.XPATH, "//one-button[contains(normalize-space(.),'1 GB')]"),
        (By.XPATH, "//*[contains(normalize-space(.),'1 GB') and (self::button or self::a)]"),
    ]
    last = None
    for by, sel in candidates:
        try:
            el2 = wait.until(EC.element_to_be_clickable((by, sel)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el2)
            time.sleep(0.2)
            js_click(driver, el2)
            return True
        except Exception as e:
            last = e

    if last:
        raise last
    return False


def save_artifacts(driver):
    try:
        os.makedirs("/tmp/alditalk", exist_ok=True)
        driver.save_screenshot("/tmp/alditalk/screen.png")
        with open("/tmp/alditalk/page.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print("Saved artifacts to /tmp/alditalk/")
    except Exception:
        pass


def main() -> int:
    if not USERNAME or not PASSWORD:
        print("ERROR: Missing credentials.")
        print("Set environment variables:")
        print("  ALDI_RUFNUMMER=...  ALDI_PASSWORT=...  (optional: ALDI_LOGIN_URL, HEADLESS=1)")
        return 2

    driver = build_driver()
    wait = WebDriverWait(driver, WAIT_SECS)

    try:
        driver.get(LOGIN_URL)

        # Accept cookie wall (best-effort)
        if accept_usercentrics_cookie_wall(driver, timeout=15):
            print("[INFO] Usercentrics cookie wall accepted")
        else:
            print("[WARN] Cookie wall not found / not accepted (continuing)")

        # Wait for web components
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "one-input#idToken3_od")))
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "one-input#idToken4_od")))

        # Fill Rufnummer + Passwort (shadow DOM) + set hidden callback inputs
        r1 = set_one_input_value(driver, "one-input#idToken3_od", USERNAME, hidden_input_id="idToken3")
        r2 = set_one_input_value(driver, "one-input#idToken4_od", PASSWORD, hidden_input_id="idToken4")
        print("[INFO] fill rufnummer:", r1)
        print("[INFO] fill passwort :", r2)

        # Cookie wall can re-appear; optional second attempt
        accept_usercentrics_cookie_wall(driver, timeout=3)

        # Wait until Anmelden becomes enabled
        login_btn_css = "one-button#IDToken5_4_od_2"
        wait.until(lambda d: one_button_is_enabled(d, login_btn_css))

        # Click "Anmelden"
        c = click_one_button(driver, login_btn_css)
        print("[INFO] click login  :", c)

        # Give navigation a moment (adjust if you want a stronger post-login check)
        time.sleep(10)

        AUTO_BOOK_1GB = env_bool("AUTO_BOOK_1GB", False)


        remaining = get_remaining_gb(driver)
        if remaining:
            used, total, left = remaining
            print(f"[INFO] Data: used={used:.3f} GB / total={total:.3f} GB -> remaining={left:.3f} GB")
        else:
             print("[WARN] Could not detect remaining GB on this page.")

        if AUTO_BOOK_1GB:
            print("[INFO] AUTO_BOOK_1GB enabled -> trying to click 1 GB button...")
            ok = click_1gb_button(driver, wait)
            print("[INFO] click_1gb_button:", ok)

        save_artifacts(driver)
        print("[INFO] Done. Current URL:", driver.current_url)
        return 0

    except Exception as e:
        print("[ERROR] Failed:", repr(e))
        try:
            driver.save_screenshot("aldi_error.png")
            print("[INFO] Saved screenshot: aldi_error.png")
        except Exception:
            pass
        return 1
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())





# input these in the shell before running: python aldi.py
# export ALDI_RUFNUMMER="015756273620"
# export ALDI_PASSWORT="Aliingermany116@"
# export HEADLESS=false
# export COOKIE_ACTION=accept     # or: deny
# export AUTO_BOOK_1GB=false  