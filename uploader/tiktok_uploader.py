"""
TikTok video uploader using Selenium.
Handles cookie-based authentication and video upload via the TikTok web interface.
Each account gets an isolated Chrome profile (user-data-dir).
Browsers are created on demand and closed after each operation.
"""

import glob as globmod
import logging
import os
import re
import shutil
import signal
import threading
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

UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload"
TIKTOK_HOME = "https://www.tiktok.com"

WAIT_SHORT = 10
WAIT_MEDIUM = 30
WAIT_LONG = 120


class TikTokUploader:
    def __init__(self):
        self._profiles_dir = os.environ.get(
            "CHROME_PROFILES_DIR",
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "profiles"),
        )
        os.makedirs(self._profiles_dir, exist_ok=True)
        self._active_drivers: dict[int, webdriver.Chrome] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Profile paths
    # ------------------------------------------------------------------

    def _profile_dir(self, account_id: int) -> str:
        return os.path.join(self._profiles_dir, str(account_id))

    def _temp_profile_dir(self, temp_id: int) -> str:
        return os.path.join(self._profiles_dir, f"_tmp_{abs(temp_id)}")

    # ------------------------------------------------------------------
    # Driver lifecycle
    # ------------------------------------------------------------------

    def _build_options(self, profile_dir: str | None = None) -> ChromeOptions:
        options = ChromeOptions()
        if not os.environ.get("DISPLAY"):
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--lang=en-US")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-setuid-sandbox")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
        if profile_dir is not None:
            # Remove all stale lock files that prevent Chrome from starting
            for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"):
                lock_path = os.path.join(profile_dir, lock_name)
                if os.path.exists(lock_path) or os.path.islink(lock_path):
                    try:
                        os.remove(lock_path)
                        logger.info("Removed stale %s: %s", lock_name, lock_path)
                    except OSError:
                        pass
            options.add_argument(f"--user-data-dir={profile_dir}")

        chrome_binary = os.environ.get("CHROME_BINARY")
        if chrome_binary:
            options.binary_location = chrome_binary

        return options

    def _create_driver(self, profile_dir: str | None = None) -> webdriver.Chrome:
        logger.info("Creating Chrome driver (profile=%s)…", profile_dir)
        options = self._build_options(profile_dir)
        driver_path = os.environ.get("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")
        service = Service(executable_path=driver_path)

        try:
            driver = webdriver.Chrome(service=service, options=options)
        except WebDriverException as exc:
            # If Chrome crashed (e.g. X display not available), retry in headless mode
            if "Chrome instance exited" in str(exc) or "session not created" in str(exc):
                logger.warning("Chrome failed with display mode, retrying headless: %s", exc)
                options2 = self._build_options(profile_dir)
                options2.add_argument("--headless=new")
                service2 = Service(executable_path=driver_path)
                driver = webdriver.Chrome(service=service2, options=options2)
            else:
                raise

        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        })
        logger.info("Chrome driver started.")
        return driver

    def _close_driver(self, driver: webdriver.Chrome):
        try:
            pid = driver.service.process.pid
            driver.quit()
        except Exception as exc:
            logger.warning("Error closing driver: %s", exc)
            # Force-kill the chromedriver process if quit() failed
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Cookie injection
    # ------------------------------------------------------------------

    def inject_cookies(self, driver: webdriver.Chrome, cookies: list) -> bool:
        driver.get(TIKTOK_HOME)
        time.sleep(2)

        driver.delete_all_cookies()
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
                driver.add_cookie(clean)
                injected += 1
            except Exception as exc:
                logger.debug("Skipped cookie %s: %s", cookie.get("name"), exc)

        logger.info("Injected %d cookies.", injected)
        driver.refresh()
        time.sleep(3)
        return self._is_logged_in(driver)

    def _is_logged_in(self, driver: webdriver.Chrome) -> bool:
        try:
            cookie_names = {c["name"] for c in driver.get_cookies()}
            return "sessionid" in cookie_names or "sid_tt" in cookie_names
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Account verification
    # ------------------------------------------------------------------

    def verify_account(self, cookies: list) -> dict:
        """
        Create a temp browser with a temp profile, inject cookies, verify,
        scrape profile info, then close browser. Profile dir is kept so
        cookies persist for later use.
        Returns: valid, username, nickname, avatar_url, temp_id.
        """
        import random
        temp_id = random.randint(100_000, 999_999)
        profile_dir = self._temp_profile_dir(temp_id)
        os.makedirs(profile_dir, exist_ok=True)

        driver = self._create_driver(profile_dir)
        try:
            ok = self.inject_cookies(driver, cookies)
            if not ok:
                self._close_driver(driver)
                shutil.rmtree(profile_dir, ignore_errors=True)
                return {"valid": False, "username": "", "nickname": "", "avatar_url": "", "temp_id": None}

            username = ""
            nickname = ""
            avatar_url = ""

            try:
                time.sleep(2)
                user_info = driver.execute_script("""
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
                "temp_id": temp_id,
            }
        finally:
            # Always close browser — cookies are saved in profile dir
            self._close_driver(driver)

    def save_profile(self, temp_id: int, account_id: int):
        """Rename temp profile dir to the real account_id profile dir."""
        old_dir = self._temp_profile_dir(temp_id)
        new_dir = self._profile_dir(account_id)
        if not os.path.isdir(old_dir):
            return
        if os.path.isdir(new_dir):
            shutil.rmtree(new_dir, ignore_errors=True)
        try:
            os.rename(old_dir, new_dir)
            logger.info("Profile saved: %s → %s", old_dir, new_dir)
        except OSError as exc:
            logger.warning("Could not rename profile: %s", exc)

    def delete_profile(self, account_id: int):
        """Delete account's profile directory."""
        profile_dir = self._profile_dir(account_id)
        if os.path.isdir(profile_dir):
            shutil.rmtree(profile_dir, ignore_errors=True)
            logger.info("Profile deleted for account %d.", account_id)

    # ------------------------------------------------------------------
    # Video list
    # ------------------------------------------------------------------

    def get_video_list(self, account_id: int, cookies: list) -> list:
        """Scrape the video list from TikTok Studio content page using Selenium."""
        profile_dir = self._profile_dir(account_id)
        driver = self._create_driver(profile_dir)
        try:
            driver.get("https://www.tiktok.com/tiktokstudio/content")
            time.sleep(6)

            if "login" in driver.current_url.lower() or not self._is_logged_in(driver):
                ok = self.inject_cookies(driver, cookies)
                if not ok:
                    return []
                driver.get("https://www.tiktok.com/tiktokstudio/content")
                time.sleep(6)

            raw = driver.execute_script("""
                const videoLinks = [...document.querySelectorAll('a[href*="/video/"]')];
                const videos = videoLinks.map(link => {
                    const videoId = link.href.match(/\\/video\\/(\\d+)/)?.[1];
                    let container = link;
                    for (let i = 0; i < 8; i++) {
                        container = container.parentElement;
                        if (!container) break;
                        const txt = container.innerText || '';
                        if (txt.match(/\\d{1,3}(,\\d{3})*/) && txt.split('\\n').length > 3) break;
                    }
                    const img = container?.querySelector('img[src*="tiktok"]');
                    const allText = container?.innerText?.split('\\n').map(t => t.trim()).filter(t => t) || [];
                    return { videoId, url: link.href, thumbnail: img?.src || null, textContent: allText };
                }).filter(d => d && d.videoId);
                const seen = new Set();
                return videos.filter(d => !seen.has(d.videoId) && seen.add(d.videoId));
            """) or []

            def parse_stat(t: str):
                """Parse a stat string like '55K', '1,310', '1.2M', '289' → int."""
                t = t.strip().replace(',', '')
                if t.endswith('K') or t.endswith('k'):
                    try: return int(float(t[:-1]) * 1_000)
                    except ValueError: return None
                if t.endswith('M') or t.endswith('m'):
                    try: return int(float(t[:-1]) * 1_000_000)
                    except ValueError: return None
                try: return int(t)
                except ValueError: return None

            result = []
            months = ('Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec')
            for v in raw:
                text = v.get("textContent", [])
                duration = ""
                description = ""
                date_str = ""
                privacy = ""
                stats = []

                for t in text:
                    if not duration and len(t) <= 5 and t.count(':') == 1 and all(c.isdigit() or c == ':' for c in t):
                        duration = t
                    elif not date_str and any(m in t for m in months) and (',' in t or ':' in t):
                        date_str = t
                    elif t in ('Only me', 'Public', 'Friends', 'Followers only'):
                        privacy = t
                    elif re.match(r'^[\d.,]+[KkMm]?$', t):
                        val = parse_stat(t)
                        if val is not None:
                            stats.append(val)

                desc_candidates = [t for t in text if '#' in t or (len(t) > 15 and not any(m in t for m in months) and t.replace(',', '').replace(' ', '').replace(':', '').replace('.', '').isalnum() is False)]
                if not desc_candidates:
                    desc_candidates = [t for t in text if len(t) > 10 and not any(m in t for m in months) and not t.replace(',', '').isdigit() and t != duration and t != privacy]
                if desc_candidates:
                    description = max(desc_candidates, key=len)

                result.append({
                    "video_id": v.get("videoId"),
                    "url": v.get("url"),
                    "thumbnail": v.get("thumbnail"),
                    "duration": duration,
                    "description": description,
                    "date": date_str,
                    "privacy": privacy,
                    "views": stats[0] if len(stats) > 0 else 0,
                    "likes": stats[1] if len(stats) > 1 else 0,
                    "comments": stats[2] if len(stats) > 2 else 0,
                })
            return result
        finally:
            self._close_driver(driver)

    def get_video_deep_analytics(self, account_id: int, video_id: str, cookies: list) -> dict:
        """Scrape per-video deep analytics from TikTok Studio analytics page using Selenium."""
        profile_dir = self._profile_dir(account_id)
        driver = self._create_driver(profile_dir)
        try:
            url = f"https://www.tiktok.com/tiktokstudio/analytics/{video_id}"
            driver.get(url)
            time.sleep(5)

            if "login" in driver.current_url.lower() or not self._is_logged_in(driver):
                ok = self.inject_cookies(driver, cookies)
                if not ok:
                    return {"error": "Cookie injection failed"}
                driver.get(url)
                time.sleep(5)

            # Wait for the page to render stat labels
            try:
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//*[normalize-space(text())='Total play time' or normalize-space(text())='Video views']")
                    )
                )
                time.sleep(2)
            except TimeoutException:
                logger.warning("Timed out waiting for analytics page to load for video %s", video_id)

            data = driver.execute_script("""
                const allEls = [...document.querySelectorAll('*')].filter(
                    el => el.children.length === 0 && el.innerText && el.innerText.trim()
                );

                function getStat(label) {
                    const el = allEls.find(e => e.innerText.trim() === label);
                    if (!el) return null;
                    const gp = el.parentElement && el.parentElement.parentElement;
                    if (!gp) return null;
                    const lines = gp.innerText.trim().split('\\n').map(l => l.trim()).filter(l => l);
                    return lines.find(l => l !== label) || null;
                }

                const trafficLabels = ['For You', 'Personal profile', 'Other', 'Following',
                                       'Sound', 'Search', 'Hashtag', 'Direct message'];
                const traffic = {};
                for (const label of trafficLabels) {
                    const el = allEls.find(e => e.innerText.trim() === label);
                    if (!el) continue;
                    const gp = el.parentElement && el.parentElement.parentElement;
                    if (!gp) continue;
                    const lines = gp.innerText.trim().split('\\n').map(l => l.trim()).filter(l => l);
                    const val = lines.find(l => l !== label && (l.includes('%') || l.startsWith('<')));
                    if (val) traffic[label] = val;
                }

                let retentionDropout = null;
                const retEl = allEls.find(e => e.innerText.trim() === 'Retention rate');
                if (retEl) {
                    let ancestor = retEl.parentElement && retEl.parentElement.parentElement;
                    if (ancestor) {
                        const m = ancestor.innerText.match(/Most viewers stopped watching at (\\d+:\\d+)/);
                        if (m) retentionDropout = m[1];
                    }
                }

                return {
                    views: getStat('Video views'),
                    total_play_time: getStat('Total play time'),
                    avg_watch_time: getStat('Average watch time'),
                    watched_full_pct: getStat('Watched full video'),
                    new_followers: getStat('New followers'),
                    traffic_sources: traffic,
                    retention_dropout: retentionDropout,
                };
            """)
            return data or {}
        finally:
            self._close_driver(driver)

    def download_avatar(self, avatar_url: str, save_path: str) -> bool:
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
        profiles = [
            d for d in os.listdir(self._profiles_dir)
            if os.path.isdir(os.path.join(self._profiles_dir, d)) and not d.startswith("_tmp_")
        ]
        active = len(self._active_drivers)
        return {
            "alive": True,
            "accounts_with_profiles": len(profiles),
            "active_uploads": active,
        }

    # ------------------------------------------------------------------
    # Video upload
    # ------------------------------------------------------------------

    def upload_video(
        self,
        video_path: str,
        description: str,
        account_id: int,
        cookies: list,
        tags: list[str] | None = None,
    ) -> dict:
        video_path = str(Path(video_path).resolve())
        if not os.path.isfile(video_path):
            return {"status": "failed", "message": f"Video file not found: {video_path}"}

        # TikTok requires lowercase file extension
        ext = os.path.splitext(video_path)[1]
        if ext != ext.lower():
            new_path = os.path.splitext(video_path)[0] + ext.lower()
            shutil.copy2(video_path, new_path)
            logger.info("Copied to lowercase extension: %s → %s", video_path, new_path)
            video_path = new_path

        profile_dir = self._profile_dir(account_id)
        os.makedirs(profile_dir, exist_ok=True)

        logger.info("Starting upload for account %d: %s", account_id, video_path)

        driver = self._create_driver(profile_dir)
        with self._lock:
            self._active_drivers[account_id] = driver

        try:
            # Step 0 — Inject cookies to ensure session is valid
            logger.info("Step 0: Injecting cookies…")
            ok = self.inject_cookies(driver, cookies)
            if not ok:
                return {"status": "failed", "message": "Cookie injection failed — not logged in."}

            # Step 1 — Navigate to upload page
            logger.info("Step 1: Navigating to upload page…")
            driver.get(UPLOAD_URL)
            time.sleep(5)

            # Step 2 — Send video file via CDP
            logger.info("Step 2: Sending video file…")
            wait = WebDriverWait(driver, WAIT_MEDIUM)

            file_input = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="file"]'))
            )

            # Make visible and remove accept restriction
            driver.execute_script("""
                var el = arguments[0];
                el.style.display = 'block';
                el.style.opacity = '1';
                el.style.position = 'fixed';
                el.style.top = '0';
                el.style.left = '0';
                el.style.width = '200px';
                el.style.height = '50px';
                el.style.zIndex = '99999';
                el.removeAttribute('accept');
            """, file_input)
            time.sleep(0.5)

            # Try CDP first, then send_keys as fallback
            try:
                logger.info("Uploading file via CDP…")
                result = driver.execute_cdp_cmd("Runtime.evaluate", {
                    "expression": "document.querySelector('input[type=\"file\"]')",
                    "returnByValue": False,
                })
                remote_object_id = result["result"]["objectId"]
                dom_node = driver.execute_cdp_cmd("DOM.describeNode", {
                    "objectId": remote_object_id,
                })
                backend_node_id = dom_node["node"]["backendNodeId"]
                driver.execute_cdp_cmd("DOM.setFileInputFiles", {
                    "files": [video_path],
                    "backendNodeId": backend_node_id,
                })
                logger.info("CDP file set done.")
            except Exception as exc:
                logger.warning("CDP upload failed: %s, trying send_keys…", exc)
                file_input = driver.find_element(By.CSS_SELECTOR, 'input[type="file"]')
                file_input.send_keys(video_path)

            # Dispatch events (React needs them)
            time.sleep(1)
            driver.execute_script("""
                var el = document.querySelector('input[type="file"]');
                if (el) {
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                }
            """)
            logger.info("File sent: %s", video_path)

            # Step 3 — Wait for caption editor to appear (= TikTok accepted the file)
            logger.info("Step 3: Waiting for video to be accepted…")
            wait_long = WebDriverWait(driver, WAIT_LONG)
            caption_selectors = [
                '[contenteditable="true"]',
                '[data-e2e="caption_container"]',
                '.public-DraftEditor-content[contenteditable="true"]',
            ]
            caption_found = False
            for sel in caption_selectors:
                try:
                    wait_long.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                    caption_found = True
                    logger.info("Caption editor appeared (selector: %s) — file accepted!", sel)
                    break
                except TimeoutException:
                    continue
            if not caption_found:
                return {"status": "failed", "message": "Video file was not accepted — caption editor never appeared."}
            time.sleep(3)

            # Step 4 — Dismiss joyride
            self._dismiss_joyride(driver)

            # Step 6 — Fill caption
            logger.info("Step 6: Filling description…")
            full_caption = description
            if tags:
                hashtags = " ".join(f"#{t.lstrip('#')}" for t in tags)
                full_caption = f"{description} {hashtags}"
            self._fill_caption(driver, full_caption)

            # Step 7 — Dismiss content-checks modal
            self._dismiss_content_checks_modal(driver)

            # Step 8 — Click Post
            logger.info("Step 8: Clicking Post button…")
            posted = self._click_post(driver)
            if not posted:
                return {"status": "failed", "message": "Could not click Post button."}

            time.sleep(2)
            self._dismiss_content_checks_modal(driver)

            # Step 9 — Wait for success
            logger.info("Step 9: Waiting for success confirmation…")
            success = self._wait_for_success(driver)
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
        finally:
            with self._lock:
                self._active_drivers.pop(account_id, None)
            self._close_driver(driver)

    # ------------------------------------------------------------------
    # Clipboard (uses any active upload browser or creates a temp one)
    # ------------------------------------------------------------------

    def get_any_driver(self) -> webdriver.Chrome | None:
        for driver in self._active_drivers.values():
            try:
                _ = driver.title
                return driver
            except WebDriverException:
                continue
        return None

    def quit(self):
        with self._lock:
            for driver in self._active_drivers.values():
                try:
                    driver.quit()
                except Exception:
                    pass
            self._active_drivers.clear()
        logger.info("All active drivers closed.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dismiss_joyride(self, driver: webdriver.Chrome):
        try:
            buttons = driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                if btn.text.strip().lower() in ("got it", "skip", "next", "close"):
                    driver.execute_script("arguments[0].click();", btn)
                    logger.info("Dismissed joyride: '%s'", btn.text.strip())
                    time.sleep(1)
                    break
            driver.execute_script("""
                document.querySelectorAll('.react-joyride__overlay').forEach(e => e.remove());
                document.querySelectorAll('[class*="joyride"]').forEach(e => {
                    if (e.style) e.style.display = 'none';
                });
            """)
            time.sleep(0.5)
        except Exception as exc:
            logger.debug("Joyride dismiss: %s", exc)

    def _dismiss_content_checks_modal(self, driver: webdriver.Chrome):
        try:
            buttons = driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                txt = btn.text.strip().lower()
                if txt in ("turn on", "cancel"):
                    driver.execute_script("arguments[0].click();", btn)
                    logger.info("Dismissed content-checks modal: '%s'", btn.text.strip())
                    time.sleep(1)
                    return
            close_btns = driver.find_elements(
                By.CSS_SELECTOR, '[aria-label="Close"], [aria-label="close"]'
            )
            for btn in close_btns:
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(1)
                return
        except Exception as exc:
            logger.debug("Content-checks modal dismiss: %s", exc)

    def _fill_caption(self, driver: webdriver.Chrome, text: str):
        wait = WebDriverWait(driver, WAIT_MEDIUM)
        editor = None

        # TikTok Studio uses div[role="combobox"][contenteditable="true"] for description
        selectors = [
            '[role="combobox"][contenteditable="true"]',
            '.public-DraftEditor-content[contenteditable="true"]',
            '[contenteditable="true"]',
        ]
        for sel in selectors:
            try:
                editor = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                )
                logger.info("Caption editor found: %s", sel)
                break
            except TimeoutException:
                continue

        if not editor:
            logger.error("No caption editor found.")
            return

        try:
            driver.execute_script("arguments[0].click();", editor)
            time.sleep(0.5)
            # Clear existing text and type new
            driver.execute_script("""
                var editor = arguments[0];
                editor.focus();
                document.execCommand('selectAll', false, null);
                document.execCommand('delete', false, null);
            """, editor)
            time.sleep(0.3)
            driver.execute_script("""
                var editor = arguments[0];
                editor.focus();
                document.execCommand('insertText', false, arguments[1]);
            """, editor, text)
            time.sleep(0.5)
            logger.info("Caption filled: %s", text[:60])
        except Exception as exc:
            logger.error("Failed to fill caption via execCommand: %s", exc)
            try:
                editor = driver.find_element(
                    By.CSS_SELECTOR, '[role="combobox"][contenteditable="true"]'
                )
                driver.execute_script("arguments[0].click();", editor)
                time.sleep(0.3)
                editor.send_keys(Keys.CONTROL + "a")
                editor.send_keys(Keys.DELETE)
                editor.send_keys(text)
            except Exception as exc2:
                logger.error("Caption fallback failed: %s", exc2)

    def _is_post_button_disabled(self, driver: webdriver.Chrome, btn) -> bool:
        """Check if Post button is disabled via attribute, aria, or CSS class."""
        try:
            return driver.execute_script("""
                var btn = arguments[0];
                if (btn.disabled) return true;
                if (btn.getAttribute('aria-disabled') === 'true') return true;
                var cls = btn.className || '';
                if (cls.includes('disabled') || cls.includes('Disabled')) return true;
                var style = window.getComputedStyle(btn);
                if (style.pointerEvents === 'none') return true;
                if (style.opacity && parseFloat(style.opacity) < 0.5) return true;
                return false;
            """, btn)
        except Exception:
            return True

    def _click_post(self, driver: webdriver.Chrome) -> bool:
        # Wait for Post button to exist and become enabled
        logger.info("Waiting for Post button to become clickable…")
        for attempt in range(60):
            btn = None
            # Try data-e2e selectors
            for selector in ('[data-e2e="post_video_button"]', '[data-e2e="post_button"]'):
                try:
                    btn = driver.find_element(By.CSS_SELECTOR, selector)
                    break
                except NoSuchElementException:
                    continue

            # Fallback: find by text
            if btn is None:
                try:
                    for b in driver.find_elements(By.TAG_NAME, "button"):
                        if b.text.strip().lower() in ("post", "publish"):
                            btn = b
                            break
                except Exception:
                    pass

            if btn is None:
                logger.debug("Post button not found yet (attempt %d)", attempt)
                time.sleep(5)
                continue

            if self._is_post_button_disabled(driver, btn):
                logger.info("Post button disabled, waiting… (attempt %d)", attempt)
                time.sleep(5)
                continue

            logger.info("Post button is enabled (attempt %d), clicking…", attempt)
            driver.execute_script("arguments[0].scrollIntoView(true);", btn)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", btn)
            logger.info("Post button clicked.")
            return True

        logger.error("Post button not found or stayed disabled for 5 min.")
        return False

    def _wait_for_success(self, driver: webdriver.Chrome) -> bool:
        for i in range(12):
            time.sleep(5)
            try:
                url = driver.current_url
                # TikTok Studio redirects to /tiktokstudio/content on success
                if "/tiktokstudio/content" in url:
                    return True
                if "upload" not in url:
                    return True
                src = driver.page_source.lower()
                if any(w in src for w in ("uploaded", "your video is being", "manage your posts",
                                           "successfully", "being processed", "being uploaded",
                                           "post published", "content under review")):
                    return True
            except Exception:
                pass
        return False
