"""
browser.py — Playwright automation for ChatGPT

Two connection modes, selected automatically at startup:

  MODE A  CDP_URL is set AND Chrome is actually reachable
          ─────────────────────────────────────────────────
          A lightweight HTTP probe hits /json/version before Playwright
          is involved. If the port is closed the probe fails in <5 ms
          and we skip straight to Mode B — no long Playwright timeouts.

          Launch Chrome once (keep the window open):

            Windows (PowerShell):
              & "C:\Program Files\Google\Chrome\Application\chrome.exe" `
                --remote-debugging-port=9222 `
                --user-data-dir=C:\temp\chrome-cdp-profile

            macOS / Linux:
              google-chrome --remote-debugging-port=9222 \
                --user-data-dir=/tmp/chrome-cdp-profile

          Log in to ChatGPT in that window, then start this server.

  MODE B  CDP_URL not set  OR  Chrome not reachable  (automatic fallback)
          ──────────────────────────────────────────────────────────────
          Playwright launches a fresh Chromium, restores session.json if
          it exists, and navigates to ChatGPT.
          No login flow is ever attempted. If ChatGPT is not authenticated
          the server raises immediately with a debug screenshot.

Cross-platform (Windows + Linux):
  • HTTP probe uses only stdlib — zero extra deps
  • Platform-specific Chromium launch args (Linux sandbox flags omitted on Windows)
  • Screenshot paths use ./ (works on both OSes)

Best practices (playwright-skill):
  • Zero fixed wait_for_timeout() calls — all waits are condition-based
  • wait_for_load_state("networkidle") after every navigation
  • safeClick() + safeFill() helpers with retry
  • Named route handler (no lambda closure surprises)
  • try/finally everywhere to guarantee browser cleanup
  • Debug screenshots auto-saved on failures
"""

import asyncio
import logging
import platform
import urllib.error
import urllib.request
from pathlib import Path
from typing import AsyncGenerator

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Locator,
    Route,
    TimeoutError as PlaywrightTimeout,
)

logger = logging.getLogger("browser")

# ── URLs ───────────────────────────────────────────────────────────────────────
CHATGPT_URL = "https://chatgpt.com"
CHATGPT_NEW = "https://chatgpt.com/?model=auto"

# ── Selectors ─────────────────────────────────────────────────────────────────
SEL_CHAT_INPUT     = "#prompt-textarea, div[contenteditable='true'][data-id='root']"
SEL_SEND_BUTTON    = "button[data-testid='send-button'], button[aria-label='Send prompt']"
SEL_STOP_BUTTON    = "button[aria-label='Stop streaming'], button[data-testid='stop-button']"
SEL_RESPONSE_BLOCK = "div[data-message-author-role='assistant']"

BLOCKED_RESOURCE_TYPES = {"image", "media", "font", "stylesheet"}

IS_WINDOWS = platform.system() == "Windows"


# ── HTTP pre-flight probe ──────────────────────────────────────────────────────

async def _cdp_is_reachable(cdp_url: str, timeout: float = 2.0) -> bool:
    """
    Probe Chrome's CDP /json/version endpoint with a plain HTTP GET.

    Completes in <5 ms when Chrome is not running (immediate connection
    refused) — no Playwright connection attempt, no long timeout.
    Returns True only when Chrome is up and answering on that port.
    """
    # Defensive fix: Avoid 2-second IPv6 DNS stall on 'localhost' for urllib
    probe = cdp_url.replace("localhost", "127.0.0.1").rstrip("/") + "/json/version"
    loop  = asyncio.get_event_loop()
    try:
        await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(probe, timeout=timeout),
            ),
            timeout=timeout + 0.5,
        )
        logger.debug("CDP probe OK — Chrome reachable at %s", probe)
        return True
    except Exception as exc:
        logger.debug("CDP probe failed (%s): %s", probe, exc)
        return False


# ── Cross-platform Chromium launch args ───────────────────────────────────────

def _chromium_args() -> list[str]:
    """
    Return platform-appropriate Chromium flags.
    --no-sandbox / --disable-dev-shm-usage are Linux-only; on Windows they
    can prevent the browser window from appearing.
    """
    args = ["--disable-blink-features=AutomationControlled"]
    if not IS_WINDOWS:
        args += [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ]
    return args


# ── Route handler ─────────────────────────────────────────────────────────────

async def _block_heavy_resources(route: Route) -> None:
    """Named handler — avoids async lambda closure surprises."""
    if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
        await route.abort()
    else:
        await route.continue_()


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

    Startup decision tree
    ─────────────────────
    CDP_URL set?
      ├─ YES → probe /json/version (HTTP, <5 ms)
      │          ├─ reachable  → Mode A (CDP connect)
      │          │               └─ still fails? → Mode B
      │          └─ unreachable → Mode B (no wait)
      └─ NO  → Mode B directly
    """

    def __init__(
        self,
        session_file: str = "./session.json",
        headless: bool = True,
        slow_mo: int = 0,
        response_timeout: int = 120,
        cdp_url: str = "",
    ):
        self.session_file     = Path(session_file)
        self.headless         = headless
        self.slow_mo          = slow_mo
        self.response_timeout = response_timeout
        self.cdp_url          = cdp_url

        self._playwright: Playwright | None  = None
        self._browser: Browser | None        = None
        self._context: BrowserContext | None = None
        self._page: Page | None              = None
        self._lock = asyncio.Lock()
        self._mode = "pending"

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._playwright = await async_playwright().start()

        if self.cdp_url:
            if await _cdp_is_reachable(self.cdp_url):
                try:
                    await self._start_cdp()
                    self._mode = "A-CDP"
                    logger.info("Browser ready — mode A (CDP at %s)", self.cdp_url)
                    return
                except Exception as exc:
                    logger.warning(
                        "Mode A: Chrome reachable but connection failed (%s) "
                        "— falling back to Mode B",
                        exc,
                    )
                    await self._cleanup_browser()
            else:
                logger.info(
                    "Mode A: Chrome not reachable at %s — skipping straight to Mode B",
                    self.cdp_url,
                )

        self._mode = "B-Fallback"
        await self._start_fallback()
        logger.info(
            "Browser ready — mode B (Chromium, headless=%s, platform=%s)",
            self.headless,
            platform.system(),
        )

    # ── Shared cleanup ─────────────────────────────────────────────────────────

    async def _cleanup_browser(self) -> None:
        """Close context + browser without touching _playwright."""
        for obj, name in [(self._context, "context"), (self._browser, "browser")]:
            if obj is not None:
                try:
                    await obj.close()
                except Exception as exc:
                    logger.debug("cleanup %s: %s", name, exc)
        self._context = None
        self._browser = None
        self._page    = None

    # ── Mode A — CDP ───────────────────────────────────────────────────────────

    async def _start_cdp(self) -> None:
        logger.info("MODE A — connecting via CDP at %s", self.cdp_url)
        self._browser = await self._playwright.chromium.connect_over_cdp(self.cdp_url)

        contexts = self._browser.contexts
        if contexts:
            self._context = contexts[0]
            logger.info("Reusing existing browser context")
        else:
            self._context = await self._browser.new_context()
            logger.warning("No existing context — created fresh one; login may be required")

        pages      = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()

        if "chatgpt.com" not in self._page.url:
            await self._page.goto(CHATGPT_URL, wait_until="domcontentloaded")
            try:
                await self._page.wait_for_load_state("networkidle", timeout=60_000)
            except PlaywrightTimeout:
                logger.warning("CDP networkidle timed out — continuing anyway")

        if not await self._is_logged_in():
            raise RuntimeError(
                "CDP-connected Chrome is NOT logged in to ChatGPT.\n"
                "Open that Chrome window, navigate to chatgpt.com, log in manually, "
                "then restart this server."
            )

        logger.info("CDP connection confirmed — ChatGPT session active")

    # ── Mode B — Fallback ──────────────────────────────────────────────────────

    async def _start_fallback(self) -> None:
        logger.info(
            "MODE B — launching Chromium (headless=%s, platform=%s)",
            self.headless,
            platform.system(),
        )

        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo,
            args=_chromium_args(),
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
            logger.info("Restoring session from %s", self.session_file)
            context_kwargs["storage_state"] = str(self.session_file)
        else:
            logger.info("No session.json found — proceeding without stored cookies")

        self._context = await self._browser.new_context(**context_kwargs)
        await self._context.route("**/*", _block_heavy_resources)

        self._page = await self._context.new_page()
        await self._page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        await self._page.goto(CHATGPT_URL, wait_until="domcontentloaded")
        try:
            await self._page.wait_for_load_state("networkidle", timeout=60_000)
        except PlaywrightTimeout:
            logger.warning("Fallback networkidle timed out — continuing anyway")

        if not await self._is_logged_in():
            screenshot = "./session-required.png"
            await self._page.screenshot(path=screenshot, full_page=True)
            raise RuntimeError(
                "ChatGPT is not authenticated in fallback mode.\n"
                "Options:\n"
                "  1. Set CDP_URL in .env and log in to ChatGPT in that Chrome window (Mode A).\n"
                "  2. Place a valid session.json next to this project (Mode B with cookies).\n"
                f"Screenshot saved → {screenshot}"
            )

        logger.info("Fallback mode — ChatGPT session verified")

    # ── Teardown ───────────────────────────────────────────────────────────────

    async def stop(self) -> None:
        try:
            await self._cleanup_browser()
        finally:
            if self._playwright:
                await self._playwright.stop()
            logger.info("Browser closed cleanly (mode %s)", self._mode)

    # ── Session check ──────────────────────────────────────────────────────────

    async def _is_logged_in(self) -> bool:
        try:
            await self._page.wait_for_selector(
                SEL_CHAT_INPUT, state="visible", timeout=6_000
            )
            return True
        except PlaywrightTimeout:
            return False

    # ── Browser health & recovery ────────────────────────────────────────────

    async def _is_browser_alive(self) -> bool:
        """Return False if page/context/browser has been closed or crashed."""
        try:
            if self._page is None or self._page.is_closed():
                return False
            await self._page.evaluate("() => true")
            return True
        except Exception:
            return False

    async def _recover(self) -> None:
        """Full teardown + restart when the browser is dead."""
        logger.warning("Browser/page is dead — recovering (was mode %s)", self._mode)
        await self.stop()
        await self.start()
        logger.info("Recovery complete (mode=%s)", self._mode)

    # ── Prompt & streaming ─────────────────────────────────────────────────────

    async def ask_stream(self, prompt: str, new_chat: bool = False) -> AsyncGenerator[str, None]:
        async with self._lock:
            if not await self._is_browser_alive():
                await self._recover()
            try:
                async for chunk in self._do_ask_stream(prompt, new_chat):
                    yield chunk
            except Exception as exc:
                err = str(exc).lower()
                if "has been closed" in err or "target closed" in err:
                    logger.warning("Browser died mid-stream — recovering and retrying")
                    await self._recover()
                    async for chunk in self._do_ask_stream(prompt, new_chat):
                        yield chunk
                else:
                    raise

    async def _do_ask_stream(self, prompt: str, new_chat: bool = False) -> AsyncGenerator[str, None]:
        page = self._page

        if new_chat or "chatgpt.com" not in page.url.lower():
            await page.goto(CHATGPT_NEW, wait_until="domcontentloaded")
            await page.wait_for_selector(SEL_CHAT_INPUT, state="visible", timeout=30_000)
            try:
                await page.wait_for_load_state("networkidle", timeout=30_000)
            except PlaywrightTimeout:
                logger.debug("networkidle timed out on prompt page — continuing")
        else:
            # Ensure chat input is visible even if we didn't explicitly navigate
            await page.wait_for_selector(SEL_CHAT_INPUT, state="visible", timeout=10_000)

        prior_count = await page.locator(SEL_RESPONSE_BLOCK).count()

        chat_input = page.locator(SEL_CHAT_INPUT)
        await safe_fill(chat_input, prompt)

        send_btn = page.locator(SEL_SEND_BUTTON)
        try:
            await safe_click(send_btn, timeout=5_000)
        except Exception:
            logger.debug("Send button not clickable — using Enter key")
            await chat_input.press("Enter")

        logger.info("Prompt submitted (%d chars)", len(prompt))

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
            screenshot = "./stream-timeout.png"
            await page.screenshot(path=screenshot, full_page=True)
            yield f"\n\n[Error: Playwright timed out — screenshot saved to {screenshot}]"
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

    async def screenshot(self, path: str = "./chatgpt-debug.png") -> str:
        await self._page.screenshot(path=path, full_page=True)
        logger.info("Screenshot saved at: %s", path)
        return path

    async def invalidate_session(self) -> None:
        """Delete persisted session.json (Mode B only)."""
        if self.session_file.exists():
            self.session_file.unlink()
            logger.info("session.json cleared")