from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import time
from urllib.request import urlopen

from browser_use import Browser, BrowserProfile

from .config import AppConfig


def _cdp_alive(base_url: str) -> bool:
    try:
        endpoint = f"{base_url.rstrip('/')}/json/version"
        with urlopen(endpoint, timeout=0.8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return bool(payload.get("Browser"))
    except Exception:
        return False


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _find_free_port(start: int, stop: int = 9400) -> int:
    for port in range(start, stop + 1):
        if not _port_open(port):
            return port
    raise RuntimeError(f"No free local port found in range {start}-{stop}.")


def _find_chrome_executable(config: AppConfig) -> str:
    if config.chrome_executable_path:
        p = Path(config.chrome_executable_path).expanduser().resolve()
        if p.exists():
            return str(p)
        raise FileNotFoundError(
            f"Configured CHROME_EXECUTABLE_PATH does not exist: {p}"
        )

    system = platform.system().lower()
    candidates: list[str] = []

    if system == "windows":
        candidates.extend(
            [
                os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(
                    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
                ),
                os.path.expandvars(
                    r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
                ),
                os.path.expandvars(r"%ProgramFiles%\Chromium\Application\chrome.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Chromium\Application\chrome.exe"),
            ]
        )
    elif system == "darwin":
        candidates.extend(
            [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
            ]
        )
    else:
        for name in (
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
        ):
            path = shutil.which(name)
            if path:
                return path

    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate

    raise FileNotFoundError(
        "Chrome/Chromium executable not found. Set CHROME_EXECUTABLE_PATH in .env."
    )


def _resolve_existing_cdp_url(config: AppConfig) -> str | None:
    candidates: list[str] = []
    if config.cdp_url:
        candidates.append(config.cdp_url.rstrip("/"))
    if config.cdp_port:
        candidates.extend(
            [
                f"http://127.0.0.1:{config.cdp_port}",
                f"http://localhost:{config.cdp_port}",
            ]
        )

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if _cdp_alive(candidate):
            return candidate
    return None


def _launch_fresh_chrome_for_cdp(
    config: AppConfig,
    logger: logging.Logger,
) -> tuple[subprocess.Popen[bytes], str]:
    executable = _find_chrome_executable(config)
    base_user_data_dir = config.fresh_chrome_user_data_dir.expanduser().resolve()

    def _launch_with_profile_dir(user_data_dir: Path) -> tuple[subprocess.Popen[bytes], str]:
        user_data_dir.mkdir(parents=True, exist_ok=True)

        desired_port = int(config.cdp_port)
        if _port_open(desired_port):
            port = _find_free_port(desired_port + 1)
            logger.info(
                "CDP port %s is busy; using free port %s for fresh Chrome.",
                desired_port,
                port,
            )
        else:
            port = desired_port

        args = [
            executable,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data_dir}",
            f"--profile-directory={config.profile_directory}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if config.headless:
            args.append("--headless=new")

        process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        cdp_url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + config.fresh_chrome_start_timeout
        while time.monotonic() < deadline:
            if _cdp_alive(cdp_url):
                logger.info(
                    "Started fresh Chrome on %s (profile: %s)",
                    cdp_url,
                    user_data_dir,
                )
                return process, cdp_url
            if process.poll() is not None:
                raise RuntimeError(
                    f"Chrome exited early with code {process.returncode} before CDP became available."
                )
            time.sleep(0.25)

        try:
            process.terminate()
        except Exception:
            pass
        raise RuntimeError(
            f"Fresh Chrome did not expose CDP within {config.fresh_chrome_start_timeout}s."
        )

    try:
        return _launch_with_profile_dir(base_user_data_dir)
    except Exception as first_error:
        retry_dir = base_user_data_dir.parent / f"{base_user_data_dir.name}-run-{int(time.time())}"
        logger.warning(
            "Fresh Chrome failed with profile %s (%s). Retrying with isolated profile %s.",
            base_user_data_dir,
            first_error,
            retry_dir,
        )
        return _launch_with_profile_dir(retry_dir)


def _manual_cdp_start_hint(port: int) -> str:
    system = platform.system().lower()
    if system == "windows":
        return (
            f'chrome --remote-debugging-port={port} '
            f'--user-data-dir="%LOCALAPPDATA%\\ChromeCDP"'
        )
    if system == "darwin":
        return (
            f'open -a "Google Chrome" --args --remote-debugging-port={port} '
            f'--user-data-dir="$HOME/.chrome-cdp"'
        )
    return (
        f'google-chrome --remote-debugging-port={port} '
        f'--user-data-dir="$HOME/.chrome-cdp"'
    )


@dataclass(slots=True)
class BrowserRuntime:
    browser: Browser
    mode: str
    cdp_url: str | None
    launched_process: subprocess.Popen[bytes] | None = None

    def cleanup(self, logger: logging.Logger, keep_alive: bool) -> None:
        if keep_alive or not self.launched_process:
            return
        process = self.launched_process
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=5)
            logger.info("Stopped fresh Chrome process.")
        except Exception:
            try:
                process.kill()
                logger.info("Killed fresh Chrome process.")
            except Exception:
                logger.exception("Failed to close fresh Chrome process cleanly.")


def _build_profile(
    config: AppConfig,
    *,
    cdp_url: str | None,
    managed_mode: bool,
) -> BrowserProfile:
    kwargs: dict[str, object] = {
        "cdp_url": cdp_url,
        "headless": config.headless,
        "keep_alive": config.keep_alive,
        "allowed_domains": config.allowed_domains or None,
        "permissions": config.permissions or None,
        "minimum_wait_page_load_time": config.min_page_load_wait,
        "wait_for_network_idle_page_load_time": config.network_idle_wait,
        "wait_between_actions": config.wait_between_actions,
        "highlight_elements": config.highlight_elements,
        "enable_default_extensions": config.enable_default_extensions,
        "profile_directory": config.profile_directory,
    }
    if managed_mode:
        if config.browser_channel:
            kwargs["channel"] = config.browser_channel
        if config.chrome_executable_path:
            kwargs["executable_path"] = config.chrome_executable_path
    return BrowserProfile(**kwargs)


def build_browser(config: AppConfig, logger: logging.Logger) -> BrowserRuntime:
    mode = config.browser_mode.lower()
    active_mode = mode
    cdp_url: str | None = None
    launched_process: subprocess.Popen[bytes] | None = None

    should_probe_existing = mode in {"auto", "own"} or config.connect_existing_cdp
    existing_cdp = _resolve_existing_cdp_url(config) if should_probe_existing else None

    if mode == "auto":
        if existing_cdp:
            active_mode = "own"
            cdp_url = existing_cdp
            logger.info("Browser mode auto -> own (existing CDP found).")
        else:
            active_mode = "fresh"
            logger.info("Browser mode auto -> fresh (no existing CDP).")

    if mode == "own":
        if not existing_cdp:
            port = config.cdp_port
            raise RuntimeError(
                "BROWSER_MODE=own requires a live Chrome CDP session.\n"
                f"Start Chrome with:\n"
                f"  {_manual_cdp_start_hint(port)}\n"
                "Or switch to BROWSER_MODE=fresh."
            )
        cdp_url = existing_cdp
        logger.info("Using your existing Chrome CDP endpoint: %s", cdp_url)

    if mode == "fresh" or active_mode == "fresh":
        launched_process, cdp_url = _launch_fresh_chrome_for_cdp(config, logger)

    managed_mode = (mode == "managed") or (active_mode == "managed")
    if managed_mode:
        logger.info("Using browser-use managed launch mode.")
        cdp_url = None

    profile = _build_profile(
        config,
        cdp_url=cdp_url,
        managed_mode=managed_mode,
    )
    browser = Browser(browser_profile=profile)
    return BrowserRuntime(
        browser=browser,
        mode=active_mode if mode == "auto" else mode,
        cdp_url=cdp_url,
        launched_process=launched_process,
    )
