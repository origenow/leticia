"""Anthropic Claude wrapper for Letícia.

Uses prompt caching on the system prompt so we don't pay full tokens on every turn.
"""
from __future__ import annotations

import logging

from anthropic import Anthropic
from django.conf import settings

from .leticia_persona import SYSTEM_PROMPT, build_user_context

log = logging.getLogger(__name__)

_client: Anthropic | None = None


def get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def generate_reply(lead, history: list[dict], incoming_text: str) -> str:
    """history: list of {'role': 'user'|'assistant', 'content': str} oldest-first."""
    context_block = build_user_context(lead, history)

    messages = []
    for h in history[-12:]:
        messages.append({"role": h["role"], "content": h["content"]})

    user_turn = incoming_text
    if context_block and len(messages) == 0:
        user_turn = f"{context_block}\n\nMensagem do lead:\n{incoming_text}"
    messages.append({"role": "user", "content": user_turn})

    try:
        resp = get_client().messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=600,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=messages,
        )
    except Exception as e:
        log.exception("anthropic.generate_reply failed: %s", e)
        return ""

    parts = []
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts).strip()
