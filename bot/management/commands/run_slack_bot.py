"""Slack Socket Mode worker. Run as a Railway worker process (Procfile: slack_bot).

Listens to messages in SLACK_CHANNEL. Recognizes commands typed in chat:

  /start                       — global autonomy ON
  /stop                        — global autonomy OFF
  /start 5511999999999         — autonomy ON only for that phone
  /stop  5511999999999         — autonomy OFF only for that phone
  /send  5511999999999 texto   — send a message manually as Letícia
  /status                      — counters snapshot
  /history 5511999999999       — last 10 messages with that lead
  /optout 5511999999999 motivo — add phone to opt-out list
  /help                        — show usage

Mentioning the bot (@Letícia) without a command triggers /help.
"""
from __future__ import annotations

import logging
import re
import shlex

from django.conf import settings
from django.core.management.base import BaseCommand

from bot.services import orchestrator

log = logging.getLogger(__name__)


HELP_TEXT = (
    "*Comandos Letícia* (digite no canal):\n"
    "• `/start` — autonomia GLOBAL ON\n"
    "• `/stop` — autonomia GLOBAL OFF\n"
    "• `/start <fone>` — ON só pra esse número\n"
    "• `/stop <fone>` — OFF só pra esse número\n"
    "• `/send <fone> <texto>` — eu mando como Letícia\n"
    "• `/status` — números atuais\n"
    "• `/history <fone>` — últimas 10 mensagens\n"
    "• `/optout <fone> [motivo]` — bloqueia esse número\n"
    "• `/help` — esta ajuda"
)


def _normalize_phone(raw: str) -> str:
    return re.sub(r"\D", "", raw or "")


def dispatch(text: str, user_id: str, user_name: str) -> str | None:
    text = text.strip()
    if not text:
        return None
    # accept "/cmd" or "cmd"
    if text.startswith("/"):
        text = text[1:]
    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = text.split()
    if not tokens:
        return None
    cmd = tokens[0].lower()
    args = tokens[1:]

    if cmd in {"help", "ajuda", "?"}:
        return HELP_TEXT

    if cmd == "status":
        return orchestrator.cmd_status()

    if cmd in {"start", "stop"}:
        enabled = cmd == "start"
        phone = _normalize_phone(args[0]) if args else None
        return orchestrator.cmd_set_autonomy(user_id, user_name, enabled, phone)

    if cmd == "send":
        if len(args) < 2:
            return "Uso: `/send <fone> <texto>`"
        phone = _normalize_phone(args[0])
        body = " ".join(args[1:])
        return orchestrator.cmd_send(user_id, user_name, phone, body)

    if cmd == "history":
        if not args:
            return "Uso: `/history <fone>`"
        return orchestrator.cmd_history(_normalize_phone(args[0]))

    if cmd == "optout":
        if not args:
            return "Uso: `/optout <fone> [motivo]`"
        phone = _normalize_phone(args[0])
        reason = " ".join(args[1:])
        return orchestrator.cmd_optout_add(user_id, user_name, phone, reason)

    return None  # not a command


class Command(BaseCommand):
    help = "Run the Slack Socket Mode listener for #leticia-teste."

    def handle(self, *args, **options):
        if not settings.SLACK_BOT_TOKEN or not settings.SLACK_APP_TOKEN:
            self.stdout.write(self.style.ERROR(
                "SLACK_BOT_TOKEN and SLACK_APP_TOKEN are required."
            ))
            return

        from slack_bolt import App
        from slack_bolt.adapter.socket_mode import SocketModeHandler

        app = App(token=settings.SLACK_BOT_TOKEN)

        target_channel = settings.SLACK_CHANNEL.lstrip("#")
        allowed_users = set(settings.SLACK_ALLOWED_USERS or [])

        @app.event("message")
        def on_message(event, say, client, logger):
            if event.get("subtype") or event.get("bot_id"):
                return  # ignore bot's own and system messages

            channel_id = event.get("channel")
            channel_name = ""
            try:
                info = client.conversations_info(channel=channel_id)
                channel_name = (info.get("channel") or {}).get("name", "")
            except Exception:
                pass
            if channel_name and channel_name != target_channel:
                return

            user_id = event.get("user", "")
            if allowed_users and user_id not in allowed_users:
                return

            user_name = ""
            try:
                u = client.users_info(user=user_id)
                user_name = (u.get("user") or {}).get("real_name", "") or (u.get("user") or {}).get("name", "")
            except Exception:
                pass

            text = event.get("text", "").strip()
            result = dispatch(text, user_id, user_name)
            if result:
                say(text=result, thread_ts=event.get("ts"))

        @app.event("app_mention")
        def on_mention(event, say):
            # strip the <@U...> mention prefix
            text = re.sub(r"<@[^>]+>", "", event.get("text", "")).strip()
            result = dispatch(text, event.get("user", ""), "") or HELP_TEXT
            say(text=result, thread_ts=event.get("ts"))

        self.stdout.write(self.style.SUCCESS("Letícia Slack bot starting in Socket Mode..."))
        SocketModeHandler(app, settings.SLACK_APP_TOKEN).start()
