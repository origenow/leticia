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


def generate_reply(
    lead,
    history: list[dict],
    incoming_text: str,
    image_b64: str | None = None,
    image_mime: str | None = None,
) -> str:
    """history: list of {'role': 'user'|'assistant', 'content': str} oldest-first.

    If image_b64 is set, the inbound user turn includes a vision content block.
    """
    context_block = build_user_context(lead, history)

    messages = []
    for h in history[-12:]:
        messages.append({"role": h["role"], "content": h["content"]})

    user_text = incoming_text
    if context_block and len(messages) == 0:
        user_text = f"{context_block}\n\nMensagem do lead:\n{incoming_text}"

    if image_b64:
        media_type = (image_mime or "image/jpeg").split(";")[0].strip()
        if media_type not in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
            media_type = "image/jpeg"
        user_content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": image_b64,
                },
            },
            {"type": "text", "text": user_text or "(o lead mandou só essa imagem, sem texto)"},
        ]
        messages.append({"role": "user", "content": user_content})
    else:
        messages.append({"role": "user", "content": user_text})

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
