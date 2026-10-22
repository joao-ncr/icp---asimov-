"""Schemas pydantic. Fato / inferencia / hipotese NUNCA se misturam: sao tipos distintos de Evidence."""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field

EvidenceType = Literal["fact", "inference", "hypothesis", "absence_inference"]
SourceKind = Literal["text_quote", "technical_check"]


class Evidence(BaseModel):
    claim: str
    type: EvidenceType
    signal_code: str
    source_kind: SourceKind = "text_quote"
    source_url: str
    source_text: str
    confidence: float = Field(ge=0.0, le=1.0)
    verified: bool = False


class SignalHit(BaseModel):
    code: str
    kind: str
    strength: float
    confidence: float
    evidence: list[Evidence] = []


class Candidate(BaseModel):
    name: str
    domain: Optional[str] = None
    cnpj: Optional[str] = None
    municipio: Optional[str] = None
    uf: Optional[str] = None
    porte: Optional[str] = None
    cnae: Optional[str] = None
    segment: Optional[str] = None
    source: str = "manual"


class HistoricalLead(BaseModel):
    """Linha da base historica de prospeccao. Sem telefone/decisor/socios (LGPD)."""
    source_id: Optional[int] = None
    candidate: Candidate
    segment_label: Optional[str] = None
    capital_social: Optional[float] = None
    digital_maturity: Optional[str] = None
    best_offer: Optional[str] = None
    suggested_service: Optional[str] = None
    identity_confidence: Optional[str] = None
    registration_alert: Optional[str] = None
    cnpj_suspect: bool = False
    ticket_filter: Optional[str] = None
    ticket_reason: Optional[str] = None
    priority: Optional[str] = None
    tier: Optional[str] = None
    legacy_score: Optional[float] = None
    legacy_components: dict[str, float] = {}
    commercial_status: Optional[str] = None
    loss_reason: Optional[str] = None


class PageData(BaseModel):
    url: str
    status_code: int = 200
    text: str = ""
    features: dict = {}
    injection_flags: int = 0


class LLMSignal(BaseModel):
    """Saida do LLM: codigo + trecho literal. O LLM NAO devolve score."""
    code: str
    evidence_quote: str = Field(max_length=300)
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)


class LLMExtraction(BaseModel):
    signals: list[LLMSignal] = []
