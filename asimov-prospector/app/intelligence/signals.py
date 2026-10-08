"""Deteccao de sinais: regras sobre texto (evidencia = frase literal) + checagens tecnicas do HTML."""
from __future__ import annotations
import re
from datetime import datetime
from functools import lru_cache
from app.core.settings import get_settings
from app.core.utils import load_yaml, norm_text
from app.extraction.text import sentences
from app.models.schemas import Evidence, SignalHit


@lru_cache
def taxonomy() -> dict[str, dict]:
    data = load_yaml(get_settings().config_dir / "signals.yaml")["signals"]
    for s in data:
        # fronteiras de palavra automaticas: evita 'reservas?' casar em 'reservados'
        s["_re"] = [re.compile(r"(?<![a-z0-9])(?:" + p + r")(?![a-z0-9])") for p in s.get("patterns", [])]
    return {s["code"]: s for s in data}


def _conf(strength: float) -> float:
    return round(min(0.95, 0.5 + 0.5 * strength), 2)


def detect_text_signals(pages: list[dict], max_evidence_per_signal: int = 2) -> dict[str, SignalHit]:
    """pages: [{url,text}]. Frases marcadas como injection ja devem ter sido removidas antes."""
    from app.crawler.extract import injection_count
    hits: dict[str, SignalHit] = {}
    for pg in pages:
        for sent in sentences(pg["text"]):
            if injection_count(sent):
                continue                    # conteudo com tentativa de injection NAO gera evidencia
            ns = norm_text(sent)
            for code, sig in taxonomy().items():
                if sig["source"] != "text":
                    continue
                for rx in sig["_re"]:
                    m = rx.search(ns)
                    if not m:
                        continue
                    if "min_number" in sig:
                        nums = [int(g) for g in m.groups() if g and g.isdigit()]
                        if nums and nums[0] < sig["min_number"]:
                            continue
                    h = hits.setdefault(code, SignalHit(code=code, kind=sig["kind"], strength=sig["strength"], confidence=_conf(sig["strength"])))
                    if len(h.evidence) < max_evidence_per_signal and all(e.source_text != sent for e in h.evidence):
                        h.evidence.append(Evidence(
                            claim=f"A pagina afirma/menciona: {sig['description']}", type="fact", signal_code=code,
                            source_url=pg["url"], source_text=sent, confidence=h.confidence))
                    break
    return hits


def detect_technical_signals(pages: list[dict], site_unreachable: bool, home_url: str | None) -> dict[str, SignalHit]:
    hits: dict[str, SignalHit] = {}

    def add(code: str, observation: str, url: str, conf: float):
        sig = taxonomy()[code]
        hits[code] = SignalHit(code=code, kind=sig["kind"], strength=sig["strength"], confidence=conf, evidence=[Evidence(
            claim=sig["description"], type="absence_inference", signal_code=code, source_kind="technical_check",
            source_url=url, source_text=observation, confidence=conf, verified=True)])

    if site_unreachable:
        add("DIGITAL_NO_SITE", "Dominio ausente ou inacessivel durante a coleta.", home_url or "", 0.5)
        return hits
    if not pages:
        return hits
    home = pages[0]
    f = home.get("features", {})
    year_now = datetime.now().year
    if not f.get("has_viewport"):
        add("DIGITAL_NO_VIEWPORT", "Pagina inicial sem meta viewport.", home["url"], 0.7)
    if not f.get("https"):
        add("DIGITAL_NO_HTTPS", "Pagina inicial servida sem HTTPS.", home["url"], 0.8)
    if not any(p.get("features", {}).get("has_form") or p.get("features", {}).get("has_whatsapp") for p in pages):
        add("DIGITAL_NO_CAPTURE", "Nenhum formulario nem link de WhatsApp nas paginas coletadas.", home["url"], 0.6)
    cy = f.get("copyright_year")
    if cy and year_now - cy >= 3:
        add("DIGITAL_STALE_COPYRIGHT", f"Rodape indica copyright {cy}.", home["url"], 0.6)
    return hits
