"""Base historica de prospeccao (planilha padronizada) -> banco, para o modelo consumir.

A planilha tem varias abas ligadas pelo ID do lead. Importamos o contexto util ao motor (CNPJ, segmento
canonico, oferta sugerida, alertas de cadastro, score legado) e descartamos dados pessoais (LGPD):
telefone, endereco, decisor e socios nunca entram no banco."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import pandas as pd
from app.core.settings import ROOT, get_settings
from app.core.utils import identity_domain, jdump, load_yaml, norm_text
from app.database.db import now
from app.discovery.dedup import upsert_org
from app.models.schemas import Candidate, HistoricalLead
from app.scoring.score import canonical_segment

HISTORICAL_XLSX = ROOT / "data" / "historico_leads_padronizado.xlsx"

SHEET_IMPORT = "importacao streamlit"
SHEET_ENRICHED = "leads enriquecidos"
SHEET_OPERATION = "operacao comercial"
SHEET_SCORE = "score detalhado"
REQUIRED_SHEETS = (SHEET_IMPORT, SHEET_ENRICHED)
SCORE_COMPONENT_PREFIXES = ("fit", "dor", "capacidade", "maturidade", "acesso", "urgencia", "qualidade")
UNKNOWN_MARKERS = {"", "inconclusivo", "nan", "none", "-", "n/a"}


@dataclass
class ImportReport:
    total: int = 0
    with_site: int = 0
    without_site: int = 0
    new_orgs: int = 0
    already_known: int = 0
    cnpj_suspect: int = 0
    unmapped_segments: list[str] = field(default_factory=list)


@lru_cache
def _rules() -> dict:
    return load_yaml(get_settings().config_dir / "historical.yaml")


def _clean(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return None if norm_text(text) in UNKNOWN_MARKERS else text


def _number(value) -> float | None:
    """'R$ 10.000,00' -> 10000.0; ausente/inconclusivo -> None."""
    text = _clean(value)
    if text is None:
        return None
    digits = re.sub(r"[^\d,]", "", text).replace(",", ".")
    try:
        return float(digits)
    except ValueError:
        return None


def _cnpj(value) -> str | None:
    digits = re.sub(r"\D", "", _clean(value) or "")
    return digits if len(digits) == 14 else None


def _sheets(path: Path) -> dict[str, pd.DataFrame]:
    """Abas indexadas por nome sem acento/caixa; colunas tambem normalizadas."""
    raw = pd.read_excel(path, sheet_name=None)
    sheets = {norm_text(name): df.rename(columns=lambda c: norm_text(str(c))) for name, df in raw.items()}
    missing = [s for s in REQUIRED_SHEETS if s not in sheets]
    if missing:
        raise ValueError(f"Planilha histórica sem as abas esperadas: {', '.join(missing)}")
    return sheets


def _by_id(sheets: dict[str, pd.DataFrame], name: str) -> dict[int, dict]:
    df = sheets.get(name)
    if df is None or "id" not in df.columns:
        return {}
    return {int(r["id"]): r for r in df.to_dict("records") if pd.notna(r["id"])}


def _column(row: dict, prefix: str):
    return next((v for k, v in row.items() if k.startswith(prefix)), None)


def _suggested_service(best_offer: str | None) -> str | None:
    return _rules()["offer_to_service"].get(norm_text(best_offer)) if best_offer else None


def _is_cnpj_suspect(alert: str | None) -> bool:
    return bool(alert) and norm_text(alert).startswith(tuple(_rules()["cnpj_suspect_prefixes"]))


def parse_historical(path: Path = HISTORICAL_XLSX) -> list[HistoricalLead]:
    sheets = _sheets(path)
    enriched = _by_id(sheets, SHEET_ENRICHED)
    operation, score = _by_id(sheets, SHEET_OPERATION), _by_id(sheets, SHEET_SCORE)
    id_by_name = {str(r.get("lead", "")).strip(): i for i, r in enriched.items()}

    leads = []
    for r in sheets[SHEET_IMPORT].to_dict("records"):
        name = (_clean(r.get("name")) or "").strip()
        if not name:
            continue
        lead_id = id_by_name.get(name)
        e, op, sc = enriched.get(lead_id, {}), operation.get(lead_id, {}), score.get(lead_id, {})
        alert = _clean(e.get("alerta de cadastro"))
        suspect = _is_cnpj_suspect(alert)
        best_offer = _clean(e.get("melhor oferta"))
        label = _clean(r.get("segment"))
        leads.append(HistoricalLead(
            source_id=lead_id,
            candidate=Candidate(
                name=name, domain=identity_domain(_clean(r.get("domain"))), municipio=_clean(r.get("municipio")), uf=_clean(r.get("uf")),
                segment=canonical_segment(label), cnpj=None if suspect else _cnpj(e.get("cnpj")), source="historical_base"),
            segment_label=label,
            capital_social=_number(e.get("capital social")),
            digital_maturity=_clean(e.get("maturidade digital")),
            best_offer=best_offer, suggested_service=_suggested_service(best_offer),
            identity_confidence=_clean(e.get("confiabilidade da identificacao")),
            registration_alert=alert, cnpj_suspect=suspect,
            ticket_filter=_clean(_column(e, "filtro ticket")), ticket_reason=_clean(e.get("motivo do filtro")),
            priority=_clean(sc.get("prioridade revisada") or op.get("prioridade")), tier=_clean(sc.get("tier") or op.get("tier")),
            legacy_score=_number(sc.get("lead score") if sc else op.get("score")),
            legacy_components={k.split(" ")[0]: float(v) for k, v in sc.items()
                               if k.startswith(SCORE_COMPONENT_PREFIXES) and isinstance(v, (int, float)) and pd.notna(v)},
            commercial_status=_clean(op.get("status comercial")), loss_reason=_clean(op.get("motivo de perda")),
        ))
    return leads


def import_historical(conn, path: Path = HISTORICAL_XLSX) -> ImportReport:
    """Idempotente: reexecutar atualiza o contexto sem duplicar organizacoes (dedup por dominio/CNPJ/nome)."""
    report = ImportReport()
    unmapped = set()
    for lead in parse_historical(path):
        org_id, is_new = upsert_org(conn, lead.candidate)
        _upsert_history(conn, org_id, lead)
        report.total += 1
        report.with_site += bool(lead.candidate.domain)
        report.without_site += not lead.candidate.domain
        report.new_orgs += is_new
        report.already_known += not is_new
        report.cnpj_suspect += lead.cnpj_suspect
        if lead.segment_label and not lead.candidate.segment:
            unmapped.add(lead.segment_label)
    report.unmapped_segments = sorted(unmapped)
    conn.commit()
    return report


def _upsert_history(conn, org_id: int, h: HistoricalLead) -> None:
    conn.execute(
        """INSERT INTO lead_history(org_id,source_id,segment_label,capital_social,digital_maturity,best_offer,suggested_service,
             identity_confidence,registration_alert,cnpj_suspect,ticket_filter,ticket_reason,priority,tier,legacy_score,
             legacy_components,commercial_status,loss_reason,imported_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(org_id) DO UPDATE SET source_id=excluded.source_id, segment_label=excluded.segment_label,
             capital_social=excluded.capital_social, digital_maturity=excluded.digital_maturity, best_offer=excluded.best_offer,
             suggested_service=excluded.suggested_service, identity_confidence=excluded.identity_confidence,
             registration_alert=excluded.registration_alert, cnpj_suspect=excluded.cnpj_suspect, ticket_filter=excluded.ticket_filter,
             ticket_reason=excluded.ticket_reason, priority=excluded.priority, tier=excluded.tier, legacy_score=excluded.legacy_score,
             legacy_components=excluded.legacy_components, commercial_status=excluded.commercial_status,
             loss_reason=excluded.loss_reason, imported_at=excluded.imported_at""",
        (org_id, h.source_id, h.segment_label, h.capital_social, h.digital_maturity, h.best_offer, h.suggested_service,
         h.identity_confidence, h.registration_alert, int(h.cnpj_suspect), h.ticket_filter, h.ticket_reason, h.priority, h.tier,
         h.legacy_score, jdump(h.legacy_components), h.commercial_status, h.loss_reason, now()))


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


def historical_candidates(conn) -> list[Candidate]:
    """Candidatos da base ja importada, na ordem original da planilha (dados canonicos vindos do banco)."""
    rows = conn.execute(
        """SELECT o.name, o.domain, o.cnpj, o.municipio, o.uf, o.segment FROM lead_history h
           JOIN organization o ON o.id=h.org_id ORDER BY h.source_id, h.id""")
    return [Candidate(name=r["name"], domain=r["domain"], cnpj=r["cnpj"], municipio=r["municipio"], uf=r["uf"],
                      segment=r["segment"], source="historical_base") for r in rows]
