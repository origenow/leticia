"""Robinhood (origenow) Supabase client.

Reads enriched leads from Robinhood's `public.leads` table via PostgREST + GoTrue.
Auth: email + password login → JWT (cached in-memory, refreshed when expired).

All credentials live in env vars; nothing hardcoded.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
from django.conf import settings

log = logging.getLogger(__name__)


# ---- in-memory token cache (per-process; fine for our scale) ----
_token_lock = threading.Lock()
_cached_token: str | None = None
_cached_expires_at: float = 0.0


def _login() -> str:
    """Authenticate against Supabase Auth, return access_token. 1h TTL."""
    base = settings.ROBINHOOD_SUPABASE_URL.rstrip("/")
    url = f"{base}/auth/v1/token?grant_type=password"
    r = httpx.post(
        url,
        headers={
            "apikey": settings.ROBINHOOD_SUPABASE_ANON_KEY,
            "Content-Type": "application/json",
        },
        json={
            "email": settings.ROBINHOOD_EMAIL,
            "password": settings.ROBINHOOD_PASSWORD,
        },
        timeout=15.0,
    )
    r.raise_for_status()
    data = r.json()
    return data["access_token"]


def _get_token() -> str:
    """Return a valid JWT, refreshing if within 60s of expiry."""
    global _cached_token, _cached_expires_at
    with _token_lock:
        if _cached_token and time.time() < _cached_expires_at - 60:
            return _cached_token
        _cached_token = _login()
        _cached_expires_at = time.time() + 3600  # 1h default
        return _cached_token


def _headers() -> dict[str, str]:
    return {
        "apikey": settings.ROBINHOOD_SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type": "application/json",
    }


# ---- phone normalization ----

# Brazilian mobile: 55 + 2-digit DDD + 9 + 8 digits  → 13 dígitos total
# Brazilian landline: 55 + 2-digit DDD + 8 digits   → 12 dígitos total
def normalize_phone_br(raw: str) -> str | None:
    """Return E.164-ish digits (no +), or None if can't be normalized."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    # Already with country code
    if digits.startswith("55") and len(digits) in (12, 13):
        return digits
    # Just DDD + number
    if len(digits) in (10, 11):
        return "55" + digits
    return None


def _is_mobile(phone: str) -> bool:
    """Heuristic: 13 digits starting with 55, position 4 (after 55 + DDD) is 9 → mobile."""
    return len(phone) == 13 and phone.startswith("55") and phone[4] == "9"


@dataclass
class RobinhoodLead:
    id: str
    nome_comercial: str
    nome_vendedor: str
    cnpj: str
    endereco: str
    produtos: list[str]
    link_loja: str
    link_vitrine: str
    percentual_positivo: float
    numero_avaliacoes: int
    status: str
    responsavel: str | None
    sales_channels: list[str]
    deep_research: str
    socio_nome: str
    phone: str  # already normalized E.164-BR
    raw: dict


def _pick_best_phone(socios: list[dict]) -> tuple[str, str] | None:
    """Choose first mobile phone we can normalize. Returns (socio_nome, phone) or None.

    Strategy: walk every socio, every telefone, prefer mobiles (13 digits starting 55*9).
    """
    fallback: tuple[str, str] | None = None
    for s in socios or []:
        name = s.get("nome", "") or ""
        for raw in s.get("telefones") or []:
            norm = normalize_phone_br(raw)
            if not norm:
                continue
            if _is_mobile(norm):
                return (name, norm)
            if fallback is None:
                fallback = (name, norm)
    return fallback


def _to_lead(row: dict) -> RobinhoodLead | None:
    enriched = row.get("enriched_data") or {}
    socios = enriched.get("socios") or []
    pick = _pick_best_phone(socios)
    if not pick:
        return None
    socio_nome, phone = pick

    produtos = [p for p in (row.get("produto_1"), row.get("produto_2"), row.get("produto_3")) if p]
    sales_channels = row.get("sales_channels") or []
    if isinstance(sales_channels, dict):
        sales_channels = list(sales_channels.values())

    return RobinhoodLead(
        id=row["id"],
        nome_comercial=row.get("nome_comercial", "") or "",
        nome_vendedor=row.get("nome_vendedor", "") or "",
        cnpj=row.get("cnpj", "") or "",
        endereco=row.get("endereco", "") or "",
        produtos=produtos,
        link_loja=row.get("link_loja", "") or "",
        link_vitrine=row.get("link_vitrine", "") or "",
        percentual_positivo=float(row.get("percentual_positivo") or 0),
        numero_avaliacoes=int(row.get("numero_avaliacoes") or 0),
        status=row.get("status", "") or "",
        responsavel=row.get("responsavel"),
        sales_channels=[c for c in sales_channels if c],
        deep_research=row.get("deep_research_data") or "",
        socio_nome=socio_nome,
        phone=phone,
        raw=row,
    )


def fetch_enriched_leads(
    limit: int = 5,
    status: str = "enriquecido",
    skip_phones: set[str] | None = None,
) -> list[RobinhoodLead]:
    """Pull leads with status `enriquecido` (or `pesquisado`), normalize phones,
    drop rows without any usable phone, skip ones already on `skip_phones`.
    """
    base = settings.ROBINHOOD_SUPABASE_URL.rstrip("/")
    # Over-fetch since some rows won't have phones
    fetch_limit = max(limit * 4, 20)
    url = (
        f"{base}/rest/v1/leads"
        f"?select=id,nome_comercial,nome_vendedor,cnpj,endereco,"
        f"produto_1,produto_2,produto_3,link_loja,link_vitrine,"
        f"percentual_positivo,numero_avaliacoes,status,responsavel,"
        f"sales_channels,enriched_data,deep_research_data,updated_at"
        f"&status=eq.{status}"
        f"&order=updated_at.desc"
        f"&limit={fetch_limit}"
    )
    try:
        r = httpx.get(url, headers=_headers(), timeout=20.0)
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.exception("robinhood.fetch_enriched_leads failed: %s", e)
        return []
    rows = r.json()
    out: list[RobinhoodLead] = []
    seen_phones: set[str] = set(skip_phones or [])
    for row in rows:
        ld = _to_lead(row)
        if not ld:
            continue
        if ld.phone in seen_phones:
            continue
        seen_phones.add(ld.phone)
        out.append(ld)
        if len(out) >= limit:
            break
    return out


def get_lead_by_id(lead_id: str) -> RobinhoodLead | None:
    """Single-lead lookup by Robinhood id."""
    base = settings.ROBINHOOD_SUPABASE_URL.rstrip("/")
    url = f"{base}/rest/v1/leads?id=eq.{lead_id}&limit=1"
    try:
        r = httpx.get(url, headers=_headers(), timeout=15.0)
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.exception("robinhood.get_lead_by_id failed: %s", e)
        return None
    rows = r.json()
    if not rows:
        return None
    return _to_lead(rows[0])
