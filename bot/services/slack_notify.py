"""Thin Slack poster for outbound notifications from the bot to #leticia-teste."""
from __future__ import annotations

import logging

from django.conf import settings

log = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        if not settings.SLACK_BOT_TOKEN:
            return None
        from slack_sdk import WebClient
        _client = WebClient(token=settings.SLACK_BOT_TOKEN)
    return _client


def post(text: str, blocks: list | None = None) -> None:
    client = _get_client()
    if not client:
        log.warning("slack_notify: no bot token configured; skipping post: %s", text[:80])
        return
    try:
        client.chat_postMessage(
            channel=settings.SLACK_CHANNEL,
            text=text,
            blocks=blocks,
        )
    except Exception as e:
        log.exception("slack_notify.post failed: %s", e)


def notify_opt_out(lead, body: str) -> None:
    post(
        f":no_entry: *Opt-out detectado*\n"
        f"Lead: `{lead.phone}` ({lead.display_name or '—'})\n"
        f"> {body[:300]}"
    )


def notify_escalation(lead, body: str, trigger: str) -> None:
    nathan = settings.SLACK_NATHAN_USER_ID
    mention = f"<@{nathan}> " if nathan else ""
    post(
        f":rotating_light: *Escalação — {trigger}*\n"
        f"{mention}Lead: `{lead.phone}` ({lead.display_name or '-'})\n"
        f"> {body[:400]}\n"
        f"_Assume, por favor._"
    )


def notify_handoff(lead, summary: str, recent_transcript: str = "") -> None:
    """Hot-lead handoff — Letícia decidiu passar pro Nathan. @-menciona ele."""
    nathan = settings.SLACK_NATHAN_USER_ID
    mention = f"<@{nathan}> " if nathan else ""
    msg = (
        f":fire: *Lead quente — handoff pro Nathan*\n"
        f"{mention}\n"
        f"Lead: `{lead.phone}` ({lead.display_name or '-'})\n"
        f"*Resumo da Letícia:* {summary}\n"
    )
    if recent_transcript:
        msg += f"\n*Últimas mensagens:*\n```\n{recent_transcript[:1500]}\n```"
    post(msg)


def notify_inbound_paused(lead, body: str) -> None:
    post(
        f":pause_button: *Mensagem com autonomia OFF*\n"
        f"Lead: `{lead.phone}`\n"
        f"> {body[:300]}\n"
        f"_Use_ `/leticia send {lead.phone} <texto>` _para responder manualmente._"
    )


def notify_error(lead, msg: str) -> None:
    post(f":warning: erro processando `{lead.phone}`: {msg}")
