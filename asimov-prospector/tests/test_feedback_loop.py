"""Ciclo principal: ranking -> avaliacao do time (3 niveis) -> calibracao -> ranking reaplicado; mais rodada unica e indices."""
import random
import pytest
from app.core.settings import ROOT, get_settings
from app.core.utils import norm_name
from app.database.db import connect, init_db, now, session
from app.database.run_lock import RunInProgress, current_holder, exclusive_run, force_release
from app.discovery import sources
from app.discovery.dedup import OrgIndex, upsert_org
from app.feedback.store import labeled_leads, learning_status, record_feedback, refresh_calibration
from app.models.schemas import Candidate
from app.pipeline import FixtureSource, StoredPageSource, analyze_org, ranking, reapply_learning, run_pipeline, start_run
from app.scoring import antiicp
from app.scoring.calibration import LabeledLead, fit_calibration
from app.scoring.score import cfg

SITES = ROOT / "tests" / "fixtures" / "sites"


def _demo_run(conn):
    return run_pipeline(conn, sources.from_seed_csv(ROOT / "data" / "seeds_demo.csv"), FixtureSource(SITES), get_settings())


def _evaluate_all(conn, levels):
    rows = ranking(conn)
    for row, level in zip(rows, levels * len(rows)):
        record_feedback(conn, row["org_id"], row["analysis_id"], level)
    return rows


@pytest.fixture
def small_thresholds(monkeypatch):
    c = cfg()["calibration"]
    for key, value in {"min_labels": 6, "min_per_class": 2, "min_group_n": 2, "shrinkage_k": 2}.items():
        monkeypatch.setitem(c, key, value)


# --- feedback em 3 niveis -----------------------------------------------------------------------------------------
def test_feedback_accepts_only_three_levels(conn):
    _demo_run(conn)
    row = ranking(conn)[0]
    assert record_feedback(conn, row["org_id"], row["analysis_id"], "boa", " ótima ", " Ana ")
    with pytest.raises(ValueError):
        record_feedback(conn, row["org_id"], row["analysis_id"], "excelente")
    assert ranking(conn)[0]["feedback"] == "boa"
    saved = conn.execute("SELECT reason, author FROM human_feedback").fetchone()
    assert (saved["reason"], saved["author"]) == ("ótima", "Ana")


# --- calibracao ---------------------------------------------------------------------------------------------------
def test_calibration_inactive_below_threshold():
    samples = [LabeledLead(1.0, frozenset({"A"}), "x")] * 5
    cal = fit_calibration(samples)
    assert not cal.active and cal.for_signal("A") == 1.0 and cal.for_segment("x") == 1.0


def test_calibration_learns_direction_and_stays_bounded(small_thresholds):
    good = [LabeledLead(1.0, frozenset({"GOOD"}), "ind") for _ in range(10)]
    bad = [LabeledLead(0.0, frozenset({"BAD"}), "loja") for _ in range(10)]
    cal = fit_calibration(good + bad)
    lo, hi = cfg()["calibration"]["bounds"]
    assert cal.active and cal.for_signal("GOOD") > 1.0 > cal.for_signal("BAD")
    assert all(lo <= m <= hi for m in [*cal.signal_mult.values(), *cal.segment_mult.values()])
    assert cal.for_segment("ind") > 1.0 > cal.for_segment("loja")


def test_calibration_needs_both_classes(small_thresholds):
    assert not fit_calibration([LabeledLead(1.0, frozenset(), "x")] * 20).active


def test_snapshot_is_idempotent_and_versioned(conn, small_thresholds):
    _demo_run(conn)
    _evaluate_all(conn, ["boa", "ruim", "neutra"])
    first = refresh_calibration(conn)
    assert refresh_calibration(conn).version == first.version            # sem feedback novo, mesmo snapshot
    row = ranking(conn)[0]
    record_feedback(conn, row["org_id"], row["analysis_id"], "ruim")      # a avaliacao mais recente substitui a anterior
    assert refresh_calibration(conn).version == first.version + 1
    samples, _ = labeled_leads(conn)
    assert len(samples) == len({r["org_id"] for r in conn.execute("SELECT org_id FROM human_feedback")})


def test_learning_is_applied_by_new_runs_and_reapplied_without_network(conn, small_thresholds):
    _demo_run(conn)
    before = {r["name"]: r["final"] for r in ranking(conn)}
    _evaluate_all(conn, ["boa", "ruim", "boa", "ruim", "neutra"])
    status = learning_status(conn)
    assert status["ready"] and status["needs_reapply"] and status["active_version"] > status["applied_version"]
    rid = reapply_learning(conn, get_settings())                          # StoredPageSource: nenhuma rede
    after = ranking(conn, rid)
    assert after and all(r["explanation"] for r in after)
    stamp = conn.execute("SELECT weights_hash, result FROM analysis WHERE run_id=? AND status='ranked' LIMIT 1", (rid,)).fetchone()
    assert "+cal" in stamp["weights_hash"] and f'"calibration_version": {status["active_version"]}' in stamp["result"]
    assert learning_status(conn)["needs_reapply"] is False
    assert any(abs(before[r["name"]] - r["final"]) > 0 for r in after if r["name"] in before)        # o ranking mudou de fato


def test_stored_page_source_reads_what_the_crawl_saved(conn):
    _demo_run(conn)
    pages, err = StoredPageSource(conn).get_pages("manutencao-sul.example", 8)
    assert pages and err is None and isinstance(pages[0]["features"], dict)
    assert StoredPageSource(conn).get_pages("nunca-visto.example", 8) == ([], "dns_failure")


# --- rodada unica ---------------------------------------------------------------------------------------------------
def test_second_run_is_blocked_until_first_finishes(tmp_path):
    db = tmp_path / "t.db"
    with session(db) as c:
        init_db(c)
    first, second = connect(db), connect(db)
    with exclusive_run(first, "rodada A"):
        assert current_holder(second)["label"] == "rodada A"
        with pytest.raises(RunInProgress, match="rodada A"):
            with exclusive_run(second, "rodada B"):
                pytest.fail("a segunda rodada nao pode entrar")
    assert current_holder(second) is None
    with exclusive_run(second, "rodada B"):          # liberada ao fim da primeira
        pass
    first.close(); second.close()


def test_stale_lock_expires_and_can_be_forced(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    with session(db) as c:
        init_db(c)
    a, b = connect(db), connect(db)
    a.execute("INSERT INTO run_lock VALUES(1,'dono-morto','antiga','2020-01-01T00:00:00+00:00','2020-01-01T00:00:00+00:00')"); a.commit()
    with exclusive_run(b, "nova"):                    # heartbeat antigo: trava expirada
        pass
    a.execute("DELETE FROM run_lock"); a.execute("INSERT INTO run_lock VALUES(1,'x','y',?,?)", (now(), now())); a.commit()    # heartbeat fresco
    with pytest.raises(RunInProgress):
        with exclusive_run(b, "nova"):
            pass
    force_release(b)
    with exclusive_run(b, "nova"):
        pass
    a.close(); b.close()


def test_pipeline_refuses_parallel_run_and_releases_on_error(conn):
    class Boom:
        def get_pages(self, *a): raise KeyboardInterrupt
    other = Candidate(name="Qualquer", domain="x.example")
    with exclusive_run(conn, "externa"):
        with pytest.raises(RunInProgress):
            run_pipeline(conn, [other], FixtureSource(SITES), get_settings())
    with pytest.raises(KeyboardInterrupt):
        run_pipeline(conn, [other], Boom(), get_settings())
    assert current_holder(conn) is None                                   # liberou mesmo com a rodada interrompida
    assert conn.execute("SELECT finished_at FROM search_run ORDER BY id DESC LIMIT 1").fetchone()[0]


def test_similar_leads_are_analyzed_once_per_run(conn):
    cands = [Candidate(name="Alfa Manutencao Industrial", domain="manutencao-sul.example"),
             Candidate(name="Alfa Manutencao Industrial Ltda", domain=None),
             Candidate(name="Clinica Vida Odontologia", domain="clinica-vida.example")]
    seen = []
    rid = run_pipeline(conn, cands, FixtureSource(SITES), get_settings(), progress=lambda n, r: seen.append(r["status"]))
    assert seen.count("duplicate") == 1 and conn.execute("SELECT COUNT(*) FROM analysis WHERE run_id=?", (rid,)).fetchone()[0] == 2
    assert '"skipped_similar": 1' in conn.execute("SELECT metrics FROM search_run WHERE id=?", (rid,)).fetchone()[0]


# --- ranking em SQL ---------------------------------------------------------------------------------------------------
def test_ranking_limit_service_and_order(conn):
    rid = _demo_run(conn)
    full = ranking(conn, rid)
    assert [r["rank"] for r in full] == list(range(1, len(full) + 1))
    assert [r["score"] for r in full] == sorted((r["score"] for r in full), reverse=True)
    assert ranking(conn, rid, limit=2) == full[:2]
    by_service = ranking(conn, service="software")
    assert [r["score"] for r in by_service] == sorted((r["service_scores"]["software"] for r in by_service), reverse=True)
    with pytest.raises(ValueError):
        ranking(conn, service="'; DROP TABLE analysis;--")


# --- indices em memoria equivalem a varredura completa ------------------------------------------------------------------
def _brute_known(rows, name, domain):
    from difflib import SequenceMatcher
    from app.core.utils import norm_domain
    nn, best, best_r = norm_name(name), None, 0.0
    for r in rows:
        if domain and r["domain"] and norm_domain(r["domain"]) == norm_domain(domain):
            return r["name"]
        ratio = SequenceMatcher(None, nn, r["name_norm"]).ratio()
        if r["name_norm"] and (r["name_norm"] in nn or nn in r["name_norm"]) and min(len(nn), len(r["name_norm"])) >= 5:
            ratio = max(ratio, 0.9)
        if ratio > best_r:
            best, best_r = r, ratio
    return best["name"] if best is not None and best_r >= 0.85 else None


def test_known_lead_index_matches_bruteforce(conn):
    rnd = random.Random(5)
    words = ["alfa", "beta", "gama", "delta", "industria", "comercio", "servicos", "tecnica", "norte", "sul", "helibras", "diavicon"]
    names = list({" ".join(rnd.sample(words, rnd.randint(1, 3))) for _ in range(60)})
    for n in names:
        conn.execute("INSERT INTO known_lead(name,name_norm,outcome,is_person) VALUES(?,?,?,0)", (n, norm_name(n), "lost"))
    rows = conn.execute("SELECT * FROM known_lead").fetchall()
    index = antiicp.KnownLeadIndex.from_db(conn)
    for _ in range(120):
        probe = " ".join(rnd.sample(words, rnd.randint(1, 3))) + rnd.choice(["", " ltda", " sa", "s"])
        got = index.match(probe, None)
        assert (got["name"] if got else None) == _brute_known(rows, probe, None), probe


def test_org_index_is_shared_across_a_batch(conn):
    index = OrgIndex.from_db(conn)
    a, _ = upsert_org(conn, Candidate(name="Padaria Pao Quente", domain="pao.example"), index)
    b, new_b = upsert_org(conn, Candidate(name="Outra Empresa Qualquer", domain="https://www.pao.example/"), index)
    assert a == b and not new_b                                           # mesmo dominio, achado pelo indice sem reler a tabela
    c, new_c = upsert_org(conn, Candidate(name="Padaria Pao Quente Ltda"), index)
    assert c == a and not new_c
