"""Scoring 100% deterministico (nenhuma chamada a LLM). Pesos em app/config/scoring.yaml."""
from __future__ import annotations
from functools import lru_cache
from app.core.settings import get_settings
from app.core.utils import clamp, load_yaml, norm_text, sha
from app.intelligence.signals import taxonomy
from app.models.schemas import SignalHit

SERVICES = ["site", "aplicativo", "software", "dados"]


@lru_cache
def cfg() -> dict:
    return load_yaml(get_settings().config_dir / "scoring.yaml")


def config_hash() -> str:
    return sha(open(get_settings().config_dir / "scoring.yaml", encoding="utf-8").read())[:12]


def service_fits(hits: dict[str, SignalHit]) -> tuple[dict[str, float], dict[str, list[str]]]:
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
                contribs.append((code, w * h.strength * h.confidence))
        p = 1.0
        for _, x in contribs:
            p *= 1 - x
        fit = 1 - p
        if contribs and len(contribs) < 2 and max(x for _, x in contribs) < c["weak_signal_threshold"] * 0.8:
            fit = min(fit, c["weak_fit_cap"])
        fits[svc] = round(clamp(fit), 4)
        why[svc] = [code for code, _ in sorted(contribs, key=lambda t: -t[1])]
    return fits, why


def opportunity_gap(hits: dict[str, SignalHit], svc: str) -> float:
    presence = 0.0
    for code, h in hits.items():
        sig = taxonomy()[code]
        if sig["kind"] == "solution_present":
            presence = max(presence, sig["reduces"].get(svc, 0) * h.confidence)
    return clamp(1 - presence)


def detect_segment(text: str, org_segment: str | None = None) -> str:
    if org_segment:
        return org_segment
    t = norm_text(text)
    for seg, kws in cfg()["segments"].items():
        if any(k in t for k in kws):
            return seg
    return "default"


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


def compute_scores(hits, facts, text, pages, injection_flags, segment, known=None, org=None) -> dict:
    c = cfg()
    fits, why = service_fits(hits)
    order = sorted(SERVICES, key=lambda s: -fits[s])
    best, rest = order[0], order[1:3]
    secondary = sum(fits[s] for s in rest) / max(1, len(rest))
    via, via_notes = viability(facts, text, segment, known, org)
    gap = opportunity_gap(hits, best)
    eq, mult = evidence_quality(hits, pages, injection_flags)
    w = c["weights"]
    base = w["best_service_fit"] * fits[best] + w["secondary_fit"] * secondary + w["viability"] * via + w["opportunity_gap"] * gap
    final = round(100 * base * mult * c.get("segment_multiplier", {}).get(segment, 1.0), 1)
    b1 = round(100 * (0.6 * c["sector_prior"].get(segment, c["sector_prior"]["default"]) + 0.4 * via), 1)   # baseline setor/porte
    distinct = len({x.signal_code for h in hits.values() if h.kind == "need" for x in h.evidence if x.verified})
    return {"service_scores": {s: round(100 * fits[s] * mult, 1) for s in SERVICES}, "service_fit_raw": fits, "best_service": best,
            "signals_by_service": why, "viability": via, "viability_notes": via_notes, "opportunity_gap": round(gap, 3),
            "evidence_quality": eq, "evidence_multiplier": mult, "final": final, "baseline_b1": b1,
            "need_signals_verified": distinct, "segment": segment,
            "components": {"best_fit": round(fits[best], 3), "secondary_fit": round(secondary, 3), "viability": via, "gap": round(gap, 3)}}
