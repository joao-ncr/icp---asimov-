"""Scoring 100% deterministico (nenhuma chamada a LLM). Pesos em app/config/scoring.yaml."""
from __future__ import annotations
from functools import lru_cache
from app.core.settings import get_settings
from app.core.utils import clamp, load_yaml, norm_text, sha
from app.intelligence.signals import taxonomy
from app.models.schemas import SignalHit

SERVICES = ["site", "aplicativo", "software", "dados", "automacao"]
COLLABORATION = "colaboracao"            # eixo proprio de oportunidade (nao e servico): ver collaboration_score
AXES = SERVICES + [COLLABORATION]
DISCIPLINES = ["aplicativo", "software", "dados", "automacao"]      # especialidades cuja combinacao caracteriza colaboracao


@lru_cache
def cfg() -> dict:
    return load_yaml(get_settings().config_dir / "scoring.yaml")


def config_hash() -> str:
    return sha(open(get_settings().config_dir / "scoring.yaml", encoding="utf-8").read())[:12]


def service_fits(hits: dict[str, SignalHit], calibration=None) -> tuple[dict[str, float], dict[str, list[str]]]:
    """noisy-OR por servico sobre sinais do tipo 'need'. Poucos sinais fracos => fit limitado (weak_fit_cap)."""
    c = cfg()["evidence"]
    fits, why = {}, {}
    for svc in SERVICES:
        contribs = []
        for code, h in hits.items():
            sig = taxonomy()[code]
            if sig["kind"] != "need":
                continue
            w = sig["services"].get(svc, 0)
            if w:
                learned = calibration.for_signal(code) if calibration else 1.0      # ajuste aprendido do feedback humano
                contribs.append((code, min(0.99, w * h.strength * h.confidence * learned)))
        p = 1.0
        for _, x in contribs:
            p *= 1 - x
        fit = 1 - p
        if contribs and len(contribs) < 2 and max(x for _, x in contribs) < c["weak_signal_threshold"] * 0.8:
            fit = min(fit, c["weak_fit_cap"])
        if contribs and all(taxonomy()[code].get("concreteness") == "contextual" for code, _ in contribs):
            fit = min(fit, c["contextual_fit_cap"])         # atividade descrita sem dor declarada != necessidade concreta
        fits[svc] = round(clamp(fit), 4)
        why[svc] = [code for code, _ in sorted(contribs, key=lambda t: -t[1])]
    return fits, why


def collaboration_score(hits: dict[str, SignalHit], fits: dict[str, float], why: dict[str, list[str]]) -> tuple[float, list[str]]:
    """Eixo proprio: necessidade que atravessa especialidades. Combina (a) sinais explicitos de colaboracao e (b) amplitude,
    isto e, varias disciplinas sustentadas por sinais DISTINTOS (um unico sinal nao pode inflar varias disciplinas)."""
    c = cfg()["collaboration"]
    explicit = 1.0
    for code, h in hits.items():
        weight = taxonomy()[code].get("collaboration", 0)
        if weight and h.kind == "need":
            explicit *= 1 - min(0.99, weight * h.strength * h.confidence)
    disciplines = [d for d in DISCIPLINES if fits[d] >= c["discipline_fit_min"] and _has_primary_signal(d, why[d], c["discipline_primary_weight"])]
    supporting = {code for d in disciplines for code in why[d]}
    breadth = 0.0
    if len(disciplines) >= 2 and len(supporting) >= c["min_distinct_signals"]:
        scale = c["breadth_score"]
        breadth = scale[min(len(disciplines), max(scale))]
    return round(clamp(1 - (1 - breadth) * explicit), 4), disciplines


def _has_primary_signal(service: str, codes: list[str], minimum: float) -> bool:
    return any(taxonomy()[code]["services"].get(service, 0) >= minimum for code in codes)


def opportunity_gap(hits: dict[str, SignalHit], svc: str) -> float:
    presence = 0.0
    for code, h in hits.items():
        sig = taxonomy()[code]
        if sig["kind"] == "solution_present":
            presence = max(presence, sig["reduces"].get(svc, 0) * h.confidence)
    return clamp(1 - presence)


def _match_segment(text: str, section: str = "segments") -> str | None:
    t = norm_text(text)
    for seg, kws in cfg().get(section, {}).items():
        if any(k in t for k in kws):
            return seg
    return None


def canonical_segment(label: str | None) -> str | None:
    """Rotulo livre (ex.: 'Imobiliária') -> chave de segmento do scoring (ex.: 'imobiliario')."""
    if not label:
        return None
    key = norm_text(label).replace(" ", "_")
    if key in cfg()["segments"]:
        return key
    return _match_segment(label, "segment_labels") or _match_segment(label)


def detect_segment(text: str, org_segment: str | None = None) -> str:
    # Rotulo informado vence a inferencia por texto; rotulo desconhecido nao pode virar chave invalida.
    return canonical_segment(org_segment) or _match_segment(text) or "default"


def viability(facts: dict, text: str, segment: str, known: dict | None, org: dict | None = None) -> tuple[float, list[str]]:
    v, notes = cfg()["viability"], []
    score = v["base"]
    t = norm_text(text)
    region_terms = cfg()["region"]["terms"]
    loc = norm_text(" ".join(str(x) for x in [(org or {}).get("municipio") or "", (org or {}).get("uf") or ""]))
    if any(r in t or r in loc for r in region_terms):
        score += cfg()["region"]["bonus"]
        notes.append("regiao-alvo")
    emp = facts.get("employees_mentioned")
    lo, hi = v["employees_sweet_spot"]
    if emp is not None:
        if emp >= v["enterprise_employees"]:
            score -= v["enterprise_penalty"]; notes.append(f"grande porte ({emp} colaboradores citados)")
        elif lo <= emp <= hi:
            score += v["sweet_spot_bonus"]; notes.append(f"porte compativel ({emp} colaboradores citados)")
    elif any(term in t for term in v["enterprise_terms"]):
        score -= v["enterprise_penalty"]; notes.append("indicio de grande porte")
    porte = norm_text((org or {}).get("porte") or "")
    if porte in ("me", "epp", "micro empresa", "empresa de pequeno porte"):
        score += v["sweet_spot_bonus"] / 2; notes.append(f"porte cadastral {porte}")
    if segment in v["low_budget_segments"]:
        score -= v["low_budget_penalty"]; notes.append(f"segmento de baixo orcamento ({segment})")
    if known and known.get("category") == "no_budget":
        score -= v["known_no_budget_penalty"]; notes.append("lead anterior perdido por falta de orcamento")
    return round(clamp(score), 3), notes


def evidence_quality(hits: dict[str, SignalHit], pages: int, injection_flags: int) -> tuple[float, float]:
    e = cfg()["evidence"]
    verified = [x for h in hits.values() if h.kind != "context" for x in h.evidence if x.verified]
    distinct = len({x.signal_code for x in verified})
    confs = [x.confidence for x in verified] or [0.0]
    eq = 0.6 * min(1, distinct / e["saturation_signals"]) + 0.25 * min(1, pages / e["saturation_pages"]) + 0.15 * (sum(confs) / len(confs))
    mult = e["min_multiplier"] + (1 - e["min_multiplier"]) * eq
    if injection_flags:
        mult *= e["injection_penalty"]
    return round(eq, 3), round(mult, 3)


def compute_scores(hits, facts, text, pages, injection_flags, segment, known=None, org=None, calibration=None) -> dict:
    c = cfg()
    fits, why = service_fits(hits, calibration)
    order = sorted(SERVICES, key=lambda s: -fits[s])
    best, rest = order[0], order[1:3]
    secondary = sum(fits[s] for s in rest) / max(1, len(rest))
    via, via_notes = viability(facts, text, segment, known, org)
    gap = opportunity_gap(hits, best)
    eq, mult = evidence_quality(hits, pages, injection_flags)
    w = c["weights"]
    base = w["best_service_fit"] * fits[best] + w["secondary_fit"] * secondary + w["viability"] * via + w["opportunity_gap"] * gap
    collab, disciplines = collaboration_score(hits, fits, why)
    base = min(1.0, base + c["collaboration"]["max_bonus"] * collab)        # so soma: sem colaboracao o score nao muda
    learned_segment = calibration.for_segment(segment) if calibration else 1.0
    final = round(100 * base * mult * c.get("segment_multiplier", {}).get(segment, 1.0) * learned_segment, 1)
    b1 = round(100 * (0.6 * c["sector_prior"].get(segment, c["sector_prior"]["default"]) + 0.4 * via), 1)   # baseline setor/porte
    distinct = len({x.signal_code for h in hits.values() if h.kind == "need" for x in h.evidence if x.verified})
    return {"criteria_version": c["criteria_version"],
            "service_scores": {**{s: round(100 * fits[s] * mult, 1) for s in SERVICES}, COLLABORATION: round(100 * collab * mult, 1)},
            "service_fit_raw": {**fits, COLLABORATION: collab}, "best_service": best,
            "collaboration": collab, "collaboration_disciplines": disciplines,
            "multidisciplinary": collab >= c["collaboration"]["flag_threshold"],
            "signals_by_service": why, "viability": via, "viability_notes": via_notes, "opportunity_gap": round(gap, 3),
            "evidence_quality": eq, "evidence_multiplier": mult, "final": final, "baseline_b1": b1,
            "need_signals_verified": distinct, "segment": segment, "calibration_version": calibration.version if calibration and calibration.active else 0,
            "components": {"best_fit": round(fits[best], 3), "secondary_fit": round(secondary, 3), "viability": via, "gap": round(gap, 3)}}
