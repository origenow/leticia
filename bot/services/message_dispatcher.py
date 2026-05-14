"""Splits Letícia's reply into balões and sends with humanized delay."""
from __future__ import annotations

import logging
import random
import threading
import time

from django.conf import settings

from . import evolution

log = logging.getLogger(__name__)


def split_balloons(text: str) -> list[str]:
    if "<<SPLIT>>" in text:
        parts = [p.strip() for p in text.split("<<SPLIT>>") if p.strip()]
    else:
        # Fallback split: paragraph breaks
        parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    return parts or [text]


def _send_with_delays(phone: str, parts: list[str], on_sent=None) -> None:
    for i, part in enumerate(parts):
        if i > 0:
            delay_ms = random.randint(
                settings.LETICIA_TYPING_DELAY_MIN_MS,
                settings.LETICIA_TYPING_DELAY_MAX_MS,
            )
            time.sleep(delay_ms / 1000.0)
        result = evolution.send_text(phone, part)
        if on_sent:
            try:
                on_sent(part, result)
            except Exception:
                log.exception("on_sent callback failed")


def dispatch_async(phone: str, full_text: str, on_sent=None) -> None:
    """Fire-and-forget send. Returns immediately; the webhook should not block on this."""
    parts = split_balloons(full_text)
    t = threading.Thread(
        target=_send_with_delays,
        args=(phone, parts),
        kwargs={"on_sent": on_sent},
        daemon=True,
    )
    t.start()
