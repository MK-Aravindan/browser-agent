import asyncio
import json
import os
import platform
import subprocess
import sys
import time
import types
from datetime import date, datetime
from urllib.request import urlopen

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from browser_use import Agent, Browser
from browser_use.llm import ChatGoogle, ChatOpenAI

DEFAULT_OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
ALLOWED_DOMAINS = [] # e.g. ["wikipedia.org", "news.ycombinator.com"] or [] for unrestricted


def make_logger(path: str):
    # Creates a simple file+console logger and returns an object with a .log(msg) function.
    abspath = os.path.abspath(path)
    try:
        parent = os.path.dirname(abspath)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
        if not os.path.exists(abspath):
            with open(abspath, "w", encoding="utf-8") as f:
                f.write("# Browser-Use Run Log\n\n")
    except Exception:
        abspath = None

    def log(msg: str):
        # Appends a timestamped line to the log file and prints to stdout.
        nonlocal abspath
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"- {ts} — {msg}\n"
        print(msg, flush=True)
        if not abspath:
            return
        try:
            with open(abspath, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            abspath = None

    return types.SimpleNamespace(log=log)


def default_log_path() -> str:
    # Returns the default log file path inside a 'logs' directory.
    today = date.today().isoformat()
    log_dir = "logs"
    return os.getenv("LOG_FILE", os.path.join(log_dir, f"browser_use_{today}.md"))


LOGGER = make_logger(default_log_path())


def build_task():
    # Reads the task string from prompt.txt in the script directory.
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        prompt_path = os.path.join(script_dir, "prompt.txt")
        with open(prompt_path, "r", encoding="utf-8") as f:
            task = f.read().strip()
        if not task:
            LOGGER.log("Error: prompt.txt is empty. Please provide a task.")
            sys.exit(1)
        LOGGER.log(f"Task from prompt.txt: {task}")
        return task
    except FileNotFoundError:
        LOGGER.log("Error: 'prompt.txt' not found in the script directory.")
        LOGGER.log("Please create it and write your desired task inside.")
        sys.exit(1)
    except Exception as e:
        LOGGER.log(f"An error occurred while reading prompt.txt: {e}")
        sys.exit(1)


def cdp_alive(url: str) -> bool:
    # Checks whether a Chrome DevTools Protocol endpoint is reachable.
    try:
        with urlopen(f"{url}/json/version", timeout=0.8) as r:
            data = json.loads(r.read().decode("utf-8"))
            return bool(data.get("Browser"))
    except Exception:
        return False


def read_devtools_active_port(user_data_dir: str):
    # Reads the DevToolsActivePort file to get the current CDP port.
    if not user_data_dir:
        return None
    path = os.path.join(user_data_dir, "DevToolsActivePort")
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                first = f.readline().strip()
                return int(first) if first.isdigit() else None
    except Exception:
        pass
    return None


def detect_cdp_port():
    # Detects an active CDP port via env, running processes, default profiles, or a port scan.
    p = os.getenv("CDP_PORT")
    if p:
        try:
            if cdp_alive(f"http://localhost:{int(p)}"):
                LOGGER.log(f"Detected CDP on port {p} from CDP_PORT env.")
                return int(p)
        except Exception:
            pass
    try:
        import psutil

        for proc in psutil.process_iter(attrs=["name", "cmdline"]):
            name = (proc.info.get("name") or "").lower()
            if not any(x in name for x in ["chrome", "chromium"]):
                continue
            cmd = proc.info.get("cmdline") or []
            for tok in cmd:
                if tok.startswith("--remote-debugging-port="):
                    try:
                        port = int(tok.split("=", 1)[1])
                        if port and cdp_alive(f"http://localhost:{port}"):
                            LOGGER.log(f"Detected CDP on running Chrome (port {port}).")
                            return port
                    except Exception:
                        pass
            udd = None
            for i, tok in enumerate(cmd):
                if tok.startswith("--user-data-dir="):
                    udd = tok.split("=", 1)[1]
                elif tok == "--user-data-dir" and i + 1 < len(cmd):
                    udd = cmd[i + 1]
            if udd:
                port = read_devtools_active_port(udd)
                if port and cdp_alive(f"http://localhost:{port}"):
                    LOGGER.log(f"Detected CDP via DevToolsActivePort (port {port}).")
                    return port
    except Exception:
        pass
    system = platform.system().lower()
    candidates = []
    if system == "windows":
        candidates = [os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")]
    elif system == "darwin":
        candidates = [os.path.expanduser("~/Library/Application Support/Google/Chrome")]
    else:
        candidates = [
            os.path.expanduser("~/.config/google-chrome"),
            os.path.expanduser("~/.config/chromium"),
        ]
    for udd in candidates:
        port = read_devtools_active_port(udd)
        if port and cdp_alive(f"http://localhost:{port}"):
            LOGGER.log(f"Detected CDP via default profile (port {port}).")
            return port
    for port in list(range(9222, 9231)) + list(range(9000, 9011)):
        if cdp_alive(f"http://localhost:{port}"):
            LOGGER.log(f"Detected CDP by scanning (port {port}).")
            return port
    return None


def strip_cmd_to_exe(cmd: str) -> str:
    # Extracts the executable path from a Windows registry command string.
    import shlex as _sh

    try:
        return _sh.split(cmd, posix=False)[0]
    except Exception:
        if cmd.startswith('"'):
            return cmd.split('"')[1]
        return cmd.split(" ")[0]


def find_chrome_path():
    # Attempts to find a Chrome/Chromium executable path on the current OS.
    system = platform.system().lower()
    if system == "windows":
        try:
            import winreg

            reg_paths = [
                (
                    winreg.HKEY_CURRENT_USER,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
                ),
                (
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
                ),
                (
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
                ),
                (
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Clients\StartMenuInternet\Google Chrome\shell\open\command",
                ),
                (
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\WOW6432Node\Clients\StartMenuInternet\Google Chrome\shell\open\command",
                ),
            ]
            candidates = []
            for hive, path in reg_paths:
                try:
                    with winreg.OpenKey(hive, path) as k:
                        val, _ = winreg.QueryValueEx(k, None)
                        exe = strip_cmd_to_exe(val)
                        if exe and os.path.exists(exe):
                            candidates.append(exe)
                except OSError:
                    pass
            for exe in dict.fromkeys(candidates):
                return exe
        except Exception:
            pass
        for p in [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]:
            if os.path.exists(p):
                return p
        return None
    elif system == "darwin":
        for p in [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/usr/local/Caskroom/google-chrome/latest/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]:
            if os.path.exists(p):
                return p
        return None
    else:
        from shutil import which

        for name in [
            "google-chrome",
            "google-chrome-stable",
            "chromium-browser",
            "chromium",
        ]:
            exe = which(name)
            if exe:
                return exe
        return None


def profile_dir_for_cdp():
    # Returns the profile directory to use for a CDP-enabled Chrome instance.
    system = platform.system().lower()
    if system == "windows":
        base = os.path.expandvars(r"%LOCALAPPDATA%")
        return os.path.join(base, "ChromeCDP")
    return os.path.join(os.path.expanduser("~"), ".chrome-cdp")


def ensure_dir(p):
    # Ensures a directory exists.
    os.makedirs(p, exist_ok=True)


def launch_chrome_with_cdp(port: int) -> bool:
    # Launches a separate Chrome instance with remote debugging on the given port.
    exe = find_chrome_path()
    if not exe:
        LOGGER.log(
            "Could not locate chrome executable. Make sure Chrome is installed and on PATH."
        )
        return False
    udd = profile_dir_for_cdp()
    ensure_dir(udd)
    args = [
        exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={udd}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-first-run-ui",
    ]
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        url = f"http://localhost:{port}"
        for _ in range(40):
            if cdp_alive(url):
                LOGGER.log(
                    f"Launched Chrome for CDP on port {port} (profile: {udd})."
                )
                return True
            time.sleep(0.2)
    except Exception as e:
        LOGGER.log(f"Failed to launch Chrome with CDP: {e}")
    return False


def normalize_api_keys():
    # Normalizes environment variable aliases for OpenAI and Gemini API keys.
    try:
        if os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
            os.environ["GOOGLE_API_KEY"] = os.getenv("GEMINI_API_KEY")
        if os.getenv("OPENAI_KEY") and not os.getenv("OPENAI_API_KEY"):
            os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_KEY")
    except Exception:
        pass


def resolve_provider_and_model():
    # Resolves which LLM provider and model to use based on env vars and defaults.
    requested_provider = os.getenv("PROVIDER", "").strip().lower()
    model_env = os.getenv("MODEL", "").strip()
    openai_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY")
    gemini_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    provider = requested_provider
    if not provider:
        if gemini_key and not openai_key:
            provider = "gemini"
        elif openai_key and not gemini_key:
            provider = "openai"
        elif gemini_key and openai_key:
            provider = "openai"
        else:
            provider = "openai"
    model = DEFAULT_GEMINI_MODEL if not model_env and provider in ("google", "gemini") else (model_env or DEFAULT_OPENAI_MODEL)
    return provider, model


def build_llm(provider: str, model: str):
    # Builds and returns an LLM client instance for the chosen provider and model.
    p = (provider or "openai").lower().strip()
    if p in ("google", "gemini"):
        return ChatGoogle(model or DEFAULT_GEMINI_MODEL)
    return ChatOpenAI(model or DEFAULT_OPENAI_MODEL)


async def run_agent():
    # Configures the environment, connects to Chrome CDP, and runs the browser agent.
    normalize_api_keys()
    provider, model = resolve_provider_and_model()
    LOGGER.log(f"LLM provider: {provider}")
    LOGGER.log(f"LLM model: {model}")
    LOGGER.log(f"Allowed domains: {ALLOWED_DOMAINS}")
    port = detect_cdp_port()
    if not port:
        port = int(os.getenv("CDP_PORT", "9222"))
        ok = launch_chrome_with_cdp(port)
        if not ok:
            LOGGER.log("[CDP not detected and auto-launch failed]")
            LOGGER.log("Try starting Chrome manually with a non-default profile, e.g.:")
            if platform.system().lower() == "windows":
                LOGGER.log(
                    f'  start chrome --remote-debugging-port={port} --user-data-dir="%LOCALAPPDATA%\\ChromeCDP"'
                )
            elif platform.system().lower() == "darwin":
                LOGGER.log(
                    f'  open -a "Google Chrome" --args --remote-debugging-port={port} --user-data-dir="$HOME/.chrome-cdp"'
                )
            else:
                LOGGER.log(
                    f'  google-chrome --remote-debugging-port={port} --user-data-dir="$HOME/.chrome-cdp"'
                )
            sys.exit(2)
    else:
        LOGGER.log(f"Using existing CDP on port {port}.")
    url = f"http://localhost:{port}"
    browser = Browser(
        cdp_url=url,
        headless=False,
        allowed_domains=ALLOWED_DOMAINS,
        permissions=["notifications", "clipboardReadWrite"],
        keep_alive=True,
    )
    agent = Agent(
        task=build_task(),
        llm=build_llm(provider, model),
        browser=browser,
    )
    LOGGER.log("Starting agent.run() …")
    await agent.run()
    LOGGER.log("Agent finished.")


if __name__ == "__main__":
    try:
        asyncio.run(run_agent())
    except SystemExit:
        raise
    except Exception as e:
        LOGGER.log(f"Fatal error: {e}")
        raise
