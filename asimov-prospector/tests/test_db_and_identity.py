import sqlite3
import pytest
from app.core.profile import seed_db
from app.core.settings import get_settings
from app.database.db import connect, init_db, session
from app.discovery.dedup import upsert_org
from app.models.schemas import Candidate
from app.pipeline import analyze_org, run_pipeline, start_run
from app.scoring.score import canonical_segment, detect_segment


def test_canonical_segment():
    assert canonical_segment("Imobiliária") == "imobiliario"
    assert canonical_segment("Escola de inglês") == "educacao"
    assert canonical_segment("industria") == "industria"
    assert canonical_segment("Moveleiro") == "industria"
    assert canonical_segment("algo desconhecido") is None
    assert detect_segment("texto sem pistas", "algo desconhecido") == "default"


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
