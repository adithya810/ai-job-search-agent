"""Playwright persistent browser session management and anti-bot detection.

Security & compliance notes:
- Credentials/passwords are NEVER stored or auto-submitted by this module.
- Interactive login opens a visible Chromium window backed by a local persistent
  profile directory so the user can sign in themselves (including 2FA/CAPTCHA)
  and reuse the session on subsequent runs.
- Anti-bot / CAPTCHA gates are detected and reported transparently; this module
  never attempts to bypass or solve them automatically.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import re
from typing import Any, Iterator

CHALLENGE_PATTERNS = (
    re.compile(r"verify you are human", re.IGNORECASE),
    re.compile(r"checking your browser", re.IGNORECASE),
    re.compile(r"cf-turnstile|challenges\.cloudflare\.com", re.IGNORECASE),
    re.compile(r"g-recaptcha|hcaptcha|captcha-delivery", re.IGNORECASE),
    re.compile(r"security verification|unusual traffic|automated access", re.IGNORECASE),
    re.compile(r"just a moment\.\.\.", re.IGNORECASE),
)


def detect_anti_bot_challenge(html_or_text: str, url: str = "") -> str | None:
    """Return a short reason string if the page appears to be a CAPTCHA or anti-bot gate."""
    lower_url = (url or "").lower()
    if any(token in lower_url for token in ("checkpoint/challenge", "/captcha", "cdn-cgi/challenge")):
        return "Redirected to verification/CAPTCHA challenge URL"
    sample = (html_or_text or "")[:30000]
    for pattern in CHALLENGE_PATTERNS:
        if pattern.search(sample):
            return f"Verification or anti-bot gate detected ({pattern.pattern})"
    return None


def playwright_available() -> tuple[bool, str]:
    """Check whether Playwright Python package is importable."""
    try:
        import playwright  # noqa: F401
        return True, "Playwright package is installed."
    except ImportError:
        return (
            False,
            "Playwright is not installed. Run `pip install playwright && python3 -m playwright install chromium`.",
        )


def has_saved_profile(profile_dir: Path) -> bool:
    """Return True if a persistent Chromium profile directory already exists with session files."""
    if not profile_dir.exists():
        return False
    return any(profile_dir.iterdir())


@contextmanager
def open_persistent_browser(
    profile_dir: Path,
    *,
    headless: bool = False,
    slow_mo_ms: int = 50,
) -> Iterator[Any]:
    """Open a Playwright Chromium persistent context for authenticated local browsing."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is required for browser mode. Install it with: "
            "`pip install playwright && python3 -m playwright install chromium`"
        ) from exc

    profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=headless,
                slow_mo=slow_mo_ms,
                viewport={"width": 1366, "height": 860},
            )
        except Exception as exc:
            raise RuntimeError(
                f"Could not launch Chromium persistent browser ({exc}). "
                "If Chromium is not installed yet, run: `python3 -m playwright install chromium`."
            ) from exc
        try:
            yield context
        finally:
            context.close()


def interactive_site_login(
    profile_dir: Path,
    *,
    site_name: str,
    login_url: str,
    email_hint: str = "",
    email_selectors: tuple[str, ...] = (),
) -> None:
    """Open a visible browser at `login_url`, optionally pre-fill email hint, and wait for manual sign-in."""
    print(f"\n[{site_name}] Opening visible Chromium window for manual sign-in...")
    print(f"[{site_name}] Persistent profile directory: {profile_dir}")
    print(f"[{site_name}] URL: {login_url}")

    with open_persistent_browser(profile_dir, headless=False) as context:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(login_url, wait_until="domcontentloaded", timeout=45000)

        if email_hint and email_selectors:
            for selector in email_selectors:
                try:
                    locator = page.locator(selector).first
                    if locator.is_visible(timeout=2500):
                        current = locator.input_value(timeout=1500)
                        if not current:
                            locator.fill(email_hint)
                            print(f"[{site_name}] Pre-filled email hint: {email_hint}")
                        break
                except Exception:
                    continue

        print(
            f"\n>>> Complete sign-in (and any 2FA / verification) for {site_name} in the browser window.\n"
            f">>> Your password is NOT read or stored by this script; only your local browser profile persists.\n"
            f">>> Press ENTER here once you are signed in to save the session and continue..."
        )
        input()
        print(f"[{site_name}] Session saved to {profile_dir}.")
