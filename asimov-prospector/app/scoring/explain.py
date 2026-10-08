"""Explicacao comercial montada por TEMPLATE a partir de campos estruturados: fato -> inferencia -> hipotese.
Linguagem sempre condicional; ausencia nunca e apresentada como fato."""
from __future__ import annotations
from app.intelligence.signals import taxonomy

SERVICE_NAMES = {"site": "Sites", "aplicativo": "Aplicativos", "software": "Softwares personalizados", "dados": "Analise de dados"}


def build_explanation(result: dict, hits: dict, service_defs: dict, similar_cases: list[tuple[str, float]]) -> dict:
    svc = result["best_service"]
    codes = result["signals_by_service"].get(svc, [])[:4]
    facts, inferences, absences = [], [], []
    for c in codes:
        h = hits[c]
        for e in h.evidence[:1]:
            line = f'"{e.source_text}" ({e.source_url})'
            (absences if e.type == "absence_inference" else facts).append(line)
        inferences.append(taxonomy()[c]["interpretation"])
    sig_txt = ", ".join(taxonomy()[c]["description"].rstrip(".").lower() for c in codes) or "sinais fracos"
    hyp = service_defs.get(svc, {}).get("hypothesis_template", "Pode haver oportunidade para {signals}.").format(signals=sig_txt)
    present = [taxonomy()[c]["description"] for c, h in hits.items() if taxonomy()[c]["kind"] == "solution_present"]
    cautions = []
    if present:
        cautions.append("Ja ha indicio de solucao existente: " + "; ".join(present).lower())
    if result["viability_notes"]:
        cautions.append("Viabilidade: " + "; ".join(result["viability_notes"]))
    if result["evidence_multiplier"] < 0.75:
        cautions.append("Evidencia limitada: tratar como pista a validar, nao como conclusao.")
    text = (f"Principal oportunidade: {SERVICE_NAMES[svc]} ({result['service_scores'][svc]:.0f}/100). "
            + (f"Fatos observados: {' | '.join(facts)}. " if facts else "")
            + (f"Observacoes tecnicas (inferencia por ausencia, a confirmar): {' | '.join(absences)}. " if absences else "")
            + f"Interpretacao possivel: {' '.join(dict.fromkeys(inferences))} "
            + f"Hipotese comercial: {hyp}")
    return {"best_service": svc, "facts": facts, "absences": absences, "inferences": list(dict.fromkeys(inferences)),
            "hypothesis": hyp, "cautions": cautions, "similar_cases": similar_cases, "text": text}
