"""Contexto comercial legado (lead_history): leitura/resumo direto e sua integracao com o resultado da analise.
A importacao em lote a partir da planilha padronizada foi descontinuada (Ploomes e geracao por CNPJ assumiram);
estes testes cobrem o que continua em uso real (app/discovery/historical.py, app/pipeline.py) sem depender dela."""
import json
from app.core.settings import ROOT, get_settings
from app.database.db import now
from app.discovery.dedup import upsert_org
from app.discovery.historical import history_for_org, summarize_history
from app.models.schemas import Candidate
from app.pipeline import FixtureSource, run_pipeline

SITES = ROOT / "tests" / "fixtures" / "sites"


def _with_history(conn, **fields) -> int:
    org_id, _ = upsert_org(conn, Candidate(name="Alfa Manutencao Industrial", domain="manutencao-sul.example"))
    cols, placeholders = ", ".join(fields), ", ".join("?" * len(fields))
    conn.execute(f"INSERT INTO lead_history(org_id,{cols},imported_at) VALUES(?,{placeholders},?)",
                 (org_id, *fields.values(), now()))
    conn.commit()
    return org_id


def test_history_for_org_and_summary_agree_with_model(conn):
    org_id = _with_history(conn, best_offer="Sites", suggested_service="site", tier="A")
    history = history_for_org(conn, org_id)
    assert history["suggested_service"] == "site" and history["best_offer"] == "Sites"
    assert summarize_history(history, "site")["agrees_with_model"] is True
    assert summarize_history(history, "dados")["agrees_with_model"] is False
    assert summarize_history(None) is None


def test_analysis_result_embeds_the_history_summary(conn):
    _with_history(conn, best_offer="Sites", suggested_service="site")
    rid = run_pipeline(conn, [Candidate(name="Alfa Manutencao Industrial", domain="manutencao-sul.example")],
                       FixtureSource(SITES), get_settings())
    row = conn.execute("SELECT status, result FROM analysis WHERE run_id=?", (rid,)).fetchone()
    assert row["status"] == "ranked"
    assert json.loads(row["result"])["history"]["suggested_service"] == "site"
