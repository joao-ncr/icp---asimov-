"""Decisao humana sobre candidatos gerados: aprovar cria organizacao e liga org_id; rejeitar nao cria nada.
Candidatos ja decididos somem da fila e uma segunda decisao sobre eles e inocua."""
import io
from app.discovery import generation as gen
from app.discovery import review

CSV = ("cnpj,razao_social,nome_fantasia,cnae,uf,municipio,porte,situacao\n"
       "11.222.333/0001-44,Industria Alfa LTDA,Industria Alfa,2512-8,MG,Itajuba,PEQUENA,ATIVA\n")


def _generated_candidate_id(conn) -> int:
    gen.run_generation(conn, io.BytesIO(CSV.encode("utf-8-sig")), "extrato.csv", "ana")
    return review.pending_candidates(conn)[0]["id"]


def test_approving_creates_an_organization_and_links_it(conn):
    candidate_id = _generated_candidate_id(conn)
    approved = review.decide(conn, [candidate_id], True, "beto")
    assert len(approved) == 1 and approved[0].cnpj == "11222333000144"
    row = conn.execute("SELECT status, org_id, decided_by FROM discovery_candidate WHERE id=?", (candidate_id,)).fetchone()
    assert row["status"] == "approved" and row["org_id"] is not None and row["decided_by"] == "beto"
    org = conn.execute("SELECT name, cnpj, source FROM organization WHERE id=?", (row["org_id"],)).fetchone()
    assert (org["name"], org["cnpj"], org["source"]) == ("Industria Alfa", "11222333000144", "discovery_cnpj")


def test_rejecting_creates_no_organization(conn):
    candidate_id = _generated_candidate_id(conn)
    approved = review.decide(conn, [candidate_id], False, "beto")
    assert approved == []
    row = conn.execute("SELECT status, org_id FROM discovery_candidate WHERE id=?", (candidate_id,)).fetchone()
    assert row["status"] == "rejected" and row["org_id"] is None
    assert conn.execute("SELECT COUNT(*) FROM organization").fetchone()[0] == 0


def test_deciding_an_already_decided_candidate_is_a_no_op(conn):
    candidate_id = _generated_candidate_id(conn)
    review.decide(conn, [candidate_id], True, "beto")
    assert review.decide(conn, [candidate_id], True, "ana") == []
    assert conn.execute("SELECT COUNT(*) FROM organization").fetchone()[0] == 1   # nao duplicou a organizacao


def test_pending_candidates_disappear_after_decision(conn):
    candidate_id = _generated_candidate_id(conn)
    review.decide(conn, [candidate_id], True, "beto")
    assert review.pending_candidates(conn) == []


def test_deciding_with_no_ids_is_a_no_op(conn):
    assert review.decide(conn, [], True, "beto") == []
