from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import logging
from pathlib import Path
import sys
from typing import Any

from browser_use import Agent

from .browser_factory import BrowserRuntime, build_browser
from .config import AppConfig
from .llm_factory import build_llm
from .logging_utils import configure_logger

TAG_AWARE_SYSTEM_GUIDANCE = """
When interacting with the page, rely on HTML tag semantics and element attributes.
- Prefer controls whose tag type matches intent (button for clicks, input/textarea for typing, select for options).
- Verify critical attributes before action: id, name, role, type, aria-label, data-testid, href.
- If multiple similar elements exist, choose the most specific visible match and avoid ambiguous clicks.
- Re-check the page after each action and adjust using the latest DOM state.
""".strip()


def _ensure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _extract_action_names(model_output: Any) -> list[str]:
    names: list[str] = []
    for action in getattr(model_output, "action", []) or []:
        if hasattr(action, "model_dump"):
            payload = action.model_dump(exclude_none=True)
            names.extend(payload.keys())
    return names


def _dom_tag_summary(state: Any, limit: int = 6) -> str:
    selector_map = getattr(getattr(state, "dom_state", None), "selector_map", None) or {}
    if not selector_map:
        return "-"

    tag_counts: Counter[str] = Counter()
    for node in selector_map.values():
        tag = (getattr(node, "node_name", "") or "").lower()
        if tag and tag != "#text":
            tag_counts[tag] += 1

    if not tag_counts:
        return "-"
    return ", ".join(f"{name}:{count}" for name, count in tag_counts.most_common(limit))


def _build_step_callback(
    logger: logging.Logger,
    log_dom_tag_summary: bool,
):
    def _callback(state: Any, model_output: Any, step_number: int) -> None:
        action_names = _extract_action_names(model_output)
        next_goal = (getattr(model_output, "next_goal", "") or "").strip()
        message = (
            f"Step {step_number} | url={getattr(state, 'url', '-')}"
            f" | actions={','.join(action_names) if action_names else '-'}"
        )
        if next_goal:
            message += f" | next_goal={next_goal}"
        if log_dom_tag_summary:
            message += f" | tags={_dom_tag_summary(state)}"
        logger.info(message)

    return _callback


async def _run(config: AppConfig, logger: logging.Logger) -> None:
    task = config.task_text()
    provider = config.resolved_provider()
    model = config.resolved_model(provider)

    logger.info("Provider: %s", provider)
    logger.info("Model: %s", model)
    logger.info("Task source: %s", config.task_file if not config.task_override else "CLI")
    logger.info("Allowed domains: %s", config.allowed_domains or "unrestricted")

    llm = build_llm(config)
    browser_runtime: BrowserRuntime = build_browser(config, logger)
    browser = browser_runtime.browser
    logger.info("Browser mode: %s", browser_runtime.mode)
    if browser_runtime.cdp_url:
        logger.info("CDP endpoint: %s", browser_runtime.cdp_url)

    step_callback = (
        _build_step_callback(
            logger=logger,
            log_dom_tag_summary=config.log_dom_tag_summary,
        )
        if config.log_step_details
        else None
    )

    try:
        agent = Agent(
            task=task,
            llm=llm,
            browser=browser,
            include_attributes=config.include_attributes,
            extend_system_message=TAG_AWARE_SYSTEM_GUIDANCE,
            use_thinking=config.use_thinking,
            use_vision=config.use_vision,
            flash_mode=config.flash_mode,
            max_actions_per_step=config.max_actions_per_step,
            llm_timeout=config.llm_timeout,
            step_timeout=config.step_timeout,
            register_new_step_callback=step_callback,
        )
        history = await agent.run(max_steps=config.max_steps)
        if history.has_errors():
            errors = history.errors()
            logger.warning("Agent finished with %s error(s).", len(errors))
            for error in errors[-3:]:
                logger.warning("Error: %s", error)
        final_result = history.final_result()
        if final_result:
            logger.info("Final result:\n%s", final_result)
        else:
            logger.info("Final result is empty.")
    finally:
        try:
            await browser.stop()
        except Exception:
            logger.exception("Failed to stop browser session cleanly.")
        browser_runtime.cleanup(logger, keep_alive=config.keep_alive)


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a browser-use based autonomous browser agent."
    )
    parser.add_argument(
        "--task",
        help="Inline task text. If omitted, prompt.txt is used.",
    )
    parser.add_argument(
        "--prompt-file",
        help="Task file path. Overrides PROMPT_FILE env.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        help="Maximum agent steps for this run.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Force headless browser mode for this run.",
    )
    parser.add_argument(
        "--show-browser",
        action="store_true",
        help="Force headed browser mode for this run.",
    )
    parser.add_argument(
        "--no-cdp",
        action="store_true",
        help="Disable auto-attach to an existing CDP endpoint.",
    )
    parser.add_argument(
        "--browser-mode",
        choices=["auto", "own", "fresh", "managed"],
        help="Browser startup mode.",
    )
    parser.add_argument(
        "--chrome-path",
        help="Path to Chrome/Chromium executable (overrides CHROME_EXECUTABLE_PATH).",
    )
    parser.add_argument(
        "--cdp-port",
        type=int,
        help="CDP port to attach to or launch with.",
    )
    parser.add_argument(
        "--cdp-url",
        help="Full CDP base URL, e.g. http://127.0.0.1:9222",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_console()
    args = _build_cli_parser().parse_args(argv)

    try:
        config = AppConfig.from_env()
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if args.task:
        config.task_override = args.task
    if args.prompt_file:
        config.task_file = Path(args.prompt_file)
    if args.max_steps is not None:
        config.max_steps = args.max_steps
    if args.headless:
        config.headless = True
    if args.show_browser:
        config.headless = False
    if args.no_cdp:
        config.connect_existing_cdp = False
    if args.browser_mode:
        config.browser_mode = args.browser_mode
    if args.chrome_path:
        config.chrome_executable_path = args.chrome_path
    if args.cdp_port is not None:
        config.cdp_port = args.cdp_port
    if args.cdp_url:
        config.cdp_url = args.cdp_url

    try:
        config.validate()
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    logger = configure_logger(config.log_level, config.log_file)
    logger.info("Starting browser agent.")

    try:
        asyncio.run(_run(config, logger))
        logger.info("Run completed.")
        return 0
    except KeyboardInterrupt:
        logger.warning("Interrupted by user.")
        return 130
    except Exception:
        logger.exception("Fatal error while running agent.")
        return 1
