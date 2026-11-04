"""Acesso a dados da interface. Cada chamada usa uma conexao de vida curta (`session`); nada de conexao global."""
from __future__ import annotations
import pandas as pd
import streamlit as st
from app.core.settings import get_settings
from app.core.utils import jdump, norm_domain
from app.database.db import now, session
from app.database.run_lock import current_holder, force_release
from app.discovery import generation as discovery_generation
from app.discovery import review as discovery_review
from app.discovery.dedup import upsert_org
from app.discovery.historical import history_for_org
from app.feedback.store import latest_feedback, learning_status, record_feedback
from app.integrations.ploomes import repository as ploomes_repo
from app.integrations.ploomes.sync import SyncReport, client_from_settings, run_sync
from app.models.schemas import Candidate
from app.pipeline import WebPageSource, analyze_org, reapply_learning, run_pipeline, start_run
from app.ranking import data_version, ranking
from app.database.run_lock import exclusive_run


# --- leitura -----------------------------------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _ranking_cached(version: tuple, service: str | None) -> list[dict]:
    with session() as conn:
        return ranking(conn, service=service)


def ranking_rows(service: str | None = None) -> list[dict]:
    """Ranking completo; recalculado so quando ha analise, avaliacao ou calibracao nova (ver `data_version`)."""
    with session() as conn:
        version = data_version(conn)
    return _ranking_cached(version, service)


def learning() -> dict:
    with session() as conn:
        return learning_status(conn)


def evidence_for(analysis_id: int) -> pd.DataFrame:
    with session() as conn:
        return pd.DataFrame([dict(r) for r in conn.execute(
            "SELECT signal_code,claim,source_text,source_url,confidence FROM evidence WHERE analysis_id=? AND verified=1 ORDER BY confidence DESC",
            (analysis_id,))])


def history_for(org_id: int) -> dict | None:
    with session() as conn:
        return history_for_org(conn, org_id)


def evaluation_for(org_id: int) -> dict | None:
    with session() as conn:
        return latest_feedback(conn, org_id)


def running_now() -> dict | None:
    with session() as conn:
        return current_holder(conn)


def ploomes_configured() -> bool:
    return bool(get_settings().ploomes_user_key)


def ploomes_overview() -> dict:
    """Resumo das empresas vindas do CRM e a última sincronização (para a tela de análise)."""
    with session() as conn:
        return {"summary": ploomes_repo.summary(conn), "last_sync": ploomes_repo.last_sync(conn)}


def ploomes_pending(limit: int) -> list[Candidate]:
    with session() as conn:
        return ploomes_repo.pending_candidates(conn, limit)


def discovery_configured() -> bool:
    return bool(discovery_generation.rules().get("icps"))


def discovery_overview() -> dict:
    """Resumo da geração de leads novos (CNPJ aberto) para a tela de análise: última geração e fila de aprovação."""
    with session() as conn:
        return {"last": discovery_generation.last_generation(conn), "pending": discovery_review.pending_candidates(conn)}


def run_discovery_generation(uploaded_file, filename: str, triggered_by: str) -> discovery_generation.GenerationReport:
    """Lê o CSV de dados abertos de CNPJ enviado pelo admin e cria candidatos pendentes de aprovação (sem rede)."""
    with session() as conn:
        return discovery_generation.run_generation(conn, uploaded_file, filename, triggered_by)


def decide_discovery(candidate_ids: list[int], approve: bool, decided_by: str) -> list[Candidate]:
    """Aprova (gera organização) ou rejeita candidatos pendentes; devolve os aprovados para a análise em lote."""
    with session() as conn:
        return discovery_review.decide(conn, candidate_ids, approve, decided_by)


# --- escrita -----------------------------------------------------------------------------------------------------
def save_evaluation(org_id: int, analysis_id: int, level: str, reason: str, author: str) -> None:
    with session() as conn:
        record_feedback(conn, org_id, analysis_id, level, reason, author)


def release_lock() -> None:
    with session() as conn:
        force_release(conn)


def sync_ploomes(triggered_by: str) -> SyncReport:
    """Lê o Ploomes (somente GET) e atualiza o banco local. Levanta RunInProgress, SyncTooSoon ou PloomesError."""
    s = get_settings()
    with session() as conn, client_from_settings(s) as client:
        return run_sync(conn, client, triggered_by)


def run_analysis(candidates: list[Candidate], run_cfg: dict, callback) -> int:
    """Rodada com conexao propria (nao divide transacao com as leituras da tela). Levanta RunInProgress se ocupada."""
    from app.crawler.fetcher import Fetcher
    s = get_settings()
    with session() as conn:
        return run_pipeline(conn, candidates, WebPageSource(Fetcher(s), s), s, run_cfg, callback)


def analyze_single(name: str, url: str) -> dict:
    from app.crawler.fetcher import Fetcher
    s, domain = get_settings(), norm_domain(url)
    with session() as conn, exclusive_run(conn, "analise_unica"):
        run_id = start_run(conn, {"mode": "operation_single", "url": url})
        org_id, _ = upsert_org(conn, Candidate(name=name or domain, domain=domain, source="ui_operation"))
        metrics: dict = {}
        result = analyze_org(conn, org_id, run_id, WebPageSource(Fetcher(s), s), s, None, metrics)
        conn.execute("UPDATE search_run SET finished_at=?, metrics=? WHERE id=?", (now(), jdump(metrics), run_id))
        return result


def reapply(callback) -> int:
    with session() as conn:
        return reapply_learning(conn, get_settings(), callback)
