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
    remote_jid = f"{phone}@s.whatsapp.net"
    for i, part in enumerate(parts):
        delay_ms = random.randint(
            settings.LETICIA_TYPING_DELAY_MIN_MS,
            settings.LETICIA_TYPING_DELAY_MAX_MS,
        )
        # Mostra "digitando..." enquanto espera. Tempo proporcional ao tamanho do balão.
        # ~30 chars/seg de digitação humana, mínimo 1.2s, máximo o LETICIA_TYPING_DELAY_MAX_MS.
        chars_delay_ms = min(
            settings.LETICIA_TYPING_DELAY_MAX_MS,
            max(1200, len(part) * 33),
        )
        total_wait_ms = max(delay_ms, chars_delay_ms) if i > 0 else chars_delay_ms
        try:
            evolution.send_presence(remote_jid, "composing", delay_ms=total_wait_ms)
        except Exception:
            log.exception("send_presence raised")
        time.sleep(total_wait_ms / 1000.0)
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
