"""Autorregulacao do scoring a partir da satisfacao do time comercial (boa | neutra | ruim).

Aprendizado simples, deterministico e auditavel: para cada sinal (e segmento) compara a satisfacao media dos
leads COM o fator contra os SEM, encolhe o desvio pelo tamanho da amostra e limita o multiplicador. Nada muda
enquanto nao houver avaliacoes suficientes. Modulo puro: nao toca no banco (ver app/feedback/store.py)."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from statistics import fmean
from app.core.utils import clamp
from app.scoring.score import cfg

LEVELS = {"boa": 1.0, "neutra": 0.5, "ruim": 0.0}


@dataclass(frozen=True)
class LabeledLead:
    satisfaction: float
    signals: frozenset[str]
    segment: str


@dataclass(frozen=True)
class Calibration:
    version: int = 0
    active: bool = False
    n_labels: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    signal_mult: dict[str, float] = field(default_factory=dict)
    segment_mult: dict[str, float] = field(default_factory=dict)

    def for_signal(self, code: str) -> float:
        return self.signal_mult.get(code, 1.0) if self.active else 1.0

    def for_segment(self, segment: str) -> float:
        return self.segment_mult.get(segment, 1.0) if self.active else 1.0

    def to_params(self) -> dict:
        return {"counts": self.counts, "signal_mult": self.signal_mult, "segment_mult": self.segment_mult}

    @classmethod
    def from_row(cls, row) -> "Calibration":
        p = json.loads(row["params"] or "{}")
        return cls(version=row["id"], active=bool(row["active"]), n_labels=row["n_labels"], counts=p.get("counts", {}),
                   signal_mult=p.get("signal_mult", {}), segment_mult=p.get("segment_mult", {}))


NEUTRAL = Calibration()


def _multiplier(with_factor: list[float], without: list[float], c: dict) -> float | None:
    if len(with_factor) < c["min_group_n"] or len(without) < c["min_group_n"]:
        return None
    delta = fmean(with_factor) - fmean(without)                      # -1..1
    shrink = len(with_factor) / (len(with_factor) + c["shrinkage_k"])
    lo, hi = c["bounds"]
    return round(clamp(1 + c["gain"] * shrink * delta, lo, hi), 3)


def label_counts(samples: list[LabeledLead]) -> dict[str, int]:
    return {level: sum(s.satisfaction == v for s in samples) for level, v in LEVELS.items()}


def is_ready(counts: dict[str, int], c: dict | None = None) -> bool:
    c = c or cfg()["calibration"]
    return sum(counts.values()) >= c["min_labels"] and min(counts["boa"], counts["ruim"]) >= c["min_per_class"]


def fit_calibration(samples: list[LabeledLead]) -> Calibration:
    c = cfg()["calibration"]
    counts = label_counts(samples)
    if not is_ready(counts, c):
        return Calibration(n_labels=len(samples), counts=counts)
    signal_mult = {}
    for code in sorted({code for s in samples for code in s.signals}):
        m = _multiplier([s.satisfaction for s in samples if code in s.signals],
                        [s.satisfaction for s in samples if code not in s.signals], c)
        if m is not None:
            signal_mult[code] = m
    segment_mult = {}
    for seg in sorted({s.segment for s in samples}):
        m = _multiplier([s.satisfaction for s in samples if s.segment == seg],
                        [s.satisfaction for s in samples if s.segment != seg], c)
        if m is not None:
            segment_mult[seg] = m
    return Calibration(active=True, n_labels=len(samples), counts=counts, signal_mult=signal_mult, segment_mult=segment_mult)
