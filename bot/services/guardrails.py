"""Safety layer: opt-out detection, escalation triggers, identity questions."""
from __future__ import annotations

import re
from dataclasses import dataclass

OPT_OUT_PATTERNS = [
    r"\bpar(a|e)\b",
    r"\bn[ãa]o\s+quero\b",
    r"\bremov[ae]\b",
    r"\bdescadastr",
    r"\bsai\b",
    r"\bbloqueia\b",
    r"\bn[ãa]o\s+me\s+mand",
    r"\bunsubscribe\b",
    r"\bstop\b",
]

ESCALATION_PATTERNS = [
    r"\bprocon\b",
    r"\breclame\s*aqui\b",
    r"\badvogad",
    r"\bprocesso\b",
    r"\bden[úu]ncia\b",
    r"\bjustiça\b",
    r"\bjudicial\b",
]

IDENTITY_PATTERNS = [
    r"\bvoc[êe]\s+[ée]\s+(ia|ai|rob[ôo]|bot|m[áa]quina|humana?|pessoa)\b",
    r"\bisso\s+[ée]\s+autom",
    r"\b[ée]\s+um?\s+(rob[ôo]|bot|ia)\b",
    r"\bquem\s+(t[áa]\s+)?(ai|aí|falando)\b",
    r"\bvoc[êe]\s+existe\b",
]

OPT_OUT_RE = re.compile("|".join(OPT_OUT_PATTERNS), re.IGNORECASE)
ESCALATION_RE = re.compile("|".join(ESCALATION_PATTERNS), re.IGNORECASE)
IDENTITY_RE = re.compile("|".join(IDENTITY_PATTERNS), re.IGNORECASE)


@dataclass
class GuardrailVerdict:
    opt_out: bool = False
    escalate: bool = False
    identity_question: bool = False
    trigger: str = ""


def evaluate(text: str) -> GuardrailVerdict:
    v = GuardrailVerdict()
    if OPT_OUT_RE.search(text):
        v.opt_out = True
        v.trigger = "opt_out"
    if ESCALATION_RE.search(text):
        v.escalate = True
        v.trigger = "escalation"
    if IDENTITY_RE.search(text):
        v.identity_question = True
        if not v.trigger:
            v.trigger = "identity"
    return v


OPT_OUT_REPLY = (
    "Entendido, vou te tirar da nossa lista agora mesmo. "
    "Desculpa pelo incômodo e obrigada pelo seu tempo. 🙏"
)

IDENTITY_REPLY = (
    "Boa, pergunta justa. Sou IA generativa sim, trabalho em colaboração com o Nathan "
    "(vendedor real da Origenow). Tudo que eu falo aqui é informação validada, "
    "e o que combinarmos com você vale. Quer continuar?"
)
