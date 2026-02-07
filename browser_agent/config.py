from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import re

from dotenv import load_dotenv

DEFAULT_OPENAI_MODEL = "gpt-5-mini"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_PERMISSIONS = ["notifications", "clipboardReadWrite"]
DEFAULT_BROWSER_MODE = "auto"
VALID_BROWSER_MODES = {"auto", "own", "fresh", "managed"}
DEFAULT_INCLUDE_ATTRIBUTES = [
    "id",
    "name",
    "role",
    "type",
    "value",
    "placeholder",
    "aria-label",
    "data-testid",
    "href",
    "title",
    "alt",
]

_INLINE_COMMENT_RE = re.compile(r"\s+#.*$")


def _clean_env(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    cleaned = _INLINE_COMMENT_RE.sub("", value).strip()
    return cleaned or None


def _env_str(name: str, default: str | None = None) -> str | None:
    value = _clean_env(os.getenv(name))
    if value is None:
        return default
    return value


def _env_bool(name: str, default: bool) -> bool:
    value = _env_str(name)
    if value is None:
        return default
    normalized = value.lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Environment variable {name} must be a boolean value.")


def _env_int(name: str, default: int) -> int:
    value = _env_str(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(
            f"Environment variable {name} must be an integer, got {value!r}."
        ) from exc


def _env_float(name: str, default: float) -> float:
    value = _env_str(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(
            f"Environment variable {name} must be a float, got {value!r}."
        ) from exc


def _env_optional_float(name: str) -> float | None:
    value = _env_str(name)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(
            f"Environment variable {name} must be a float, got {value!r}."
        ) from exc


def _env_list(name: str, default: list[str]) -> list[str]:
    value = _env_str(name)
    if value is None:
        return default.copy()
    items = []
    for raw in re.split(r"[;,]", value):
        token = raw.strip()
        if token:
            items.append(token)
    return items or default.copy()


def normalize_api_key_aliases() -> None:
    openai_alias = _clean_env(os.getenv("OPENAI_KEY"))
    gemini_alias = _clean_env(os.getenv("GEMINI_API_KEY"))
    if openai_alias and not _clean_env(os.getenv("OPENAI_API_KEY")):
        os.environ["OPENAI_API_KEY"] = openai_alias
    if gemini_alias and not _clean_env(os.getenv("GOOGLE_API_KEY")):
        os.environ["GOOGLE_API_KEY"] = gemini_alias


@dataclass(slots=True)
class AppConfig:
    provider: str = "auto"
    model: str | None = None
    openai_model: str = DEFAULT_OPENAI_MODEL
    gemini_model: str = DEFAULT_GEMINI_MODEL
    openai_reasoning_effort: str = "low"
    temperature: float | None = None

    task_file: Path = Path("prompt.txt")
    task_override: str | None = None

    log_file: Path = Path("logs/browser_agent.log")
    log_level: str = "INFO"

    connect_existing_cdp: bool = True
    cdp_url: str | None = None
    cdp_port: int = 9222

    browser_mode: str = DEFAULT_BROWSER_MODE
    chrome_executable_path: str | None = None
    fresh_chrome_user_data_dir: Path = Path(".browser-agent/chrome-fresh-profile")
    fresh_chrome_start_timeout: float = 45.0
    profile_directory: str = "Default"
    browser_channel: str | None = None
    enable_default_extensions: bool = False

    headless: bool = False
    keep_alive: bool = False
    allowed_domains: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=lambda: DEFAULT_PERMISSIONS.copy())

    min_page_load_wait: float = 0.25
    network_idle_wait: float = 1.0
    wait_between_actions: float = 0.15
    highlight_elements: bool = False

    use_thinking: bool = True
    use_vision: bool = True
    flash_mode: bool = True
    max_steps: int = 60
    max_actions_per_step: int = 6
    llm_timeout: int = 90
    step_timeout: int = 120

    include_attributes: list[str] = field(
        default_factory=lambda: DEFAULT_INCLUDE_ATTRIBUTES.copy()
    )
    log_step_details: bool = True
    log_dom_tag_summary: bool = False

    @property
    def openai_api_key(self) -> str | None:
        return _clean_env(os.getenv("OPENAI_API_KEY"))

    @property
    def google_api_key(self) -> str | None:
        return _clean_env(os.getenv("GOOGLE_API_KEY"))

    def resolved_provider(self) -> str:
        provider = self.provider.strip().lower()
        if provider in {"gemini", "google"}:
            return "gemini"
        if provider == "openai":
            return "openai"
        if provider != "auto":
            raise ValueError(
                f"Unsupported provider {self.provider!r}. Use auto, openai, or gemini."
            )
        if self.google_api_key and not self.openai_api_key:
            return "gemini"
        return "openai"

    def resolved_model(self, provider: str | None = None) -> str:
        current_provider = provider or self.resolved_provider()
        if self.model:
            return self.model
        if current_provider == "gemini":
            return self.gemini_model
        return self.openai_model

    def task_text(self) -> str:
        if self.task_override:
            task = self.task_override.strip()
            if task:
                return task
        task_path = self.task_file
        if not task_path.exists():
            raise FileNotFoundError(
                f"Task file not found: {task_path}. Create it or pass --task."
            )
        text = task_path.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError(f"Task file is empty: {task_path}")
        return text

    def validate(self) -> None:
        browser_mode = self.browser_mode.strip().lower()
        if browser_mode not in VALID_BROWSER_MODES:
            valid = ", ".join(sorted(VALID_BROWSER_MODES))
            raise ValueError(
                f"BROWSER_MODE must be one of: {valid}. Got {self.browser_mode!r}."
            )
        self.browser_mode = browser_mode

        provider = self.resolved_provider()
        if provider == "openai" and not self.openai_api_key:
            raise ValueError(
                "OpenAI provider selected but OPENAI_API_KEY is not set."
            )
        if provider == "gemini" and not self.google_api_key:
            raise ValueError(
                "Gemini provider selected but GOOGLE_API_KEY is not set."
            )
        if self.max_steps <= 0:
            raise ValueError("MAX_STEPS must be greater than 0.")
        if self.max_actions_per_step <= 0:
            raise ValueError("MAX_ACTIONS_PER_STEP must be greater than 0.")
        if self.llm_timeout <= 0:
            raise ValueError("LLM_TIMEOUT must be greater than 0.")
        if self.step_timeout <= 0:
            raise ValueError("STEP_TIMEOUT must be greater than 0.")
        if self.cdp_port <= 0:
            raise ValueError("CDP_PORT must be greater than 0.")
        if self.fresh_chrome_start_timeout <= 0:
            raise ValueError("FRESH_CHROME_START_TIMEOUT must be greater than 0.")

    @classmethod
    def from_env(cls) -> "AppConfig":
        load_dotenv(override=False)
        normalize_api_key_aliases()

        provider = (_env_str("PROVIDER", "auto") or "auto").lower()
        model = _env_str("MODEL")
        openai_model = _env_str("OPENAI_MODEL", DEFAULT_OPENAI_MODEL) or DEFAULT_OPENAI_MODEL
        gemini_model = _env_str("GEMINI_MODEL", DEFAULT_GEMINI_MODEL) or DEFAULT_GEMINI_MODEL

        task_file = Path(_env_str("PROMPT_FILE", "prompt.txt") or "prompt.txt")
        log_file = Path(_env_str("LOG_FILE", "logs/browser_agent.log") or "logs/browser_agent.log")

        config = cls(
            provider=provider,
            model=model,
            openai_model=openai_model,
            gemini_model=gemini_model,
            openai_reasoning_effort=(
                _env_str("OPENAI_REASONING_EFFORT", "low") or "low"
            ).lower(),
            temperature=_env_optional_float("TEMPERATURE"),
            task_file=task_file,
            log_file=log_file,
            log_level=(_env_str("LOG_LEVEL", "INFO") or "INFO").upper(),
            connect_existing_cdp=_env_bool("CONNECT_EXISTING_CDP", True),
            cdp_url=_env_str("CDP_URL"),
            cdp_port=_env_int("CDP_PORT", 9222),
            browser_mode=_env_str("BROWSER_MODE", DEFAULT_BROWSER_MODE) or DEFAULT_BROWSER_MODE,
            chrome_executable_path=_env_str("CHROME_EXECUTABLE_PATH"),
            fresh_chrome_user_data_dir=Path(
                _env_str("FRESH_CHROME_USER_DATA_DIR", ".browser-agent/chrome-fresh-profile")
                or ".browser-agent/chrome-fresh-profile"
            ),
            fresh_chrome_start_timeout=_env_float("FRESH_CHROME_START_TIMEOUT", 45.0),
            profile_directory=_env_str("PROFILE_DIRECTORY", "Default") or "Default",
            browser_channel=_env_str("BROWSER_CHANNEL"),
            enable_default_extensions=_env_bool("ENABLE_DEFAULT_EXTENSIONS", False),
            headless=_env_bool("HEADLESS", False),
            keep_alive=_env_bool("KEEP_ALIVE", False),
            allowed_domains=_env_list("ALLOWED_DOMAINS", []),
            permissions=_env_list("BROWSER_PERMISSIONS", DEFAULT_PERMISSIONS),
            min_page_load_wait=_env_float("MIN_PAGE_LOAD_WAIT", 0.25),
            network_idle_wait=_env_float("NETWORK_IDLE_WAIT", 1.0),
            wait_between_actions=_env_float("WAIT_BETWEEN_ACTIONS", 0.15),
            highlight_elements=_env_bool("HIGHLIGHT_ELEMENTS", False),
            use_thinking=_env_bool("USE_THINKING", True),
            use_vision=_env_bool("USE_VISION", True),
            flash_mode=_env_bool("FLASH_MODE", True),
            max_steps=_env_int("MAX_STEPS", 60),
            max_actions_per_step=_env_int("MAX_ACTIONS_PER_STEP", 6),
            llm_timeout=_env_int("LLM_TIMEOUT", 90),
            step_timeout=_env_int("STEP_TIMEOUT", 120),
            include_attributes=_env_list(
                "INCLUDE_ATTRIBUTES",
                DEFAULT_INCLUDE_ATTRIBUTES,
            ),
            log_step_details=_env_bool("LOG_STEP_DETAILS", True),
            log_dom_tag_summary=_env_bool("LOG_DOM_TAG_SUMMARY", False),
        )
        config.validate()
        return config
