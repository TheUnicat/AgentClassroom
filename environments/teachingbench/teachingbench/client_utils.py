"""Provider-aware client config: dispatch to OpenAI vs Anthropic based on model name.

Usage:
    cfg = tutor_client_for("claude-haiku-4-5-20251001")
    # → ClientConfig with client_type="anthropic_messages"

    cfg = tutor_client_for("gpt-5.4-mini")
    # → ClientConfig with client_type="openai_chat_completions"

Caching note: verifiers' anthropic_messages client translates OpenAI-style
content blocks to Anthropic format, but **strips `cache_control` markers** in
the process. That means Anthropic prompt caching (5-min ephemeral cache, 10%
read cost) is not accessible without bypassing verifiers' translation layer.
OpenAI's automatic prompt caching still applies for OpenAI tutors.
"""

from __future__ import annotations

from typing import Literal

from verifiers.types import ClientConfig

# Default API base URLs per provider.
OPENAI_API_BASE = "https://api.openai.com/v1"
ANTHROPIC_API_BASE = "https://api.anthropic.com"


def detect_provider(model_name: str) -> Literal["openai", "anthropic"]:
    """Detect provider from a model name. claude-* → anthropic; else openai."""
    name = model_name.lower()
    if name.startswith("claude") or name.startswith("anthropic"):
        return "anthropic"
    return "openai"


def tutor_client_for(
    model_name: str,
    *,
    openai_api_key_var: str = "OPENAI_API_KEY",
    anthropic_api_key_var: str = "ANTHROPIC_API_KEY",
    openai_base_url: str = OPENAI_API_BASE,
    anthropic_base_url: str = ANTHROPIC_API_BASE,
) -> ClientConfig:
    """Build a verifiers ClientConfig appropriate for the given tutor model."""
    provider = detect_provider(model_name)
    if provider == "anthropic":
        return ClientConfig(
            client_type="anthropic_messages",
            api_key_var=anthropic_api_key_var,
            api_base_url=anthropic_base_url,
        )
    return ClientConfig(
        client_type="openai_chat_completions",
        api_key_var=openai_api_key_var,
        api_base_url=openai_base_url,
    )
