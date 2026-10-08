import csv, json
from pathlib import Path
from app.core.settings import ROOT, get_settings
from app.core.utils import norm_name
from app.discovery import sources
from app.pipeline import FixtureSource, ranking, run_pipeline
from app.models.schemas import Candidate


def _load_leads(conn):
    for r in csv.DictReader(open(ROOT / "data" / "leads_seed.csv", encoding="utf-8")):
        conn.execute("INSERT INTO known_lead(name,name_norm,outcome,value,funnel,loss_reason,loss_category,segment,is_person) VALUES(?,?,?,?,?,?,?,?,?)",
                     (r["name"], norm_name(r["name"]), r["outcome"], float(r["value"] or 0), r["funnel"], r["loss_reason"] or None, r["loss_category"] or None, r["segment"], int(r["is_person"])))


def _run(conn):
    _load_leads(conn)
    s = get_settings()
    cands = sources.from_seed_csv(ROOT / "data" / "seeds_demo.csv")
    rid = run_pipeline(conn, cands, FixtureSource(ROOT / "tests" / "fixtures" / "sites"), s)
    return rid, {r["name"]: r for r in ranking(conn, rid)}


def test_e2e_asimov_to_ranking(conn):
    rid, rk = _run(conn)
    rows = ranking(conn, rid)
    assert rows[0]["name"] == "Alfa Manutencao Industrial"            # dor clara + regiao + porte compativel
    assert "WebFabrica Software House" not in rk                       # concorrente excluido
    assert "Helibras" not in rk                                        # lead anterior: sem dor solucionavel
    st = {r["name"]: r["status"] for r in conn.execute("SELECT name,status FROM organization")}
    assert st["WebFabrica Software House"] == "excluded" and st["Helibras"] == "excluded"
    assert rk["Mega Industria Aeroespacial"]["final"] < rk["Norte Distribuidora de Bebidas"]["final"]
    assert rk["Exemplo Consultoria Jr"]["final"] < rk["Rapido Sul Transportes"]["final"]


def test_every_ranked_evidence_is_verified_and_typed(conn):
    _run(conn)
    ev = conn.execute("SELECT * FROM evidence").fetchall()
    assert ev and all(e["verified"] == 1 for e in ev)
    assert {e["type"] for e in ev} <= {"fact", "absence_inference"}
    for e in ev:                     # citacao de texto precisa existir na pagina armazenada
        if e["source_kind"] == "text_quote":
            txt = conn.execute("SELECT text FROM page WHERE url=?", (e["source_url"],)).fetchone()["text"]
            assert " ".join(e["source_text"].lower().split()) in " ".join(txt.lower().split())


def test_prompt_injection_page_gets_no_inflated_score(conn):
    _, rk = _run(conn)
    p = rk["Padaria Pao Quente"]
    assert p["final"] < 35 and p["service_scores"]["aplicativo"] < 20 and p["service_scores"]["software"] < 20
    ev = conn.execute("SELECT source_text FROM evidence e JOIN organization o ON o.id=e.org_id WHERE o.name='Padaria Pao Quente'").fetchall()
    assert not any("ignore" in e["source_text"].lower() for e in ev)


def test_unreachable_site_is_absence_inference_not_fact(conn):
    _run(conn)
    e = conn.execute("SELECT e.* FROM evidence e JOIN organization o ON o.id=e.org_id WHERE o.name='Barbearia Sem Site'").fetchall()
    assert e and e[0]["type"] == "absence_inference" and e[0]["confidence"] <= 0.5


def test_explanation_separates_fact_inference_hypothesis(conn):
    rid, _ = _run(conn)
    ex = ranking(conn, rid)[0]["explanation"]
    assert ex["facts"] and ex["inferences"] and ex["hypothesis"]
    assert "Hipotese comercial" in ex["text"] and "Fatos observados" in ex["text"]


def test_dns_failure_through_web_source_is_no_site_not_blocked(conn):
    from app.pipeline import WebPageSource, analyze_org, start_run
    from app.crawler.fetcher import FetchResult
    from app.discovery.dedup import upsert_org

    class F:
        stats = {}
        def fetch(self, url): return FetchResult(url, error="unsafe:dns_failure:naoexiste.example")
    s = get_settings()
    oid, _ = upsert_org(conn, Candidate(name="Loja Fantasma", domain="naoexiste.example"))
    res = analyze_org(conn, oid, start_run(conn, {}), WebPageSource(F(), s), s)
    assert res["status"] == "ranked"
    assert conn.execute("SELECT signal_code FROM evidence WHERE org_id=?", (oid,)).fetchone()[0] == "DIGITAL_NO_SITE"


def test_blocked_site_is_not_treated_as_no_site(conn):
    from app.pipeline import WebPageSource, analyze_org, start_run
    from app.crawler.fetcher import FetchResult
    from app.discovery.dedup import upsert_org

    class F:
        stats = {}
        def fetch(self, url): return FetchResult(url, error="blocked_by_robots")
    s = get_settings()
    oid, _ = upsert_org(conn, Candidate(name="Empresa Bloqueada", domain="bloqueada.example"))
    assert analyze_org(conn, oid, start_run(conn, {}), WebPageSource(F(), s), s)["status"] == "blocked"
