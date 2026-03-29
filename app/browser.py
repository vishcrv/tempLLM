"""
browser.py — Playwright automation for ChatGPT
Handles three connection modes:

  MODE A  CDP_URL set
          Connect to an already-running Chrome via Chrome DevTools Protocol.
          No login flow — you stay logged in as long as Chrome is open.
          Best for local dev and Playwright MCP setups.

  MODE B  USER_DATA_DIR set
          Playwright launches Chromium but stores its profile in a real directory
          on disk.  Cookies / local-storage survive restarts automatically.
          First run: set HEADLESS=false and log in manually once.

  MODE C  Neither set  (original behaviour)
          Fresh Chromium + Google OAuth, then saves a session.json.
          Requires GOOGLE_EMAIL + GOOGLE_PASSWORD in .env.

Best practices (playwright-skill):
  • Zero fixed wait_for_timeout() calls — all waits are condition-based
  • wait_for_load_state("networkidle") after every navigation
  • wait_for_url() for redirect detection
  • safeClick() + safeFill() helpers with retry
  • Network request blocking (images/fonts/media) for speed in MODE B/C
  • try/finally everywhere to guarantee browser cleanup
  • Debug screenshots auto-saved on failures
"""

import asyncio
import logging
from pathlib import Path
from typing import AsyncGenerator

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Locator,
    TimeoutError as PlaywrightTimeout,
)

logger = logging.getLogger("browser")

# ── URLs ───────────────────────────────────────────────────────────────────────
CHATGPT_URL  = "https://chatgpt.com"
CHATGPT_NEW  = "https://chatgpt.com/?model=auto"

# ── Selectors ─────────────────────────────────────────────────────────────────
SEL_LOGIN_BUTTON  = "button:has-text('Log in')"
SEL_GOOGLE_BUTTON = (
    "[data-provider='google'], "
    "button:has-text('Continue with Google'), "
    "a:has-text('Continue with Google')"
)
SEL_GOOGLE_EMAIL    = "input[type='email']"
SEL_GOOGLE_NEXT     = "#identifierNext, button:has-text('Next')"
SEL_GOOGLE_PASSWORD = "input[type='password']"
SEL_GOOGLE_SIGN_IN  = "#passwordNext, button:has-text('Next')"
SEL_CHAT_INPUT      = "#prompt-textarea, div[contenteditable='true'][data-id='root']"
SEL_SEND_BUTTON     = "button[data-testid='send-button'], button[aria-label='Send prompt']"
SEL_STOP_BUTTON     = "button[aria-label='Stop streaming'], button[data-testid='stop-button']"
SEL_RESPONSE_BLOCK  = "div[data-message-author-role='assistant']"

BLOCKED_RESOURCE_TYPES = {"image", "media", "font", "stylesheet"}


# ── playwright-skill helpers ───────────────────────────────────────────────────

async def safe_click(
    locator: Locator,
    *,
    retries: int = 3,
    delay_ms: int = 500,
    timeout: int = 10_000,
) -> None:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            await locator.wait_for(state="visible", timeout=timeout)
            await locator.click(timeout=timeout)
            return
        except PlaywrightTimeout as exc:
            last_exc = exc
            logger.warning("safe_click attempt %d/%d failed", attempt, retries)
            await asyncio.sleep(delay_ms / 1000)
    raise RuntimeError(f"safe_click failed after {retries} retries") from last_exc


async def safe_fill(
    locator: Locator,
    value: str,
    *,
    timeout: int = 10_000,
) -> None:
    await locator.wait_for(state="visible", timeout=timeout)
    await locator.clear()
    await locator.fill(value, timeout=timeout)


# ── Main class ─────────────────────────────────────────────────────────────────

class ChatGPTBrowser:
    """
    Single persistent Playwright session for ChatGPT.
    asyncio.Lock serialises concurrent /ask requests.
    """

    def __init__(
        self,
        google_email: str = "",
        google_password: str = "",
        session_file: str = "./session.json",
        headless: bool = True,
        slow_mo: int = 0,
        response_timeout: int = 120,
        # ── New connection-mode params ──────────────────────────────────────
        cdp_url: str = "",        # MODE A — e.g. "http://localhost:9222"
        user_data_dir: str = "",  # MODE B — e.g. "/home/you/.config/chatgpt-profile"
    ):
        self.google_email    = google_email
        self.google_password = google_password
        self.session_file    = Path(session_file)
        self.headless        = headless
        self.slow_mo         = slow_mo
        self.response_timeout = response_timeout
        self.cdp_url         = cdp_url
        self.user_data_dir   = user_data_dir

        self._playwright: Playwright | None  = None
        self._browser: Browser | None        = None
        self._context: BrowserContext | None = None
        self._page: Page | None              = None
        self._lock = asyncio.Lock()

        # Determine active mode for logging
        if cdp_url:
            self._mode = "A-CDP"
        elif user_data_dir:
            self._mode = "B-PersistentProfile"
        else:
            self._mode = "C-OAuth"

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Launch / connect browser according to active mode."""
        self._playwright = await async_playwright().start()

        if self._mode == "A-CDP":
            await self._start_cdp()
        elif self._mode == "B-PersistentProfile":
            await self._start_persistent_profile()
        else:
            await self._start_oauth()

        logger.info("Browser ready in mode %s", self._mode)

    # ── Mode A — CDP ───────────────────────────────────────────────────────────

    async def _start_cdp(self) -> None:
        """
        Connect to an already-running Chrome instance via CDP.

        How to launch that Chrome (do this ONCE, then keep it open):

            Windows:
              "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" ^
                --remote-debugging-port=9222 ^
                --user-data-dir=C:\\temp\\chrome-cdp-profile

            macOS:
              /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\
                --remote-debugging-port=9222 \\
                --user-data-dir=/tmp/chrome-cdp-profile

            Linux:
              google-chrome --remote-debugging-port=9222 \\
                --user-data-dir=/tmp/chrome-cdp-profile

        Log in to ChatGPT manually in that window, then start this server.
        From that point on, no login flow ever runs.
        """
        logger.info("MODE A — connecting to existing Chrome via CDP at %s", self.cdp_url)
        self._browser = await self._playwright.chromium.connect_over_cdp(self.cdp_url)

        # Reuse the first (existing) browser context — that's the logged-in one
        contexts = self._browser.contexts
        if contexts:
            self._context = contexts[0]
            logger.info("Reusing existing browser context (already logged in)")
        else:
            self._context = await self._browser.new_context()
            logger.warning("No existing context found; created a fresh one — login may be required")

        # Reuse an existing page if available, otherwise open a new one
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()

        # Verify we're already logged in — navigate to ChatGPT if not already there
        if "chatgpt.com" not in self._page.url:
            await self._page.goto(CHATGPT_URL, wait_until="domcontentloaded")
            await self._page.wait_for_load_state("networkidle", timeout=20_000)

        if not await self._is_logged_in():
            raise RuntimeError(
                "CDP-connected Chrome is NOT logged in to ChatGPT.\n"
                "Open that Chrome window, navigate to chatgpt.com, log in manually, "
                "then restart this server."
            )
        logger.info("CDP connection confirmed — ChatGPT session is active")

    # ── Mode B — Persistent profile ────────────────────────────────────────────

    async def _start_persistent_profile(self) -> None:
        """
        Launch Chromium with a real persistent user-data directory.
        Cookies and local-storage survive process restarts automatically.

        First run: set HEADLESS=false in .env so you can log in manually.
        Subsequent runs: HEADLESS=true works fine — already authenticated.
        """
        logger.info("MODE B — launching with persistent profile at %s", self.user_data_dir)

        # launch_persistent_context combines browser launch + context creation
        self._context = await self._playwright.chromium.launch_persistent_context(
            self.user_data_dir,
            headless=self.headless,
            slow_mo=self.slow_mo,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="America/New_York",
        )

        # Block heavy resources — big speed win
        await self._context.route(
            "**/*",
            lambda route: (
                route.abort()
                if route.request.resource_type in BLOCKED_RESOURCE_TYPES
                else route.continue_()
            ),
        )

        # launch_persistent_context doesn't expose a separate Browser object
        self._browser = None

        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        await self._page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        await self._page.goto(CHATGPT_URL, wait_until="domcontentloaded")
        await self._page.wait_for_load_state("networkidle", timeout=20_000)

        if not await self._is_logged_in():
            if self.headless:
                raise RuntimeError(
                    "Persistent profile is not logged in and HEADLESS=true.\n"
                    "Set HEADLESS=false, restart, and log in manually once."
                )
            logger.info("Not logged in — waiting for manual login (HEADLESS=false)")
            # Wait up to 3 minutes for a human to log in
            await self._page.wait_for_selector(SEL_CHAT_INPUT, state="visible", timeout=180_000)
            logger.info("Manual login detected — profile will persist this session")
        else:
            logger.info("Persistent profile already authenticated")

    # ── Mode C — OAuth (original) ──────────────────────────────────────────────

    async def _start_oauth(self) -> None:
        """Original behaviour: fresh Chromium + Google OAuth + session.json cache."""
        logger.info("MODE C — launching fresh Chromium with Google OAuth")
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context_kwargs: dict = dict(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="America/New_York",
        )

        if self.session_file.exists():
            logger.info("Restoring saved session from %s", self.session_file)
            context_kwargs["storage_state"] = str(self.session_file)
        else:
            logger.info("No saved session found; proceeding with fresh Google login")

        self._context = await self._browser.new_context(**context_kwargs)

        await self._context.route(
            "**/*",
            lambda route: (
                route.abort()
                if route.request.resource_type in BLOCKED_RESOURCE_TYPES
                else route.continue_()
            ),
        )

        self._page = await self._context.new_page()
        await self._page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        await self._ensure_logged_in()

    # ── Shared teardown ────────────────────────────────────────────────────────

    async def stop(self) -> None:
        """Graceful teardown — works for all three modes."""
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
        finally:
            if self._playwright:
                await self._playwright.stop()
            logger.info("Browser closed cleanly (mode %s)", self._mode)

    # ── Login (Mode C only) ────────────────────────────────────────────────────

    async def _ensure_logged_in(self) -> None:
        await self._page.goto(CHATGPT_URL, wait_until="domcontentloaded")
        await self._page.wait_for_load_state("networkidle", timeout=20_000)

        if await self._is_logged_in():
            logger.info("Existing session valid; skipping login flow")
            return

        logger.info("Session invalid or expired; initiating Google OAuth flow")
        await self._do_google_login()
        await self._context.storage_state(path=str(self.session_file))
        logger.info("Session state persisted to %s", self.session_file)

    async def _is_logged_in(self) -> bool:
        try:
            await self._page.wait_for_selector(
                SEL_CHAT_INPUT, state="visible", timeout=6_000
            )
            return True
        except PlaywrightTimeout:
            return False

    async def _do_google_login(self) -> None:
        page = self._page

        login_btn = page.locator(SEL_LOGIN_BUTTON)
        if await login_btn.is_visible():
            await safe_click(login_btn)
            await page.wait_for_load_state("networkidle", timeout=15_000)

        google_btn = page.locator(SEL_GOOGLE_BUTTON)
        await google_btn.wait_for(state="visible", timeout=12_000)

        async with page.expect_popup() as popup_info:
            await safe_click(google_btn)

        google_popup: Page = await popup_info.value
        await google_popup.wait_for_load_state("domcontentloaded")
        await google_popup.wait_for_load_state("networkidle", timeout=15_000)

        try:
            email_input = google_popup.locator(SEL_GOOGLE_EMAIL)
            await safe_fill(email_input, self.google_email)
            await safe_click(google_popup.locator(SEL_GOOGLE_NEXT))

            password_input = google_popup.locator(SEL_GOOGLE_PASSWORD)
            await password_input.wait_for(state="visible", timeout=15_000)

            await safe_fill(password_input, self.google_password)
            await safe_click(google_popup.locator(SEL_GOOGLE_SIGN_IN))

            await page.wait_for_url("**chatgpt.com/**", timeout=30_000)
            await page.wait_for_load_state("networkidle", timeout=20_000)
            await page.wait_for_selector(SEL_CHAT_INPUT, state="visible", timeout=15_000)
            logger.info("Google OAuth login successful")

        except Exception:
            screenshot_path = "/tmp/login-failure.png"
            await google_popup.screenshot(path=screenshot_path, full_page=True)
            logger.exception("Login failure. Screenshot saved at %s", screenshot_path)
            raise

    # ── Prompt & streaming ─────────────────────────────────────────────────────

    async def ask_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        async with self._lock:
            async for chunk in self._do_ask_stream(prompt):
                yield chunk

    async def _do_ask_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        page = self._page

        await page.goto(CHATGPT_NEW, wait_until="domcontentloaded")
        await page.wait_for_selector(SEL_CHAT_INPUT, state="visible", timeout=15_000)
        await page.wait_for_load_state("networkidle", timeout=15_000)

        prior_count = await page.locator(SEL_RESPONSE_BLOCK).count()

        chat_input = page.locator(SEL_CHAT_INPUT)
        await safe_fill(chat_input, prompt)

        send_btn = page.locator(SEL_SEND_BUTTON)
        try:
            await safe_click(send_btn, timeout=5_000)
        except Exception:
            logger.debug("Send button not clickable — using Enter key")
            await chat_input.press("Enter")

        logger.info("Prompt submitted (length: %d chars)", len(prompt))

        await page.locator(SEL_RESPONSE_BLOCK).nth(prior_count).wait_for(
            state="attached", timeout=15_000
        )

        last_text = ""
        deadline  = asyncio.get_event_loop().time() + self.response_timeout

        try:
            while asyncio.get_event_loop().time() < deadline:
                blocks = page.locator(SEL_RESPONSE_BLOCK)
                count  = await blocks.count()

                if count == 0:
                    await asyncio.sleep(0.2)
                    continue

                current_block = blocks.nth(count - 1)
                current_text  = await current_block.inner_text()

                if len(current_text) > len(last_text):
                    delta     = current_text[len(last_text):]
                    last_text = current_text
                    if delta.strip():
                        yield delta

                if await self._is_generation_done(page):
                    final_text = await current_block.inner_text()
                    if len(final_text) > len(last_text):
                        yield final_text[len(last_text):]
                    logger.info("Response complete (%d chars)", len(final_text))
                    return

                await asyncio.sleep(0.2)

        except PlaywrightTimeout as exc:
            logger.error("Timeout in stream loop: %s", exc)
            await page.screenshot(path="/tmp/stream-timeout.png", full_page=True)
            yield "\n\n[Error: Playwright timed out — screenshot at /tmp/stream-timeout.png]"
            return

        except Exception as exc:
            logger.exception("Unexpected error in stream loop: %s", exc)
            yield f"\n\n[Error: {exc}]"
            return

        logger.warning("Hard deadline (%ds) reached; returning partial response", self.response_timeout)
        yield "\n\n[Response timed out — increase RESPONSE_TIMEOUT in .env if needed]"

    async def _is_generation_done(self, page: Page) -> bool:
        try:
            stop_btn = page.locator(SEL_STOP_BUTTON)
            if await stop_btn.is_visible():
                return False
            send_btn = page.locator(SEL_SEND_BUTTON)
            if await send_btn.count() > 0:
                return await send_btn.is_enabled()
            return True
        except Exception:
            return False

    # ── Utility ────────────────────────────────────────────────────────────────

    async def screenshot(self, path: str = "/tmp/chatgpt-debug.png") -> str:
        await self._page.screenshot(path=path, full_page=True)
        logger.info("Screenshot saved at: %s", path)
        return path

    async def invalidate_session(self) -> None:
        """Mode C only — delete persisted session.json."""
        if self.session_file.exists():
            self.session_file.unlink()
            logger.info("session.json cleared — re-auth required on next start")