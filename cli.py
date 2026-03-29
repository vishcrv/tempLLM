#!/usr/bin/env python3
"""
ChatGPT CLI

First run:        opens a browser window → log in → session saved automatically
Every run after:  fully headless, prompt ↔ response right in the terminal

Usage:
  python cli.py              # start chatting
  python cli.py --setup      # force re-login (e.g. session expired)
  python cli.py --new-chat   # start a fresh conversation
"""

import asyncio
import sys
import os
from pathlib import Path

from browser import ChatGPTBrowser

SESSION_FILE     = Path(os.getenv("SESSION_FILE", "./session.json"))
RESPONSE_TIMEOUT = int(os.getenv("RESPONSE_TIMEOUT", "120"))
HEADLESS         = os.getenv("HEADLESS", "false").lower() == "true"  # false = more reliable

BANNER = """
  ██████╗██╗  ██╗ █████╗ ████████╗ ██████╗ ██████╗ ████████╗
 ██╔════╝██║  ██║██╔══██╗╚══██╔══╝██╔════╝ ██╔══██╗╚══██╔══╝
 ██║     ███████║███████║   ██║   ██║  ███╗██████╔╝   ██║
 ██║     ██╔══██║██╔══██║   ██║   ██║   ██║██╔═══╝    ██║
 ╚██████╗██║  ██║██║  ██║   ██║   ╚██████╔╝██║        ██║
  ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚═╝        ╚═╝
  CLI  ·  type your message  ·  'exit' to quit  ·  Ctrl+C to cancel
"""


# ── Setup flow ─────────────────────────────────────────────────────────────────

async def run_setup() -> None:
    """Open a headed browser, wait for the user to log in, save session."""
    browser = ChatGPTBrowser(
        session_file=str(SESSION_FILE),
        headless=False,
        response_timeout=RESPONSE_TIMEOUT,
    )

    print("\nOpening ChatGPT in your browser...")
    print("Log in with your account, then come back here.\n")
    print("Waiting for login ", end="", flush=True)

    dots = [0]
    def tick():
        dots[0] += 1
        if dots[0] % 3 == 0:
            print(".", end="", flush=True)

    try:
        await browser.setup_session(on_tick=tick)
    except TimeoutError:
        print("\n\n✗ Timed out waiting for login (5 min). Please try again.\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n✗ Setup failed: {e}\n")
        sys.exit(1)

    print("\n\n✓ Logged in — session saved.\n")


# ── Chat loop ──────────────────────────────────────────────────────────────────

async def run_chat(new_chat: bool = False) -> None:
    browser = ChatGPTBrowser(
        session_file=str(SESSION_FILE),
        headless=HEADLESS,
        response_timeout=RESPONSE_TIMEOUT,
    )

    try:
        await browser.start()
    except RuntimeError as e:
        err = str(e)
        if err == "no-session":
            print("No session found. Run: python cli.py --setup\n")
        elif err == "session-expired":
            print("Your session expired. Run: python cli.py --setup\n")
        else:
            print(f"Failed to start: {e}\n")
        sys.exit(1)

    if new_chat:
        # Navigate to a fresh conversation
        await browser._page.goto("https://chatgpt.com", wait_until="domcontentloaded")

    print(BANNER)

    try:
        while True:
            # get input on a thread so we don't block the event loop
            try:
                user_input = await asyncio.to_thread(input, "You: ")
            except (EOFError, KeyboardInterrupt):
                break

            user_input = user_input.strip()
            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit", "/exit", "/quit", "q"}:
                break

            print("ChatGPT: ", end="", flush=True)
            try:
                async for chunk in browser.ask_stream(user_input):
                    print(chunk, end="", flush=True)
            except KeyboardInterrupt:
                print("  [cancelled]")
            except Exception as e:
                print(f"\n✗ Error: {e}")
            print("\n")

    finally:
        print("Goodbye!")
        await browser.stop()


# ── Entry point ────────────────────────────────────────────────────────────────

async def main():
    args = sys.argv[1:]

    force_setup = "--setup" in args
    new_chat    = "--new-chat" in args

    # First run or forced re-login
    if force_setup or not SESSION_FILE.exists():
        if not force_setup:
            print("\nWelcome to ChatGPT CLI!")
            print("─" * 40)
            print("First-time setup: we need to log you in.\n")
        await run_setup()

    await run_chat(new_chat=new_chat)


if __name__ == "__main__":
    asyncio.run(main())
