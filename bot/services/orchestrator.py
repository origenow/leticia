"""Core conversation orchestrator: receive inbound, run guardrails, generate, dispatch."""
from __future__ import annotations

import logging
import re

from django.utils import timezone

# Letícia inclui este token quando decide passar o lead pro Nathan.
HANDOFF_RE = re.compile(r"\[\[HANDOFF:\s*([^\]]+)\]\]", re.IGNORECASE)

from ..models import (
    CommandLog,
    Conversation,
    Escalation,
    Lead,
    Message,
    OptOut,
)
from . import anthropic_client, evolution, guardrails, message_dispatcher, slack_notify

log = logging.getLogger(__name__)


def _get_or_create_lead(phone: str, push_name: str = "") -> Lead:
    lead, created = Lead.objects.get_or_create(
        phone=phone,
        defaults={"display_name": push_name, "source": "whatsapp_inbound"},
    )
    if not created and push_name and not lead.display_name:
        lead.display_name = push_name
        lead.save(update_fields=["display_name", "updated_at"])
    return lead


def _open_conversation(lead: Lead) -> Conversation:
    conv = (
        Conversation.objects.filter(lead=lead)
        .exclude(status="closed")
        .order_by("-id")
        .first()
    )
    if conv:
        return conv
    return Conversation.objects.create(lead=lead)


def _history(conv: Conversation, limit: int = 12) -> list[dict]:
    msgs = list(conv.messages.order_by("-id")[:limit])[::-1]
    out = []
    for m in msgs:
        out.append({
            "role": "user" if m.direction == "inbound" else "assistant",
            "content": m.body,
        })
    return out


def handle_inbound(phone: str, body: str, message_id: str, push_name: str, raw: dict) -> None:
    # Best-effort blue-tick: marca como lida ANTES de processar, pra parecer humana.
    # Falha silenciosa — não bloqueia o fluxo.
    remote_jid = f"{phone}@s.whatsapp.net"
    try:
        evolution.mark_as_read(remote_jid, message_id)
    except Exception:
        log.exception("mark_as_read raised (unexpected)")

    if OptOut.objects.filter(phone=phone).exists():
        log.info("ignoring inbound from opted-out phone=%s", phone)
        return

    lead = _get_or_create_lead(phone, push_name)
    conv = _open_conversation(lead)

    Message.objects.create(
        conversation=conv,
        direction="inbound",
        body=body,
        evolution_message_id=message_id,
        raw=raw,
    )
    conv.last_message_at = timezone.now()
    conv.save(update_fields=["last_message_at", "updated_at"])

    verdict = guardrails.evaluate(body)

    if verdict.opt_out:
        OptOut.objects.get_or_create(phone=phone, defaults={"reason": body[:200]})
        conv.status = "closed"
        conv.save(update_fields=["status", "updated_at"])
        _send_and_log(conv, guardrails.OPT_OUT_REPLY)
        slack_notify.notify_opt_out(lead, body)
        return

    if verdict.escalate:
        Escalation.objects.create(lead=lead, trigger=verdict.trigger, context=body[:500])
        conv.status = "escalated"
        conv.save(update_fields=["status", "updated_at"])
        slack_notify.notify_escalation(lead, body, verdict.trigger)
        # Soft reply, then humans take over.
        _send_and_log(
            conv,
            "Entendi. Vou chamar o Nathan aqui pra te dar a resposta certa, "
            "pode ser? Ele responde já.",
        )
        return

    if not lead.autonomy_enabled or conv.status == "paused":
        log.info("autonomy off for lead=%s; not replying", phone)
        slack_notify.notify_inbound_paused(lead, body)
        return

    if verdict.identity_question:
        _send_and_log(conv, guardrails.IDENTITY_REPLY)
        return

    history = _history(conv)[:-1]  # exclude the just-inserted inbound
    reply = anthropic_client.generate_reply(lead, history, body)
    if not reply:
        slack_notify.notify_error(lead, "Claude returned empty reply")
        return

    # HANDOFF detection: Letícia incluiu [[HANDOFF: motivo]] na resposta?
    # Se sim: strip da tag, log de escalação, pinga o Nathan no Slack.
    handoff_match = HANDOFF_RE.search(reply)
    if handoff_match:
        summary = handoff_match.group(1).strip()
        reply = HANDOFF_RE.sub("", reply).strip()
        try:
            Escalation.objects.create(lead=lead, trigger="handoff", context=summary[:500])
            conv.status = "escalated"
            conv.save(update_fields=["status", "updated_at"])
            transcript_lines = []
            for h in history[-6:]:
                tag = "lead" if h["role"] == "user" else "Letícia"
                transcript_lines.append(f"{tag}: {h['content']}")
            transcript_lines.append(f"lead: {body}")
            slack_notify.notify_handoff(lead, summary, "\n".join(transcript_lines))
        except Exception:
            log.exception("handoff side effects failed (still delivering reply)")

    _send_and_log(conv, reply)


def _send_and_log(conv: Conversation, text: str) -> None:
    def _on_sent(part: str, result: dict) -> None:
        Message.objects.create(
            conversation=conv,
            direction="outbound",
            body=part,
            raw={"send_result": result},
        )

    message_dispatcher.dispatch_async(conv.lead.phone, text, on_sent=_on_sent)


# ---- Slack-triggered actions ----

def cmd_send(slack_user: str, slack_user_name: str, phone: str, text: str) -> str:
    lead, _ = Lead.objects.get_or_create(
        phone=phone,
        defaults={"source": "slack_command"},
    )
    if OptOut.objects.filter(phone=phone).exists():
        result = f":no_entry: {phone} está no opt-out. Mensagem não enviada."
        _log_cmd(slack_user, slack_user_name, "send", f"{phone} {text}", result)
        return result
    conv = _open_conversation(lead)
    _send_and_log(conv, text)
    result = f":envelope_with_arrow: enviei pra {phone}"
    _log_cmd(slack_user, slack_user_name, "send", f"{phone} {text}", result)
    return result


def cmd_set_autonomy(slack_user: str, slack_user_name: str, enabled: bool, phone: str | None = None) -> str:
    if phone:
        lead = Lead.objects.filter(phone=phone).first()
        if not lead:
            return f"Lead {phone} não encontrado."
        lead.autonomy_enabled = enabled
        lead.save(update_fields=["autonomy_enabled", "updated_at"])
        state = "ON" if enabled else "OFF"
        result = f"Autonomia {state} para {phone}."
    else:
        Lead.objects.update(autonomy_enabled=enabled)
        state = "ON" if enabled else "OFF"
        result = f"Autonomia GLOBAL agora está {state}."
    _log_cmd(slack_user, slack_user_name, "autonomy", f"{enabled} {phone or '*'}", result)
    return result


def cmd_status() -> str:
    total_leads = Lead.objects.count()
    active = Conversation.objects.filter(status="active").count()
    paused = Conversation.objects.filter(status="paused").count()
    escalated = Conversation.objects.filter(status="escalated").count()
    optouts = OptOut.objects.count()
    return (
        f"*Status Letícia*\n"
        f"• Leads: {total_leads}\n"
        f"• Conversas ativas: {active}\n"
        f"• Pausadas: {paused}\n"
        f"• Escaladas: {escalated}\n"
        f"• Opt-outs: {optouts}"
    )


def cmd_optout_add(slack_user: str, slack_user_name: str, phone: str, reason: str = "") -> str:
    OptOut.objects.get_or_create(phone=phone, defaults={"reason": reason or "manual"})
    result = f"{phone} adicionado ao opt-out."
    _log_cmd(slack_user, slack_user_name, "optout_add", phone, result)
    return result


def cmd_history(phone: str, limit: int = 10) -> str:
    lead = Lead.objects.filter(phone=phone).first()
    if not lead:
        return f"Lead {phone} não encontrado."
    conv = Conversation.objects.filter(lead=lead).order_by("-id").first()
    if not conv:
        return f"Sem conversa para {phone}."
    msgs = list(conv.messages.order_by("-id")[:limit])[::-1]
    lines = [f"*Histórico {phone}* (últimas {len(msgs)}):"]
    for m in msgs:
        prefix = "👤" if m.direction == "inbound" else "💬"
        lines.append(f"{prefix} {m.body[:200]}")
    return "\n".join(lines)


def _log_cmd(user: str, user_name: str, command: str, args: str, result: str) -> None:
    try:
        CommandLog.objects.create(
            slack_user_id=user,
            slack_user_name=user_name,
            command=command,
            args=args,
            result=result,
        )
    except Exception:
        log.exception("failed to log command")
