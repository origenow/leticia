"""Áudio → texto via Groq Whisper (free tier).

Uso:
    from .media_transcribe import transcribe_audio_b64
    txt = transcribe_audio_b64(base64_audio, mime="audio/ogg; codecs=opus")

Retorna string vazia em qualquer falha (logada). Nunca levanta exceção,
pra não derrubar o pipeline inbound.
"""
from __future__ import annotations

import base64
import io
import logging

import httpx
from django.conf import settings

log = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3-turbo"  # rápido + barato no free tier


def _ext_from_mime(mime: str) -> str:
    if not mime:
        return "ogg"
    m = mime.lower().split(";")[0].strip()
    return {
        "audio/ogg": "ogg",
        "audio/opus": "ogg",
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/mp4": "m4a",
        "audio/m4a": "m4a",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/webm": "webm",
        "audio/aac": "aac",
    }.get(m, "ogg")


def transcribe_audio_b64(b64: str, mime: str = "audio/ogg") -> str:
    """Transcribe a base64-encoded audio blob via Groq Whisper. Returns text or ''."""
    if not b64:
        return ""
    key = getattr(settings, "GROQ_API_KEY", "") or ""
    if not key:
        log.warning("media_transcribe: GROQ_API_KEY not set; cannot transcribe")
        return ""
    try:
        audio_bytes = base64.b64decode(b64)
    except Exception:
        log.exception("media_transcribe: bad base64")
        return ""
    ext = _ext_from_mime(mime)
    files = {
        "file": (f"audio.{ext}", io.BytesIO(audio_bytes), mime or f"audio/{ext}"),
    }
    data = {
        "model": GROQ_MODEL,
        "response_format": "text",
        "language": "pt",
        "temperature": "0",
    }
    headers = {"Authorization": f"Bearer {key}"}
    try:
        r = httpx.post(GROQ_URL, headers=headers, files=files, data=data, timeout=60.0)
        if r.status_code >= 400:
            log.warning("groq transcription failed %s: %s", r.status_code, r.text[:300])
            return ""
        # response_format=text returns plain text
        text = r.text.strip()
        # Some Groq deployments still wrap in JSON even when text requested
        if text.startswith("{"):
            try:
                import json
                j = json.loads(text)
                text = (j.get("text") or "").strip()
            except Exception:
                pass
        return text
    except httpx.HTTPError as e:
        log.exception("groq transcription HTTP error: %s", e)
        return ""
