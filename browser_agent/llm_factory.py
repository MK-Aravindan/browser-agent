from __future__ import annotations

from browser_use import ChatGoogle, ChatOpenAI

from .config import AppConfig


def build_llm(config: AppConfig):
    provider = config.resolved_provider()
    model = config.resolved_model(provider)

    if provider == "gemini":
        kwargs = {
            "model": model,
            "api_key": config.google_api_key,
        }
        if config.temperature is not None:
            kwargs["temperature"] = config.temperature
        return ChatGoogle(**kwargs)

    kwargs = {
        "model": model,
        "api_key": config.openai_api_key,
        "reasoning_effort": config.openai_reasoning_effort,
    }
    if config.temperature is not None:
        kwargs["temperature"] = config.temperature
    return ChatOpenAI(**kwargs)
