"""Contexto comercial legado (lead_history) que acompanha a analise: mapeamento oferta->servico, deteccao de
CNPJ suspeito e leitura/resumo do que ja foi importado (pelo Ploomes ou por uma rodada anterior). A importacao em
lote a partir da planilha padronizada foi descontinuada (substituida pelo Ploomes e pela geracao de leads por
CNPJ aberto); o schema de `lead_history` e os dados ja importados continuam intactos."""
from __future__ import annotations
from functools import lru_cache
from app.core.settings import get_settings
from app.core.utils import load_yaml, norm_text


@lru_cache
def _rules() -> dict:
    return load_yaml(get_settings().config_dir / "historical.yaml")


def suggested_service(best_offer: str | None) -> str | None:
    return _rules()["offer_to_service"].get(norm_text(best_offer)) if best_offer else None


def is_cnpj_suspect(alert: str | None) -> bool:
    return bool(alert) and norm_text(alert).startswith(tuple(_rules()["cnpj_suspect_prefixes"]))


def history_for_org(conn, org_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM lead_history WHERE org_id=?", (org_id,)).fetchone()
    return dict(row) if row else None


def summarize_history(history: dict | None, best_service: str | None = None) -> dict | None:
    """Recorte do historico que acompanha a analise (auditavel em analysis.result).
    `agrees_with_model` compara a oferta sugerida na planilha com o servico que o motor encontrou."""
    if not history:
        return None
    suggested = history.get("suggested_service")
    return {"suggested_service": suggested, "best_offer": history.get("best_offer"), "tier": history.get("tier"),
            "legacy_score": history.get("legacy_score"), "registration_alert": history.get("registration_alert"),
            "identity_confidence": history.get("identity_confidence"),
            "agrees_with_model": (suggested == best_service) if suggested and best_service else None}
