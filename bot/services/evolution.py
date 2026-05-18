"""Thin Evolution API client. Sends WhatsApp messages and parses inbound webhooks."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import quote

import httpx
from django.conf import settings

log = logging.getLogger(__name__)


@dataclass
class InboundMessage:
    phone: str
    body: str
    message_id: str
    push_name: str
    raw: dict
    # Mídia (preenchido só quando messageType for audio/image/document)
    media_kind: str = ""        # "audio" | "image" | "document" | ""
    media_mimetype: str = ""
    media_caption: str = ""     # legenda da imagem ou nome do doc
    remote_jid: str = ""        # jid completo, pra baixar mídia depois


def parse_inbound(payload: dict) -> InboundMessage | None:
    """Extract a normalized message from Evolution's messages.upsert webhook.

    Evolution payload shape (typical):
    {
      "event": "messages.upsert",
      "instance": "...",
      "data": {
        "key": {"remoteJid": "5511999999999@s.whatsapp.net", "fromMe": false, "id": "..."},
        "message": {"conversation": "olá"} | {"extendedTextMessage": {"text": "..."}},
        "pushName": "Fulano",
        ...
      }
    }
    """
    event = payload.get("event", "")
    if event not in {"messages.upsert", "MESSAGES_UPSERT"}:
        return None
    data = payload.get("data") or {}
    key = data.get("key") or {}
    if key.get("fromMe"):
        return None
    remote_jid = key.get("remoteJid", "")
    if not remote_jid or "@g.us" in remote_jid:  # ignore group chats for v1
        return None
    phone = remote_jid.split("@", 1)[0]

    msg = data.get("message") or {}
    body = (
        msg.get("conversation")
        or (msg.get("extendedTextMessage") or {}).get("text")
        or ""
    )

    media_kind = ""
    media_mime = ""
    media_caption = ""
    if msg.get("audioMessage"):
        media_kind = "audio"
        media_mime = msg["audioMessage"].get("mimetype", "")
    elif msg.get("imageMessage"):
        media_kind = "image"
        media_mime = msg["imageMessage"].get("mimetype", "")
        media_caption = msg["imageMessage"].get("caption", "") or ""
    elif msg.get("documentMessage"):
        media_kind = "document"
        media_mime = msg["documentMessage"].get("mimetype", "")
        media_caption = msg["documentMessage"].get("fileName", "") or msg["documentMessage"].get("title", "") or ""
    elif msg.get("videoMessage"):
        media_kind = "video"
        media_mime = msg["videoMessage"].get("mimetype", "")
        media_caption = msg["videoMessage"].get("caption", "") or ""

    if not body.strip() and not media_kind:
        return None

    return InboundMessage(
        phone=phone,
        body=body.strip(),
        message_id=key.get("id", ""),
        push_name=data.get("pushName", ""),
        raw=payload,
        media_kind=media_kind,
        media_mimetype=media_mime,
        media_caption=media_caption,
        remote_jid=remote_jid,
    )


def get_media_base64(message_key: dict) -> tuple[str, str] | None:
    """POST /chat/getBase64FromMediaMessage/{instance} — baixa mídia (áudio/imagem/doc).

    Returns (base64_str, mimetype) or None on failure.
    """
    instance = quote(settings.EVOLUTION_INSTANCE, safe="")
    url = f"{settings.EVOLUTION_BASE_URL.rstrip('/')}/chat/getBase64FromMediaMessage/{instance}"
    headers = {"apikey": settings.EVOLUTION_API_KEY, "Content-Type": "application/json"}
    body = {"message": {"key": message_key}, "convertToMp4": False}
    try:
        r = httpx.post(url, json=body, headers=headers, timeout=60.0)
        r.raise_for_status()
        d = r.json()
        b64 = d.get("base64") or d.get("data") or ""
        mime = d.get("mimetype") or ""
        if not b64:
            return None
        return (b64, mime)
    except httpx.HTTPError as e:
        log.warning("evolution.get_media_base64 failed: %s", e)
        return None


def mark_as_read(remote_jid: str, message_id: str) -> dict:
    """POST /chat/markMessageAsRead/{instance} — send blue tick to the lead.

    Best-effort: any error is logged but never raised, so failure to mark
    doesn't break the response pipeline.
    """
    if not remote_jid or not message_id:
        return {"skipped": True}
    instance = quote(settings.EVOLUTION_INSTANCE, safe="")
    url = f"{settings.EVOLUTION_BASE_URL.rstrip('/')}/chat/markMessageAsRead/{instance}"
    headers = {"apikey": settings.EVOLUTION_API_KEY, "Content-Type": "application/json"}
    body = {
        "readMessages": [
            {"remoteJid": remote_jid, "fromMe": False, "id": message_id}
        ]
    }
    try:
        r = httpx.post(url, json=body, headers=headers, timeout=10.0)
        r.raise_for_status()
        return r.json() if r.content else {"ok": True}
    except httpx.HTTPError as e:
        log.warning("evolution.mark_as_read failed jid=%s err=%s", remote_jid, e)
        return {"error": str(e)}


def send_presence(remote_jid: str, presence: str = "composing", delay_ms: int = 1500) -> dict:
    """POST /chat/sendPresence/{instance} — show 'typing...' to the lead.

    presence values: 'composing' (typing), 'recording' (recording audio),
    'paused', 'available', 'unavailable'.
    """
    if not remote_jid:
        return {"skipped": True}
    instance = quote(settings.EVOLUTION_INSTANCE, safe="")
    url = f"{settings.EVOLUTION_BASE_URL.rstrip('/')}/chat/sendPresence/{instance}"
    headers = {"apikey": settings.EVOLUTION_API_KEY, "Content-Type": "application/json"}
    body = {"number": remote_jid, "presence": presence, "delay": delay_ms}
    try:
        r = httpx.post(url, json=body, headers=headers, timeout=10.0)
        r.raise_for_status()
        return r.json() if r.content else {"ok": True}
    except httpx.HTTPError as e:
        log.warning("evolution.send_presence failed jid=%s err=%s", remote_jid, e)
        return {"error": str(e)}


def send_text(phone: str, text: str) -> dict:
    """POST to Evolution /message/sendText/{instance}.

    Instance name is URL-encoded explicitly here so accented names like 'Letícia'
    survive env-var round-tripping (where Latin-1 mojibake can creep in).
    """
    instance = quote(settings.EVOLUTION_INSTANCE, safe="")
    url = f"{settings.EVOLUTION_BASE_URL.rstrip('/')}/message/sendText/{instance}"
    headers = {"apikey": settings.EVOLUTION_API_KEY, "Content-Type": "application/json"}
    body = {"number": phone, "text": text}
    try:
        r = httpx.post(url, json=body, headers=headers, timeout=15.0)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        log.exception("evolution.send_text failed phone=%s err=%s", phone, e)
        return {"error": str(e)}
