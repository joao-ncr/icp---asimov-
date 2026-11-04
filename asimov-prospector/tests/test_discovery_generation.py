"""Geracao de leads novos a partir de um CSV de dados abertos de CNPJ, filtrado por ICP (config/icp.yaml).
Sem rede: os candidatos ficam pendentes de aprovacao humana - nunca viram organizacao sozinhos (ver
test_discovery_review.py para a decisao). Cobre tambem a trava de intervalo minimo e o nao-resurgimento de CNPJ
ja visto (pendente, aprovado ou rejeitado)."""
import io
from datetime import datetime, timedelta, timezone
import pytest
from app.discovery import generation as gen
from app.discovery import review
from app.discovery.dedup import upsert_org
from app.models.schemas import Candidate

CSV_HEADER = "cnpj,razao_social,nome_fantasia,cnae,uf,municipio,porte,situacao\n"
ROW_MATCH = "11.222.333/0001-44,Industria Alfa LTDA,Industria Alfa,2512-8,MG,Itajuba,PEQUENA,ATIVA"
ROW_OTHER_UF = "22.333.444/0001-55,Industria Fora,Industria Fora,2512-8,SP,Campinas,PEQUENA,ATIVA"
ROW_INACTIVE = "33.444.555/0001-66,Industria Baixada,Industria Baixada,2512-8,MG,Itajuba,PEQUENA,BAIXADA"
ROW_NO_CNAE_MATCH = "44.555.666/0001-77,Comercio Qualquer,Comercio Qualquer,4711-3,MG,Itajuba,PEQUENA,ATIVA"
ROW_NO_CNPJ = ",Sem Cnpj,Sem Cnpj,2512-8,MG,Itajuba,PEQUENA,ATIVA"


def _csv(*rows: str) -> io.BytesIO:
    return io.BytesIO((CSV_HEADER + "\n".join(rows)).encode("utf-8-sig"))


def _run(conn, *rows: str, filename: str = "extrato.csv", by: str = "ana"):
    return gen.run_generation(conn, _csv(*rows), filename, by)


def _allow_next_generation(conn) -> None:
    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(timespec="seconds")
    conn.execute("UPDATE discovery_generation SET finished_at=?", (past,))
    conn.commit()


def test_generation_matches_by_cnae_uf_and_municipio(conn):
    report = _run(conn, ROW_MATCH, ROW_OTHER_UF, ROW_INACTIVE, ROW_NO_CNAE_MATCH)
    assert (report.rows_total, report.matched, report.new_candidates) == (4, 1, 1)
    pending = review.pending_candidates(conn)
    assert len(pending) == 1 and pending[0]["cnpj"] == "11222333000144"
    assert pending[0]["rationale"].startswith("ICP:")


def test_nothing_becomes_an_organization_before_approval(conn):
    _run(conn, ROW_MATCH)
    assert conn.execute("SELECT COUNT(*) FROM organization").fetchone()[0] == 0


def test_existing_organization_is_not_resuggested(conn):
    upsert_org(conn, Candidate(name="Industria Alfa", cnpj="11222333000144"))
    report = _run(conn, ROW_MATCH)
    assert (report.new_candidates, report.duplicates) == (0, 1)
    assert review.pending_candidates(conn) == []


def test_second_generation_is_throttled(conn):
    _run(conn, ROW_MATCH)
    with pytest.raises(gen.GenerationTooSoon):
        _run(conn, ROW_OTHER_UF, filename="extrato2.csv")


def test_same_cnpj_is_not_suggested_twice_across_generations(conn):
    _run(conn, ROW_MATCH)
    _allow_next_generation(conn)
    report = _run(conn, ROW_MATCH, filename="extrato2.csv")
    assert (report.new_candidates, report.duplicates) == (0, 1)
    assert len(review.pending_candidates(conn)) == 1          # nao duplicou a linha pendente


def test_rejected_candidate_is_not_resuggested(conn):
    _run(conn, ROW_MATCH)
    review.decide(conn, [review.pending_candidates(conn)[0]["id"]], False, "ana")
    _allow_next_generation(conn)
    report = _run(conn, ROW_MATCH, filename="extrato2.csv")
    assert (report.new_candidates, report.duplicates) == (0, 1)
    assert review.pending_candidates(conn) == []


def test_row_without_cnpj_is_skipped_not_inserted(conn):
    report = _run(conn, ROW_NO_CNPJ)
    assert (report.skipped_without_cnpj, report.new_candidates) == (1, 0)


def test_generation_writes_audit_trail(conn):
    _run(conn, ROW_MATCH)
    row = conn.execute("SELECT status, triggered_by, filename FROM discovery_generation").fetchone()
    assert (row["status"], row["triggered_by"], row["filename"]) == ("ok", "ana", "extrato.csv")


def test_failed_generation_is_audited_and_releases_the_lock(conn, monkeypatch):
    monkeypatch.setattr(gen, "candidates_from_cnpj_rows", lambda *a, **k: (_ for _ in ()).throw(ValueError("config quebrada")))
    with pytest.raises(ValueError):
        _run(conn, ROW_MATCH)
    row = conn.execute("SELECT status, error FROM discovery_generation").fetchone()
    assert row["status"] == "error" and "config quebrada" in row["error"]
    assert conn.execute("SELECT COUNT(*) FROM run_lock").fetchone()[0] == 0


def test_generation_interval_math():
    moment = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    assert gen.seconds_until_allowed(None, moment, 300) == 0
    assert gen.seconds_until_allowed("2026-11-04T11:58:00+00:00", moment, 300) == 180
    assert gen.seconds_until_allowed("2026-11-04T11:00:00+00:00", moment, 300) == 0
