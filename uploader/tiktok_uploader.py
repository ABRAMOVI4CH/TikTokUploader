"""
TikTok video uploader using Selenium.
Handles cookie-based authentication and video upload via the TikTok web interface.
"""

import base64
import logging
import os
import time
from pathlib import Path
from urllib.request import urlopen

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("TikTokUploader")

UPLOAD_URL = "https://www.tiktok.com/creator#/upload?scene=creator_center"
TIKTOK_HOME = "https://www.tiktok.com"

WAIT_SHORT = 10
WAIT_MEDIUM = 30
WAIT_LONG = 120


class TikTokUploader:
    def __init__(self):
        self.driver = None
        self._init_driver()

    # ------------------------------------------------------------------
    # Driver lifecycle
    # ------------------------------------------------------------------

    def _init_driver(self):
        logger.info("Initialising Chrome driver…")
        options = ChromeOptions()
        if not os.environ.get("DISPLAY"):
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--lang=en-US")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )

        chrome_binary = os.environ.get("CHROME_BINARY")
        if chrome_binary:
            options.binary_location = chrome_binary

        driver_path = os.environ.get("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")
        service = Service(executable_path=driver_path)

        try:
            self.driver = webdriver.Chrome(service=service, options=options)
            self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            })
            logger.info("Chrome driver started successfully.")
        except Exception as exc:
            logger.error("Failed to start Chrome driver: %s", exc)
            raise

    def quit(self):
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Chrome driver closed.")
            except Exception as exc:
                logger.warning("Error while closing driver: %s", exc)
            finally:
                self.driver = None

    # ------------------------------------------------------------------
    # Cookie injection
    # ------------------------------------------------------------------

    def inject_cookies(self, cookies: list) -> bool:
        """Inject a list of cookie dicts into the browser. Returns True if session valid."""
        self.driver.get(TIKTOK_HOME)
        time.sleep(2)

        # Clear existing cookies first
        self.driver.delete_all_cookies()
        time.sleep(0.5)

        injected = 0
        for cookie in cookies:
            clean = {}
            clean["name"] = cookie.get("name", "")
            clean["value"] = cookie.get("value", "")

            if "domain" in cookie:
                clean["domain"] = cookie["domain"]
            if "path" in cookie:
                clean["path"] = cookie["path"]
            if "secure" in cookie:
                clean["secure"] = cookie["secure"]
            if "httpOnly" in cookie:
                clean["httpOnly"] = cookie["httpOnly"]

            if "expiry" in cookie:
                clean["expiry"] = int(cookie["expiry"])
            elif "expirationDate" in cookie:
                clean["expiry"] = int(cookie["expirationDate"])

            same_site = cookie.get("sameSite")
            if same_site == "no_restriction":
                clean["sameSite"] = "None"
            elif same_site in ("lax", "Lax"):
                clean["sameSite"] = "Lax"
            elif same_site in ("strict", "Strict"):
                clean["sameSite"] = "Strict"

            if not clean.get("name") or not clean.get("value"):
                continue

            try:
                self.driver.add_cookie(clean)
                injected += 1
            except Exception as exc:
                logger.debug("Skipped cookie %s: %s", cookie.get("name"), exc)

        logger.info("Injected %d cookies.", injected)
        self.driver.refresh()
        time.sleep(3)
        return self._is_logged_in()

    def _is_logged_in(self) -> bool:
        try:
            browser_cookies = self.driver.get_cookies()
            cookie_names = {c["name"] for c in browser_cookies}
            if "sessionid" in cookie_names or "sid_tt" in cookie_names:
                return True
            return False
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Account verification
    # ------------------------------------------------------------------

    def verify_account(self, cookies: list) -> dict:
        """
        Inject cookies, verify login, and scrape TikTok profile info.
        Returns dict with keys: valid, username, nickname, avatar_url.
        """
        ok = self.inject_cookies(cookies)
        if not ok:
            return {"valid": False, "username": "", "nickname": "", "avatar_url": ""}

        username = ""
        nickname = ""
        avatar_url = ""

        try:
            time.sleep(2)
            # Parse __UNIVERSAL_DATA_FOR_REHYDRATION__ → webapp.app-context → user
            user_info = self.driver.execute_script("""
                try {
                    var el = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');
                    if (el) {
                        var data = JSON.parse(el.textContent);
                        var user = data.__DEFAULT_SCOPE__['webapp.app-context'].user;
                        return {
                            username: user.uniqueId || '',
                            nickname: user.nickName || '',
                            avatar: (user.avatarUri && user.avatarUri[0]) || ''
                        };
                    }
                } catch(e) {}
                return null;
            """)

            if user_info:
                username = user_info.get("username", "")
                nickname = user_info.get("nickname", "")
                avatar_url = user_info.get("avatar", "")

            logger.info("Verified account: @%s (%s)", username, nickname)

        except Exception as exc:
            logger.warning("Could not scrape profile info: %s", exc)

        return {
            "valid": True,
            "username": username,
            "nickname": nickname,
            "avatar_url": avatar_url,
        }

    def download_avatar(self, avatar_url: str, save_path: str) -> bool:
        """Download avatar image to local path."""
        if not avatar_url:
            return False
        try:
            resp = urlopen(avatar_url, timeout=10)
            data = resp.read()
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(data)
            logger.info("Avatar saved to %s", save_path)
            return True
        except Exception as exc:
            logger.warning("Failed to download avatar: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def check_status(self) -> dict:
        if not self.driver:
            return {"alive": False}
        try:
            _ = self.driver.title
            return {"alive": True}
        except WebDriverException:
            return {"alive": False}

    # ------------------------------------------------------------------
    # Video upload
    # ------------------------------------------------------------------

    def upload_video(
        self,
        video_path: str,
        description: str,
        cookies: list,
        tags: list[str] | None = None,
    ) -> dict:
        video_path = str(Path(video_path).resolve())
        if not os.path.isfile(video_path):
            return {"status": "failed", "message": f"Video file not found: {video_path}"}

        logger.info("Starting upload for: %s", video_path)

        try:
            # Step 0 — Inject cookies
            logger.info("Step 0: Injecting cookies…")
            ok = self.inject_cookies(cookies)
            if not ok:
                return {"status": "failed", "message": "Cookie injection failed — not logged in."}

            # Step 1 — Navigate to upload page
            logger.info("Step 1: Navigating to upload page…")
            self.driver.get(UPLOAD_URL)
            time.sleep(5)

            # Step 2 — Send video file
            logger.info("Step 2: Sending video file…")
            wait = WebDriverWait(self.driver, WAIT_MEDIUM)
            file_input = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="file"]'))
            )
            file_input.send_keys(video_path)
            logger.info("File sent: %s", video_path)

            # Step 3 — Wait for caption editor
            logger.info("Step 3: Waiting for video to process…")
            wait_long = WebDriverWait(self.driver, WAIT_LONG)
            wait_long.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[data-e2e="caption_container"]'))
            )
            time.sleep(3)

            # Step 4 — Dismiss joyride
            self._dismiss_joyride()

            # Step 5 — Fill caption
            logger.info("Step 5: Filling description…")
            full_caption = description
            if tags:
                hashtags = " ".join(f"#{t.lstrip('#')}" for t in tags)
                full_caption = f"{description} {hashtags}"
            self._fill_caption(full_caption)

            # Step 6 — Dismiss content-checks modal
            self._dismiss_content_checks_modal()

            # Step 7 — Click Post
            logger.info("Step 7: Clicking Post button…")
            posted = self._click_post()
            if not posted:
                return {"status": "failed", "message": "Could not click Post button."}

            # Modal may appear after clicking Post
            time.sleep(2)
            self._dismiss_content_checks_modal()

            # Step 8 — Wait for success
            logger.info("Step 8: Waiting for success confirmation…")
            success = self._wait_for_success()
            if success:
                logger.info("Upload successful!")
                return {"status": "success", "message": "Video uploaded successfully."}
            else:
                return {
                    "status": "failed",
                    "message": "Post button was clicked but success confirmation not detected.",
                }

        except Exception as exc:
            logger.exception("Unhandled error during upload: %s", exc)
            return {"status": "failed", "message": f"Unexpected error: {exc}"}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dismiss_joyride(self):
        try:
            buttons = self.driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                if btn.text.strip().lower() in ("got it", "skip", "next", "close"):
                    self.driver.execute_script("arguments[0].click();", btn)
                    logger.info("Dismissed joyride: '%s'", btn.text.strip())
                    time.sleep(1)
                    break
            self.driver.execute_script("""
                document.querySelectorAll('.react-joyride__overlay').forEach(e => e.remove());
                document.querySelectorAll('[class*="joyride"]').forEach(e => {
                    if (e.style) e.style.display = 'none';
                });
            """)
            time.sleep(0.5)
        except Exception as exc:
            logger.debug("Joyride dismiss: %s", exc)

    def _dismiss_content_checks_modal(self):
        try:
            buttons = self.driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                txt = btn.text.strip().lower()
                if txt in ("turn on", "cancel"):
                    self.driver.execute_script("arguments[0].click();", btn)
                    logger.info("Dismissed content-checks modal: '%s'", btn.text.strip())
                    time.sleep(1)
                    return
            close_btns = self.driver.find_elements(
                By.CSS_SELECTOR, '[aria-label="Close"], [aria-label="close"]'
            )
            for btn in close_btns:
                self.driver.execute_script("arguments[0].click();", btn)
                time.sleep(1)
                return
        except Exception as exc:
            logger.debug("Content-checks modal dismiss: %s", exc)

    def _fill_caption(self, text: str):
        wait = WebDriverWait(self.driver, WAIT_MEDIUM)
        try:
            editor = wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, '.public-DraftEditor-content[contenteditable="true"]')
                )
            )
            self.driver.execute_script("arguments[0].click();", editor)
            time.sleep(0.5)
            self.driver.execute_script("""
                var editor = arguments[0];
                editor.focus();
                document.execCommand('selectAll', false, null);
                document.execCommand('delete', false, null);
            """, editor)
            time.sleep(0.3)
            self.driver.execute_script("""
                var editor = arguments[0];
                editor.focus();
                document.execCommand('insertText', false, arguments[1]);
            """, editor, text)
            time.sleep(0.5)
            logger.info("Caption filled: %s", text[:60])
        except Exception as exc:
            logger.error("Failed to fill caption: %s", exc)
            try:
                editor = self.driver.find_element(
                    By.CSS_SELECTOR, '.public-DraftEditor-content[contenteditable="true"]'
                )
                self.driver.execute_script("arguments[0].click();", editor)
                time.sleep(0.3)
                editor.send_keys(Keys.CONTROL + "a")
                editor.send_keys(Keys.DELETE)
                editor.send_keys(text)
            except Exception as exc2:
                logger.error("Caption fallback failed: %s", exc2)

    def _click_post(self) -> bool:
        wait = WebDriverWait(self.driver, WAIT_MEDIUM)
        try:
            btn = wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, '[data-e2e="post_video_button"]')
                )
            )
            self.driver.execute_script("arguments[0].scrollIntoView(true);", btn)
            time.sleep(0.5)
            self.driver.execute_script("arguments[0].click();", btn)
            logger.info("Post button clicked (data-e2e).")
            return True
        except (TimeoutException, NoSuchElementException):
            pass

        try:
            buttons = self.driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                txt = btn.text.strip().lower()
                if txt in ("post", "publish"):
                    self.driver.execute_script("arguments[0].click();", btn)
                    logger.info("Post button clicked by text: '%s'", txt)
                    return True
        except Exception:
            pass

        logger.error("Post button not found.")
        return False

    def _wait_for_success(self) -> bool:
        for i in range(12):
            time.sleep(5)
            try:
                src = self.driver.page_source.lower()
                url = self.driver.current_url
                if any(w in src for w in ("uploaded", "your video is being", "manage your posts",
                                           "successfully", "being processed", "being uploaded")):
                    return True
                if "upload" not in url:
                    return True
            except Exception:
                pass
        return False
