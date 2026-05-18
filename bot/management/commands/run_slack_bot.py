"""Slack Socket Mode worker. Run as a Railway worker process.

In Slack, the `/` prefix is reserved for registered slash commands. So all of
Letícia's commands work by *mentioning* her (`@Letícia <cmd>`) or by typing the
bare command in the channel:

  @Letícia start                       — global autonomy ON
  @Letícia stop                        — global autonomy OFF
  @Letícia start 5511999999999         — autonomy ON only for that phone
  @Letícia stop 5511999999999          — autonomy OFF only for that phone
  @Letícia send 5511999999999 texto    — send a message manually as Letícia
  @Letícia status                      — counters snapshot
  @Letícia history 5511999999999       — last 10 messages with that lead
  @Letícia optout 5511999999999 motivo — add phone to opt-out list
  @Letícia help                        — show usage

Mentioning the bot without any command shows the help.
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
    "*Comandos Letícia* — marca a bot (`@Letícia <cmd>`):\n"
    "• `@Letícia start` — autonomia GLOBAL ON\n"
    "• `@Letícia stop` — autonomia GLOBAL OFF\n"
    "• `@Letícia start <fone>` — ON só pra esse número\n"
    "• `@Letícia stop <fone>` — OFF só pra esse número\n"
    "• `@Letícia send <fone> <texto>` — eu mando como Letícia\n"
    "• `@Letícia status` — números atuais\n"
    "• `@Letícia history <fone>` — últimas 10 mensagens\n"
    "• `@Letícia optout <fone> [motivo]` — bloqueia esse número\n"
    "• `@Letícia prospect preview <N>` — gera primeira msg pra N leads do Robinhood (sem enviar)\n"
    "• `@Letícia prospect send <N>` — gera + envia pra N leads do Robinhood\n"
    "• `@Letícia help` — esta ajuda\n"
    "\n"
    "_Dica:_ comandos sem mencionar também funcionam (ex: digitar só `status` no canal)."
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

    if cmd == "prospect":
        # subcomandos: preview <N> | send <N>
        if not args:
            return (
                "Uso: `@Letícia prospect preview <N>` (gera msgs, não envia)\n"
                "     `@Letícia prospect send <N>` (envia de verdade)"
            )
        sub = args[0].lower()
        try:
            n = int(args[1]) if len(args) > 1 else 5
        except ValueError:
            n = 5
        n = max(1, min(20, n))
        from bot.services import prospecting, robinhood
        if sub == "preview":
            leads = robinhood.fetch_enriched_leads(limit=n)
            if not leads:
                return "Nenhum lead enriquecido com telefone encontrado."
            out = [f"*Preview de {len(leads)} lead(s)* (não enviei nada):\n"]
            for i, ld in enumerate(leads, 1):
                try:
                    msg = prospecting.generate_first_touch(ld)
                except Exception as e:
                    msg = f"_(erro gerando: {e})_"
                ch = ", ".join(ld.sales_channels) or "?"
                out.append(
                    f"*{i}. {ld.nome_comercial}* `{ld.cnpj}` — {ld.socio_nome} (`{ld.phone}`)\n"
                    f"_Canais: {ch} | Produtos: {', '.join(ld.produtos[:2]) or '?'}_\n"
                    f"```\n{msg}\n```"
                )
            out.append(f"\nSe gostou, roda `@Letícia prospect send {n}` pra disparar.")
            return "\n".join(out)
        if sub == "send":
            leads = robinhood.fetch_enriched_leads(limit=n)
            if not leads:
                return "Nenhum lead enriquecido com telefone encontrado."
            results = []
            for ld in leads:
                try:
                    msg = prospecting.generate_first_touch(ld)
                    if not msg:
                        results.append(f":warning: {ld.nome_comercial}: msg vazia")
                        continue
                    out = prospecting.send_first_touch(ld, msg)
                    if out.get("skipped"):
                        results.append(f":no_entry: {ld.nome_comercial}: opt-out")
                    elif out.get("sent"):
                        results.append(f":envelope_with_arrow: {ld.nome_comercial} → `{ld.phone}`")
                except Exception as e:
                    results.append(f":x: {ld.nome_comercial}: {e}")
            return "*Prospecção enviada:*\n" + "\n".join(results)
        return f"Subcomando `{sub}` inválido. Use `preview` ou `send`."

    return None  # not a command


class Command(BaseCommand):
    help = "Run the Slack Socket Mode listener for #leticia-teste."

    def handle(self, *args, **options):
        bot_token = settings.SLACK_BOT_TOKEN or ""
        app_token = settings.SLACK_APP_TOKEN or ""
        if not bot_token.startswith("xoxb-") or not app_token.startswith("xapp-"):
            # Boot-safe idle: keep the container alive so Railway shows the service as up,
            # but don't try to connect to Slack with placeholder/empty credentials.
            self.stdout.write(self.style.WARNING(
                "Slack credentials missing or malformed.\n"
                f"  SLACK_BOT_TOKEN starts with: {bot_token[:5] or '<empty>'}  (expected 'xoxb-')\n"
                f"  SLACK_APP_TOKEN starts with: {app_token[:5] or '<empty>'}  (expected 'xapp-')\n"
                "Set both in Railway and redeploy. Idling..."
            ))
            import time
            while True:
                time.sleep(3600)
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
