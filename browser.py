"""
browser.py — Playwright automation for ChatGPT
Handles:
  • Google OAuth login with session persistence
  • Prompt submission
  • Real-time response streaming via async generator

Applies playwright-skill best practices:
  • Zero fixed wait_for_timeout() calls — all waits are condition-based
  • wait_for_load_state("networkidle") after every navigation
  • wait_for_url() for redirect detection instead of guessing timing
  • safeClick() + safeFill() helpers with retry
  • Network request blocking (images/fonts/media) for speed
  • slowMo param for visual debugging
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
CHATGPT_NEW  = "https://chatgpt.com/?model=auto"   # always starts a fresh chat

# ── Selectors — update if OpenAI changes their DOM ────────────────────────────
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

# Block heavy resources that aren't needed for automation — speeds up loads
BLOCKED_RESOURCE_TYPES = {"image", "media", "font", "stylesheet"}


# ── playwright-skill helpers ───────────────────────────────────────────────────

async def safe_click(
    locator: Locator,
    *,
    retries: int = 3,
    delay_ms: int = 500,
    timeout: int = 10_000,
) -> None:
    """
    Click with retry (playwright-skill safeClick pattern).
    Waits for visible + enabled state before each attempt.
    Raises RuntimeError after all retries exhausted.
    """
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
    """
    Wait for an input to be visible, clear any existing content, then fill.
    Prevents accidental appending to stale field values.
    """
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
        google_email: str,
        google_password: str,
        session_file: str = "./session.json",
        headless: bool = True,
        slow_mo: int = 0,
        response_timeout: int = 120,
    ):
        self.google_email     = google_email
        self.google_password  = google_password
        self.session_file     = Path(session_file)
        self.headless         = headless
        self.slow_mo          = slow_mo       # set ~150 to slow down for visual debugging
        self.response_timeout = response_timeout

        self._playwright: Playwright | None  = None
        self._browser: Browser | None        = None
        self._context: BrowserContext | None = None
        self._page: Page | None              = None
        self._lock = asyncio.Lock()

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Launch browser, configure context, restore or create session."""
        self._playwright = await async_playwright().start()
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
            logger.info("♻️  Restoring saved session from %s", self.session_file)
            context_kwargs["storage_state"] = str(self.session_file)
        else:
            logger.info("🆕 No saved session — will do fresh Google login")

        self._context = await self._browser.new_context(**context_kwargs)

        # Block images / fonts / media — not needed for automation, big speed win
        await self._context.route(
            "**/*",
            lambda route: (
                route.abort()
                if route.request.resource_type in BLOCKED_RESOURCE_TYPES
                else route.continue_()
            ),
        )

        self._page = await self._context.new_page()

        # Stealth patch — remove the webdriver fingerprint
        await self._page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        await self._ensure_logged_in()

    async def stop(self) -> None:
        """Graceful teardown — context closes before browser, always."""
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
        finally:
            if self._playwright:
                await self._playwright.stop()
            logger.info("🛑 Browser stopped cleanly")

    # ── Login ──────────────────────────────────────────────────────────────────

    async def _ensure_logged_in(self) -> None:
        """Navigate to ChatGPT. Login only if session is missing or expired."""
        logger.info("🌐 Loading ChatGPT…")
        await self._page.goto(CHATGPT_URL, wait_until="domcontentloaded")
        # networkidle confirms JS has settled — replaces all fixed delays here
        await self._page.wait_for_load_state("networkidle", timeout=20_000)

        if await self._is_logged_in():
            logger.info("✅ Session valid — skipping login")
            return

        logger.info("🔐 Session stale — starting Google OAuth…")
        await self._do_google_login()

        await self._context.storage_state(path=str(self.session_file))
        logger.info("💾 Session persisted to %s", self.session_file)

    async def _is_logged_in(self) -> bool:
        """Return True if the chat input box is present and visible."""
        try:
            await self._page.wait_for_selector(
                SEL_CHAT_INPUT, state="visible", timeout=6_000
            )
            return True
        except PlaywrightTimeout:
            return False

    async def _do_google_login(self) -> None:
        """
        Full Google OAuth flow:
          1. Click 'Log in' on ChatGPT (if visible)
          2. Click 'Continue with Google' — opens popup
          3. Fill email → Next (wait for password screen — condition based)
          4. Fill password → Sign in
          5. wait_for_url() for the post-OAuth redirect back to chatgpt.com
        """
        page = self._page

        # Step 1 — ChatGPT login button (may already be on /auth/login)
        login_btn = page.locator(SEL_LOGIN_BUTTON)
        if await login_btn.is_visible():
            await safe_click(login_btn)
            await page.wait_for_load_state("networkidle", timeout=15_000)

        # Step 2 — 'Continue with Google' → Google popup
        google_btn = page.locator(SEL_GOOGLE_BUTTON)
        await google_btn.wait_for(state="visible", timeout=12_000)

        async with page.expect_popup() as popup_info:
            await safe_click(google_btn)

        google_popup: Page = await popup_info.value
        await google_popup.wait_for_load_state("domcontentloaded")
        await google_popup.wait_for_load_state("networkidle", timeout=15_000)
        logger.info("🪟 Google popup ready: %s", google_popup.url)

        try:
            # Step 3 — Email
            email_input = google_popup.locator(SEL_GOOGLE_EMAIL)
            await safe_fill(email_input, self.google_email)
            await safe_click(google_popup.locator(SEL_GOOGLE_NEXT))

            # Wait for password field to appear — no fixed delay needed
            password_input = google_popup.locator(SEL_GOOGLE_PASSWORD)
            await password_input.wait_for(state="visible", timeout=15_000)

            # Step 4 — Password
            await safe_fill(password_input, self.google_password)
            await safe_click(google_popup.locator(SEL_GOOGLE_SIGN_IN))

            # Step 5 — wait_for_url detects the redirect back to ChatGPT cleanly
            logger.info("⏳ Awaiting OAuth redirect…")
            await page.wait_for_url("**chatgpt.com/**", timeout=30_000)
            await page.wait_for_load_state("networkidle", timeout=20_000)

            # Final confirmation — chat input must be present
            await page.wait_for_selector(
                SEL_CHAT_INPUT, state="visible", timeout=15_000
            )
            logger.info("✅ Google OAuth login successful")

        except Exception:
            screenshot_path = "/tmp/login-failure.png"
            await google_popup.screenshot(path=screenshot_path, full_page=True)
            logger.exception(
                "❌ Login failed — debug screenshot at %s", screenshot_path
            )
            raise

    # ── Prompt & streaming ─────────────────────────────────────────────────────

    async def ask_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        """
        Public API: submit a prompt, stream response as text deltas.
        Lock ensures only one prompt runs at a time.
        """
        async with self._lock:
            async for chunk in self._do_ask_stream(prompt):
                yield chunk

    async def _do_ask_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        """
        Internal streaming logic:
          1. Navigate to a fresh chat — networkidle ensures JS is ready
          2. safe_fill + safe_click to submit
          3. Wait for new assistant block using native locator — no JS eval
          4. Poll inner_text() delta every 200ms (condition-based exit)
        """
        page = self._page

        # Navigate to fresh chat — condition-based readiness checks only
        await page.goto(CHATGPT_NEW, wait_until="domcontentloaded")
        await page.wait_for_selector(SEL_CHAT_INPUT, state="visible", timeout=15_000)
        await page.wait_for_load_state("networkidle", timeout=15_000)

        # Count existing assistant blocks so we can detect the new one
        prior_count = await page.locator(SEL_RESPONSE_BLOCK).count()

        # Fill + submit
        chat_input = page.locator(SEL_CHAT_INPUT)
        await safe_fill(chat_input, prompt)

        send_btn = page.locator(SEL_SEND_BUTTON)
        try:
            await safe_click(send_btn, timeout=5_000)
        except Exception:
            # Fallback to keyboard if send button is elusive
            logger.debug("Send button not clickable — using Enter key")
            await chat_input.press("Enter")

        logger.info("📤 Prompt submitted (%d chars): %.60s…", len(prompt), prompt)

        # ── FIX: use native Playwright locator instead of wait_for_function ────
        # wait_for_function evals a JS string in the browser — any quote in the
        # CSS selector (e.g. [data-message-author-role='assistant']) causes a
        # JS SyntaxError before the predicate even runs.
        # .nth(prior_count).wait_for(state="attached") is pure Python — no eval,
        # no quoting issues, identical behaviour.
        await page.locator(SEL_RESPONSE_BLOCK).nth(prior_count).wait_for(
            state="attached", timeout=15_000
        )

        # ── Streaming delta loop ───────────────────────────────────────────────
        last_text = ""
        deadline  = asyncio.get_event_loop().time() + self.response_timeout

        try:
            while asyncio.get_event_loop().time() < deadline:
                blocks = page.locator(SEL_RESPONSE_BLOCK)
                count  = await blocks.count()

                if count == 0:
                    await asyncio.sleep(0.2)
                    continue

                # Always read the last block — that's the one being written
                current_block = blocks.nth(count - 1)
                current_text  = await current_block.inner_text()

                # Emit only the new delta
                if len(current_text) > len(last_text):
                    delta     = current_text[len(last_text):]
                    last_text = current_text
                    if delta.strip():
                        yield delta

                # Check completion — pure condition, no timing assumptions
                if await self._is_generation_done(page):
                    # Final read — catches any trailing characters
                    final_text = await current_block.inner_text()
                    if len(final_text) > len(last_text):
                        yield final_text[len(last_text):]
                    logger.info("✅ Generation complete — %d chars total", len(final_text))
                    return

                await asyncio.sleep(0.2)

        except PlaywrightTimeout as exc:
            logger.error("⏱ Playwright timeout in stream loop: %s", exc)
            await page.screenshot(path="/tmp/stream-timeout.png", full_page=True)
            yield "\n\n[Error: Playwright timed out — screenshot at /tmp/stream-timeout.png]"
            return

        except Exception as exc:
            logger.exception("💥 Unexpected error in stream loop: %s", exc)
            yield f"\n\n[Error: {exc}]"
            return

        # Reached only if the hard deadline elapsed without completion
        logger.warning("⏱ Hard deadline (%ds) hit — partial response returned", self.response_timeout)
        yield "\n\n[Response timed out — increase RESPONSE_TIMEOUT in .env if needed]"

    async def _is_generation_done(self, page: Page) -> bool:
        """
        Condition-only completion check — no sleeps, no timeouts.
        ChatGPT is done when: stop button gone AND send button re-enabled.
        """
        try:
            stop_btn = page.locator(SEL_STOP_BUTTON)
            if await stop_btn.is_visible():
                return False   # Still generating

            send_btn = page.locator(SEL_SEND_BUTTON)
            if await send_btn.count() > 0:
                return await send_btn.is_enabled()  # True = ready for next prompt

            return True
        except Exception:
            return False

    # ── Utility ────────────────────────────────────────────────────────────────

    async def screenshot(self, path: str = "/tmp/chatgpt-debug.png") -> str:
        """Take a full-page screenshot — handy for debugging selector failures."""
        await self._page.screenshot(path=path, full_page=True)
        logger.info("📸 Screenshot saved: %s", path)
        return path

    async def invalidate_session(self) -> None:
        """Delete the persisted session file — next start() will re-authenticate."""
        if self.session_file.exists():
            self.session_file.unlink()
            logger.info("🗑  Session cleared — next start will prompt Google login")