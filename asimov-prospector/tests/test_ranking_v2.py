"""Criterios v2 (portfolio ampliado): automacao/engenharia de dados, colaboracao entre areas, necessidade concreta x superficial.
Garante tambem que o que ja existia nao regrediu (score dos fixtures anteriores e historico preservado)."""
import json
from app.core.settings import ROOT, get_settings
from app.discovery import sources
from app.feedback.store import record_feedback
from app.intelligence.signals import detect_text_signals, taxonomy
from app.models.schemas import Candidate, Evidence, SignalHit
from app.pipeline import FixtureSource, ranking, run_pipeline
from app.scoring import score as sc

SITES = ROOT / "tests" / "fixtures" / "sites"
BASELINE_V1 = {"Alfa Manutencao Industrial": 85.3, "Norte Distribuidora de Bebidas": 67.8, "Rapido Sul Transportes": 54.6,
               "Clinica Vida Odontologia": 46.4, "Mega Industria Aeroespacial": 29.0, "Barbearia Sem Site": 27.2,
               "Helibras": 27.2, "Exemplo Consultoria Jr": 26.1, "Padaria Pao Quente": 21.9}     # medido antes da v2
NEW_CASES = [Candidate(name="Distribuidora Serra Azul", domain="dados-integra.example"),
             Candidate(name="Hidrosul Saneamento", domain="campo-multi.example"),
             Candidate(name="Projetar Engenharia", domain="engenharia-vitrine.example")]


def hit(code, conf=0.8):
    t = taxonomy()[code]
    e = Evidence(claim="c", type="fact", signal_code=code, source_url="https://x.com/", source_text="t", confidence=conf, verified=True)
    return SignalHit(code=code, kind=t["kind"], strength=t["strength"], confidence=conf, evidence=[e])


def hits(*codes):
    return {c: hit(c) for c in codes}


def _analyze(conn, candidates):
    run_pipeline(conn, candidates, FixtureSource(SITES), get_settings())
    return {r["name"]: r for r in ranking(conn)}


# --- novas necessidades sao reconhecidas -----------------------------------------------------------------------------
def test_new_patterns_detect_real_pains_not_mere_vocabulary():
    pains = detect_text_signals([{"url": "https://x.com/", "text": "A digitação manual dos pedidos gera retrabalho. Os dados ficam espalhados em sistemas diferentes."}])
    assert {"DATA_MANUAL_TRANSFER", "AUTOMATION_REPETITIVE", "DATA_SYSTEMS_FRAGMENTED"} <= set(pains)
    neutral = detect_text_signals([{"url": "https://x.com/", "text": "Nossa empresa usa tecnologia de ponta e integra pessoas e resultados com excelência."}])
    assert not neutral


def test_data_engineering_opportunity_ranks_with_automation_and_data(conn):
    row = _analyze(conn, NEW_CASES)["Distribuidora Serra Azul"]
    assert row["best_service"] in ("dados", "automacao")
    assert row["service_scores"]["dados"] > 40 and row["service_scores"]["automacao"] > 40


# --- colaboracao entre areas e eixo proprio --------------------------------------------------------------------------
def test_collaboration_is_its_own_axis_and_flags_multidisciplinary(conn):
    rows = _analyze(conn, NEW_CASES)
    multi = rows["Hidrosul Saneamento"]
    assert multi["service_scores"]["colaboracao"] >= 50
    assert ranking(conn, service="colaboracao")[0]["name"] == "Hidrosul Saneamento"
    result = json.loads(conn.execute("SELECT result FROM analysis WHERE org_id=? ORDER BY id DESC", (multi["org_id"],)).fetchone()[0])
    assert result["multidisciplinary"] and len(result["collaboration_disciplines"]) >= 2 and result["criteria_version"] == 2
    assert any("multidisciplinar" in c for c in multi["explanation"]["cautions"])


def test_one_signal_cannot_fake_multidisciplinary():
    # OPERATIONAL_FIELD alimenta aplicativo+software+dados, mas e UM sinal so: amplitude nao conta
    h = hits("OPERATIONAL_FIELD")
    fits, why = sc.service_fits(h)
    collab, _ = sc.collaboration_score(h, fits, why)
    assert collab == 0


def test_explicit_collaboration_signal_alone_is_not_enough_to_flag():
    h = hits("COLLABORATION_CROSS_AREA")
    fits, why = sc.service_fits(h)
    collab, _ = sc.collaboration_score(h, fits, why)
    assert 0 < collab < sc.cfg()["collaboration"]["flag_threshold"]


def test_collaboration_only_adds_to_score():
    base = {"OPERATIONAL_FIELD": hit("OPERATIONAL_FIELD"), "DATA_REPORTING": hit("DATA_REPORTING")}
    without = sc.compute_scores(base, {}, "texto", 3, 0, "default")
    with_collab = sc.compute_scores({**base, "COLLABORATION_CROSS_AREA": hit("COLLABORATION_CROSS_AREA")}, {}, "texto", 3, 0, "default")
    assert with_collab["final"] >= without["final"]
    assert with_collab["final"] - without["final"] <= 100 * sc.cfg()["collaboration"]["max_bonus"] + 0.1


# --- compatibilidade superficial x necessidade concreta ---------------------------------------------------------------
def test_contextual_activity_alone_is_capped_and_ranks_below_concrete_need(conn):
    rows = _analyze(conn, NEW_CASES)
    cap = sc.cfg()["evidence"]["contextual_fit_cap"]
    assert rows["Projetar Engenharia"]["service_scores"]["automacao"] <= 100 * cap
    assert rows["Projetar Engenharia"]["score"] < rows["Distribuidora Serra Azul"]["score"]


def test_contextual_cap_does_not_touch_concrete_signals():
    cap = sc.cfg()["evidence"]["contextual_fit_cap"]
    fits, _ = sc.service_fits(hits("ENGINEERING_TECHNICAL_DOCS"))
    assert fits["automacao"] <= cap
    fits, _ = sc.service_fits(hits("ENGINEERING_TECHNICAL_DOCS", "AUTOMATION_REPETITIVE"))
    assert fits["automacao"] > cap


# --- regressao: criterios antigos preservados --------------------------------------------------------------------------
def test_conventional_leads_keep_their_v1_scores(conn):
    run_pipeline(conn, sources.from_seed_csv(ROOT / "data" / "seeds_demo.csv"), FixtureSource(SITES), get_settings())
    got = {r["name"]: r["final"] for r in ranking(conn)}
    assert got.keys() == BASELINE_V1.keys()
    for name, v1 in BASELINE_V1.items():
        assert abs(got[name] - v1) <= 4.0, (name, v1, got[name])       # tolerancia: a v2 so ve automacao como servico extra
    assert max(got, key=got.get) == "Alfa Manutencao Industrial"


def test_legacy_analysis_and_feedback_survive(conn):
    run_pipeline(conn, sources.from_seed_csv(ROOT / "data" / "seeds_demo.csv"), FixtureSource(SITES), get_settings())
    row = ranking(conn)[0]
    record_feedback(conn, row["org_id"], row["analysis_id"], "boa")
    snapshot = lambda: json.dumps(dict(conn.execute("SELECT * FROM analysis WHERE id=?", (row["analysis_id"],)).fetchone()), default=str)
    legacy = snapshot()
    run_pipeline(conn, NEW_CASES, FixtureSource(SITES), get_settings())      # nova rodada sob v2
    assert snapshot() == legacy
    assert conn.execute("SELECT COUNT(*) FROM human_feedback").fetchone()[0] == 1


def test_old_results_without_criteria_version_are_distinguishable():
    legacy = {"final": 50.0}                          # analises anteriores nao tinham o campo
    assert legacy.get("criteria_version", 1) == 1 and sc.cfg()["criteria_version"] == 2
