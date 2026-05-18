"""Outbound prospecting: take a Robinhood lead, generate first-touch message, send it.

Used by the Slack `prospect preview/send` command.
"""
from __future__ import annotations

import logging

from django.conf import settings

from ..models import Conversation, Lead, Message, OptOut
from . import anthropic_client, evolution, message_dispatcher, robinhood
from .leticia_persona import SYSTEM_PROMPT

log = logging.getLogger(__name__)


COLD_OPEN_INSTRUCTION = """CONTEXTO ATUAL: você está iniciando uma abordagem fria (primeiro contato).
O lead AINDA NÃO falou com você. Sua tarefa é mandar a PRIMEIRA mensagem
pra abrir o papo.

REGRAS DA PRIMEIRA MENSAGEM:
- Não use "Olá [Nome]" robótico. Soa frio. Comece com "Opa, [nome]!", "E aí,
  [nome], tudo bem?" ou variação.
- Mencione DETALHE ESPECÍFICO do lead (loja, produto, canal). Mostra que
  você não tá mandando spam.
- Faça UMA pergunta curta no final pra abrir conversa. Não pitch corrido.
- Máximo 2 balões. Tom amigável, sem corporativo.
- ZERO emoji nesta primeira mensagem.
- NÃO use a tag [[HANDOFF]] em primeira abordagem.
- Não diga "vi seu cadastro", "encontrei seu contato", "comprei lista".
  Diga "tava olhando lojas de X no [marketplace] e bateu o olho na de
  vocês", ou similar.

Use o contexto do lead abaixo pra personalizar."""


def _format_lead_context(ld: robinhood.RobinhoodLead) -> str:
    parts = [
        f"Nome do contato: {ld.socio_nome or '(sem nome de sócio, use neutro)'}",
        f"Empresa: {ld.nome_comercial}",
        f"Marca/Loja: {ld.nome_vendedor}",
    ]
    if ld.produtos:
        parts.append(f"Produtos: {', '.join(ld.produtos[:3])}")
    if ld.sales_channels:
        parts.append(f"Canais ativos: {', '.join(ld.sales_channels)}")
    if ld.percentual_positivo:
        parts.append(
            f"Reputação no marketplace: {ld.percentual_positivo}% positivo "
            f"em {ld.numero_avaliacoes} avaliações"
        )
    if ld.link_loja:
        parts.append(f"Link da loja: {ld.link_loja}")
    if ld.deep_research:
        parts.append(f"\nResearch (resumo curto): {ld.deep_research[:800]}")
    return "\n".join(parts)


def generate_first_touch(ld: robinhood.RobinhoodLead) -> str:
    """Generate a personalized first message for this lead. No send."""
    ctx = _format_lead_context(ld)
    user_turn = f"{COLD_OPEN_INSTRUCTION}\n\nDADOS DO LEAD:\n{ctx}"

    from anthropic import Anthropic
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=400,
        system=[
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
        ],
        messages=[{"role": "user", "content": user_turn}],
    )
    parts = []
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts).strip()


def send_first_touch(ld: robinhood.RobinhoodLead, reply: str) -> dict:
    """Persist a Lead/Conversation/Message and dispatch via Evolution.

    Returns a dict with status info for logging.
    """
    if OptOut.objects.filter(phone=ld.phone).exists():
        return {"skipped": True, "reason": "opt_out", "phone": ld.phone}

    lead, _created = Lead.objects.get_or_create(
        phone=ld.phone,
        defaults={
            "display_name": ld.socio_nome or ld.nome_comercial,
            "source": "robinhood",
            "metadata": {
                "robinhood_id": ld.id,
                "cnpj": ld.cnpj,
                "nome_comercial": ld.nome_comercial,
                "nome_vendedor": ld.nome_vendedor,
                "produtos": ld.produtos,
                "sales_channels": ld.sales_channels,
                "link_loja": ld.link_loja,
            },
        },
    )
    # Always update metadata in case lead was created from inbound earlier
    if "robinhood_id" not in (lead.metadata or {}):
        lead.metadata = {**(lead.metadata or {}), "robinhood_id": ld.id, "cnpj": ld.cnpj}
        lead.save(update_fields=["metadata", "updated_at"])

    conv = Conversation.objects.filter(lead=lead).exclude(status="closed").order_by("-id").first()
    if not conv:
        conv = Conversation.objects.create(lead=lead)

    def _on_sent(part: str, result: dict) -> None:
        Message.objects.create(
            conversation=conv,
            direction="outbound",
            body=part,
            raw={"send_result": result, "source": "prospect_send"},
        )

    message_dispatcher.dispatch_async(ld.phone, reply, on_sent=_on_sent)
    return {"sent": True, "phone": ld.phone, "lead_id": str(lead.id)}
