"""HTTP entrypoints. Currently: Evolution webhook."""
from __future__ import annotations

import logging

from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .services import evolution, orchestrator

log = logging.getLogger(__name__)


@csrf_exempt
@api_view(["POST"])
def evolution_webhook(request):
    token = request.headers.get("X-Webhook-Token") or request.query_params.get("token")
    if settings.EVOLUTION_WEBHOOK_TOKEN and token != settings.EVOLUTION_WEBHOOK_TOKEN:
        log.warning("rejected webhook: bad token")
        return Response({"ok": False, "error": "unauthorized"}, status=401)

    payload = request.data if isinstance(request.data, dict) else {}
    inbound = evolution.parse_inbound(payload)
    if not inbound:
        return Response({"ok": True, "ignored": True})

    try:
        orchestrator.handle_inbound(
            phone=inbound.phone,
            body=inbound.body,
            message_id=inbound.message_id,
            push_name=inbound.push_name,
            raw=payload,
            media_kind=inbound.media_kind,
            media_mimetype=inbound.media_mimetype,
            media_caption=inbound.media_caption,
            remote_jid=inbound.remote_jid,
        )
    except Exception as e:
        log.exception("orchestrator.handle_inbound failed: %s", e)
        return Response({"ok": False, "error": "internal"}, status=500)

    return Response({"ok": True})
