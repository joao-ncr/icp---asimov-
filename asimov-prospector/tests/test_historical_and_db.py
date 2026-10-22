import sqlite3
import pandas as pd
import pytest
from app.core.settings import ROOT, get_settings
from app.database.db import connect, init_db, session
from app.discovery.historical import (HISTORICAL_XLSX, history_for_org, historical_candidates, import_historical,
                                      parse_historical, summarize_history)
from app.pipeline import FixtureSource, analyze_org, ranking, run_pipeline, start_run
from app.models.schemas import Candidate
from app.scoring.score import canonical_segment, detect_segment

SITES = ROOT / "tests" / "fixtures" / "sites"


def _xlsx(tmp_path):
    imp = pd.DataFrame([
        {"name": "Alfa Manutencao Industrial", "domain": "https://manutencao-sul.example/", "municipio": "Itajubá", "uf": "MG", "segment": "Serviço de manutenção de máquinas"},
        {"name": "Imobiliaria Sem Site", "domain": None, "municipio": "Itajubá", "uf": "MG", "segment": "Imobiliária"},
        {"name": "Loja Alerta", "domain": "https://alerta.example/", "municipio": "Itajubá", "uf": "MG", "segment": "Loja de marcenaria"},
    ])
    enriched = pd.DataFrame([
        {"ID": 1, "Lead": imp.name[0], "Telefone": "(35) 99999-0000", "CNPJ": "11.222.333/0001-81", "Capital social": "R$ 10.000,00",
         "Melhor oferta": "Sites", "Maturidade digital": "Média", "Decisor a abordar": "Fulano de Tal", "Alerta de cadastro": None},
        {"ID": 2, "Lead": imp.name[1], "Telefone": "(35) 98888-0000", "CNPJ": "Inconclusivo", "Capital social": "Inconclusivo",
         "Melhor oferta": "Ciência de dados", "Maturidade digital": "Baixa", "Decisor a abordar": "Beltrano", "Alerta de cadastro": None},
        {"ID": 3, "Lead": imp.name[2], "Telefone": "", "CNPJ": "99.888.777/0001-00", "Capital social": None,
         "Melhor oferta": "Mobile", "Maturidade digital": "Alta", "Decisor a abordar": None, "Alerta de cadastro": "ATENÇÃO: CNPJ de empresa diferente."},
    ])
    score = pd.DataFrame([{"ID": i, "Lead": n, "Prioridade revisada": "A", "Fit (30)": 30, "Dor (20)": 10, "Lead Score": 90 - i, "Tier": "A – atacar"}
                          for i, n in enumerate(imp.name, 1)])
    operation = pd.DataFrame([{"ID": i, "Lead": n, "Status comercial": "Não abordado", "Motivo de perda": None} for i, n in enumerate(imp.name, 1)])
    path = tmp_path / "historico.xlsx"
    with pd.ExcelWriter(path) as w:
        imp.to_excel(w, sheet_name="Importação Streamlit", index=False)
        enriched.to_excel(w, sheet_name="Leads enriquecidos", index=False)
        operation.to_excel(w, sheet_name="Operação Comercial", index=False)
        score.to_excel(w, sheet_name="Score detalhado", index=False)
    return path


def test_parse_maps_segment_service_and_drops_personal_data(tmp_path):
    leads = {l.candidate.name: l for l in parse_historical(_xlsx(tmp_path))}
    alfa, semsite, alerta = leads["Alfa Manutencao Industrial"], leads["Imobiliaria Sem Site"], leads["Loja Alerta"]
    assert alfa.candidate.domain == "manutencao-sul.example" and alfa.candidate.cnpj == "11222333000181"
    assert alfa.capital_social == 10000.0 and alfa.suggested_service == "site" and alfa.legacy_score == 89
    assert alfa.legacy_components == {"fit": 30.0, "dor": 10.0}
    assert semsite.candidate.domain is None and semsite.candidate.segment == "imobiliario" and semsite.suggested_service == "dados"
    assert alerta.cnpj_suspect and alerta.candidate.cnpj is None          # CNPJ em alerta nao serve de identidade
    assert alerta.candidate.segment == "industria"                         # marcenaria -> industria
    assert not any("decisor" in f or "telefone" in f for f in type(alfa).model_fields)


def test_import_is_idempotent_and_persists_history(conn, tmp_path):
    path = _xlsx(tmp_path)
    first = import_historical(conn, path)
    second = import_historical(conn, path)
    assert (first.total, first.with_site, first.without_site, first.new_orgs, first.cnpj_suspect) == (3, 2, 1, 3, 1)
    assert (second.new_orgs, second.already_known) == (0, 3)
    assert conn.execute("SELECT COUNT(*) FROM organization").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM lead_history").fetchone()[0] == 3
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(lead_history)")}
    assert not cols & {"phone", "telefone", "decision_maker", "decisor", "owners"}      # LGPD
    org = conn.execute("SELECT id FROM organization WHERE name='Alfa Manutencao Industrial'").fetchone()["id"]
    assert history_for_org(conn, org)["suggested_service"] == "site"
    assert [c.name for c in historical_candidates(conn)][0] == "Alfa Manutencao Industrial"


def test_model_receives_history_and_flags_divergence(conn, tmp_path):
    import_historical(conn, _xlsx(tmp_path))           # planilha sugere 'site'; sinais do fixture apontam outro servico
    rid = run_pipeline(conn, historical_candidates(conn)[:1], FixtureSource(SITES), get_settings())
    row = ranking(conn, rid)[0]
    hist = row["explanation"] and conn.execute("SELECT result FROM analysis WHERE run_id=?", (rid,)).fetchone()["result"]
    assert '"history"' in hist
    assert "agrees_with_model" in summarize_history(history_for_org(conn, row["org_id"]), row["best_service"])
    assert row["segment"] == "servicos_tecnicos"        # segmento canonico chegou ao scoring, nao o rotulo livre


def test_lead_without_site_keeps_history_context(conn, tmp_path):
    import_historical(conn, _xlsx(tmp_path))
    cand = next(c for c in historical_candidates(conn) if c.name == "Imobiliaria Sem Site")
    rid = run_pipeline(conn, [cand], FixtureSource(SITES), get_settings())
    res = conn.execute("SELECT status,reason,result FROM analysis WHERE run_id=?", (rid,)).fetchone()
    assert res["status"] == "inconclusive" and res["reason"].startswith("no_domain")
    assert '"suggested_service": "dados"' in res["result"]


def test_canonical_segment():
    assert canonical_segment("Imobiliária") == "imobiliario"
    assert canonical_segment("Escola de inglês") == "educacao"
    assert canonical_segment("industria") == "industria"
    assert canonical_segment("Moveleiro") == "industria"
    assert canonical_segment("algo desconhecido") is None
    assert detect_segment("texto sem pistas", "algo desconhecido") == "default"


@pytest.mark.skipif(not HISTORICAL_XLSX.exists(), reason="base historica local ausente")
def test_real_historical_base_parses_completely():
    leads = parse_historical()
    assert len(leads) >= 300
    assert sum(1 for l in leads if l.candidate.segment is None) / len(leads) < 0.1       # quase todo rotulo mapeia
    assert all(l.suggested_service for l in leads)


def test_short_lived_session_does_not_block_writers(tmp_path):
    db = tmp_path / "t.db"
    with session(db) as c:
        init_db(c)
    holder = connect(db)
    holder.execute("INSERT INTO search_run(started_at,config,metrics) VALUES('x','{}','{}')")    # tx de escrita aberta
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        c2 = sqlite3.connect(str(db), timeout=0.2)
        c2.execute("INSERT INTO search_run(started_at,config,metrics) VALUES('y','{}','{}')")
    holder.commit(); holder.close()
    with session(db) as c3:                              # apos o commit, escrita segue normalmente
        c3.execute("INSERT INTO search_run(started_at,config,metrics) VALUES('z','{}','{}')")
    with session(db) as c4:
        assert c4.execute("SELECT COUNT(*) FROM search_run").fetchone()[0] == 2


def test_analyze_org_does_not_hold_write_lock_during_crawl(tmp_path):
    """Regressao do 'database is locked': enquanto o crawl roda, outra conexao precisa conseguir escrever."""
    db = tmp_path / "t.db"
    with session(db) as c:
        init_db(c)
        from app.core.profile import seed_db
        seed_db(c)
        c.execute("INSERT INTO known_lead(name,name_norm,outcome,loss_category,is_person) VALUES('Alfa Manutencao Industrial','alfa manutencao industrial','lost','no_response',0)")
    outcomes = []

    class ProbeSource:
        def get_pages(self, domain, max_pages):
            other = sqlite3.connect(str(db), timeout=0.5)
            try:
                other.execute("INSERT INTO search_run(started_at,config,metrics) VALUES('probe','{}','{}')"); other.commit()
                outcomes.append("ok")
            except sqlite3.OperationalError as exc:
                outcomes.append(str(exc))
            finally:
                other.close()
            return [], "dns_failure"

    with session(db) as c:
        run_pipeline(c, [Candidate(name="Alfa Manutencao Industrial", domain="manutencao-sul.example")], ProbeSource(), get_settings())
    assert outcomes == ["ok"]


def test_platform_hosts_are_not_company_identity(conn):
    from app.core.utils import identity_domain
    from app.discovery.dedup import upsert_org
    assert identity_domain("https://www.instagram.com/loja") is None and identity_domain("wa.me/55") is None
    assert identity_domain("https://www.empresa.com.br/") == "empresa.com.br"
    a, new_a = upsert_org(conn, Candidate(name="Casa das Mangueiras", domain="https://instagram.com/casa"))
    b, new_b = upsert_org(conn, Candidate(name="Gabriel Leite Services", domain="https://instagram.com/gabriel"))
    assert a != b and new_a and new_b                   # antes: o 2o lead era fundido no 1o por compartilharem 'instagram.com'
    assert conn.execute("SELECT domain FROM organization WHERE id=?", (a,)).fetchone()["domain"] is None


def test_social_only_lead_is_inconclusive_without_crawl(conn):
    conn.execute("INSERT INTO organization(name,name_norm,domain) VALUES('Legado','legado','instagram.com')")    # dado antigo no banco
    class Boom:
        def get_pages(self, *a): raise AssertionError("nao deve fazer crawl de rede social")
    rid = start_run(conn, {})
    res = analyze_org(conn, 1, rid, Boom(), get_settings())
    assert res["status"] == "inconclusive" and res["reason"].startswith("no_domain")
